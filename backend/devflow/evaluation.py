from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal

from pydantic import BaseModel, Field

from devflow.models import AgentState, RiskLevel, StepStatus, TaskStatus, utc_now


class EvaluationDimension(BaseModel):
    key: Literal["completion", "evidence", "safety", "auditability", "reliability"]
    label: str
    score: float = Field(ge=0, le=100)
    weight: float = Field(gt=0, le=1)
    status: Literal["pass", "warning", "fail"]
    explanation: str
    checks: list[str] = Field(default_factory=list)


class EvaluationReport(BaseModel):
    task_id: str
    overall_score: float = Field(ge=0, le=100)
    grade: Literal["A+", "A", "B", "C", "F"]
    passed: bool
    evaluated_at: str = Field(default_factory=utc_now)
    dimensions: list[EvaluationDimension]
    gate_failures: list[str] = Field(default_factory=list)


class TaskEvaluator:
    """Deterministic, explainable quality gates for a completed or paused task."""

    weights = {
        "completion": 0.25,
        "evidence": 0.25,
        "safety": 0.25,
        "auditability": 0.15,
        "reliability": 0.10,
    }

    def evaluate(self, state: AgentState, events: Sequence[dict[str, Any]]) -> EvaluationReport:
        dimensions = [
            self._completion(state),
            self._evidence(state),
            self._safety(state, events),
            self._auditability(state, events),
            self._reliability(state),
        ]
        gate_failures = self._gate_failures(state)
        overall = round(sum(item.score * item.weight for item in dimensions), 1)
        passed = overall >= 85 and not gate_failures
        return EvaluationReport(
            task_id=state["task_id"],
            overall_score=overall,
            grade=self._grade(overall, gate_failures),
            passed=passed,
            dimensions=dimensions,
            gate_failures=gate_failures,
        )

    def _completion(self, state: AgentState) -> EvaluationDimension:
        steps = state.get("plan", {}).get("steps", [])
        succeeded = sum(step.get("status") == StepStatus.SUCCEEDED.value for step in steps)
        terminal_safe = sum(
            step.get("status") in {StepStatus.SKIPPED.value, StepStatus.BLOCKED.value} for step in steps
        )
        score = 0.0 if not steps else min(100.0, (succeeded + terminal_safe * 0.7) / len(steps) * 100)
        checks = [f"{succeeded}/{len(steps)} 个步骤成功"]
        if terminal_safe:
            checks.append(f"{terminal_safe} 个步骤处于安全暂停或跳过状态")
        return self._dimension(
            "completion",
            "任务完成度",
            score,
            f"工作流已完成 {succeeded} 个受控步骤。",
            checks,
        )

    def _evidence(self, state: AgentState) -> EvaluationDimension:
        evidence = state.get("evidence", [])
        source_types = {item.get("source_type") for item in evidence if item.get("source_type")}
        has_analysis = any(item.get("source_type") == "analysis" for item in evidence)
        complete_refs = sum(bool(item.get("source_uri") and item.get("content_hash")) for item in evidence)
        reference_ratio = complete_refs / len(evidence) if evidence else 0
        score = min(100.0, len(evidence) * 7 + len(source_types) * 6 + (15 if has_analysis else 0))
        score *= reference_ratio
        return self._dimension(
            "evidence",
            "证据完备性",
            score,
            f"收集 {len(evidence)} 条证据，覆盖 {len(source_types)} 类来源。",
            [
                f"{complete_refs}/{len(evidence)} 条证据具备 URI 与内容哈希",
                "包含根因分析证据" if has_analysis else "缺少根因分析证据",
            ],
        )

    def _safety(
        self,
        state: AgentState,
        events: Sequence[dict[str, Any]],
    ) -> EvaluationDimension:
        steps = state.get("plan", {}).get("steps", [])
        writes = [step for step in steps if step.get("risk_level") == RiskLevel.HIGH_WRITE.value]
        if not writes:
            return self._dimension("safety", "安全合规", 100, "任务未包含高风险写操作。", ["默认只读"])

        approval = state.get("pending_approval")
        event_types = {event.get("event_type") for event in events}
        approval_requested = next(
            (event for event in events if event.get("event_type") == "approval_requested"),
            None,
        )
        score = 0.0
        checks: list[str] = []
        if all(step.get("requires_approval") for step in writes):
            score += 35
            checks.append("所有高风险写操作均声明人工审批")
        hash_bound = bool(
            (approval and approval.get("arguments_hash"))
            or (approval_requested and approval_requested.get("payload", {}).get("arguments_hash"))
        )
        if hash_bound:
            score += 30
            checks.append("审批绑定精确参数哈希")

        status = state.get("status")
        approval_status = approval.get("status") if approval else None
        lifecycle_valid = (
            status == TaskStatus.WAITING_APPROVAL.value and approval_status == "pending"
        ) or (
            status == TaskStatus.REJECTED.value and approval_status == "rejected"
        ) or (
            status == TaskStatus.COMPLETED.value
            and approval is None
            and "approval_approved" in event_types
        )
        if lifecycle_valid:
            score += 35
            checks.append("审批状态与任务生命周期一致")
        return self._dimension(
            "safety",
            "安全合规",
            score,
            "高风险写操作经过策略检查、参数绑定与人工决策。",
            checks,
        )

    def _auditability(
        self,
        state: AgentState,
        events: Sequence[dict[str, Any]],
    ) -> EvaluationDimension:
        required = {
            "task_created",
            "intent_detected",
            "plan_created",
            "skill_selected",
            "tool_started",
            "tool_succeeded",
        }
        present = {event.get("event_type") for event in events}
        coverage = len(required & present) / len(required)
        ordered = all(
            int(events[index]["event_id"]) < int(events[index + 1]["event_id"])
            for index in range(len(events) - 1)
        )
        score = coverage * 85 + (15 if ordered and events else 0)
        return self._dimension(
            "auditability",
            "审计可追溯性",
            score,
            f"记录 {len(events)} 条有序执行事件。",
            [f"核心事件覆盖率 {coverage:.0%}", "事件序列有序" if ordered else "事件序列异常"],
        )

    def _reliability(self, state: AgentState) -> EvaluationDimension:
        errors = state.get("errors", [])
        steps = state.get("plan", {}).get("steps", [])
        failed = [step for step in steps if step.get("status") == StepStatus.FAILED.value]
        score = 100.0 - min(60, len(errors) * 30) - min(40, len(failed) * 20)
        return self._dimension(
            "reliability",
            "执行可靠性",
            score,
            "执行链未发现失败。" if not errors and not failed else "执行链存在需要处理的失败。",
            [f"{len(errors)} 个运行错误", f"{len(failed)} 个失败步骤"],
        )

    def _gate_failures(self, state: AgentState) -> list[str]:
        failures: list[str] = []
        steps = state.get("plan", {}).get("steps", [])
        if any(step.get("risk_level") == RiskLevel.PROHIBITED.value for step in steps):
            failures.append("计划包含禁止执行的工具风险等级")
        if any(
            step.get("risk_level") == RiskLevel.HIGH_WRITE.value and not step.get("requires_approval")
            for step in steps
        ):
            failures.append("高风险写操作未声明人工审批")
        evidence = state.get("evidence", [])
        if evidence and any(not item.get("source_uri") or not item.get("content_hash") for item in evidence):
            failures.append("存在无法回溯来源或缺少内容哈希的证据")
        if state.get("status") == TaskStatus.COMPLETED.value and state.get("pending_approval"):
            failures.append("任务已完成但仍残留待处理审批")
        return failures

    def _dimension(
        self,
        key: Literal["completion", "evidence", "safety", "auditability", "reliability"],
        label: str,
        score: float,
        explanation: str,
        checks: list[str],
    ) -> EvaluationDimension:
        bounded = round(max(0.0, min(100.0, score)), 1)
        status: Literal["pass", "warning", "fail"] = (
            "pass" if bounded >= 85 else "warning" if bounded >= 60 else "fail"
        )
        return EvaluationDimension(
            key=key,
            label=label,
            score=bounded,
            weight=self.weights[key],
            status=status,
            explanation=explanation,
            checks=checks,
        )

    @staticmethod
    def _grade(score: float, gate_failures: list[str]) -> Literal["A+", "A", "B", "C", "F"]:
        if gate_failures:
            return "F"
        if score >= 95:
            return "A+"
        if score >= 85:
            return "A"
        if score >= 75:
            return "B"
        if score >= 60:
            return "C"
        return "F"
