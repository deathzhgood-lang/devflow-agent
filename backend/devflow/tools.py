from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from pydantic import ValidationError

from devflow.llm import DeepSeekEvidenceReasoner, LLMError
from devflow.models import ApprovalState, Evidence, PlanStep, RiskLevel, ToolResult, utc_now
from devflow.store import SQLiteStore


ToolHandler = Callable[[dict[str, Any], dict[str, Any]], ToolResult]


def stable_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def make_evidence(source_type: str, source_uri: str, summary: str, raw_ref: str) -> Evidence:
    return Evidence(
        evidence_id=f"ev_{uuid4().hex[:12]}",
        source_type=source_type,
        source_uri=source_uri,
        content_hash=stable_hash({"source_uri": source_uri, "summary": summary}),
        summary=summary,
        raw_ref=raw_ref,
    )


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    risk_level: RiskLevel
    required_role: str | None
    handler: ToolHandler


class LocalToolRegistry:
    def __init__(
        self,
        fixture_root: Path,
        report_dir: Path,
        evidence_reasoner: DeepSeekEvidenceReasoner | None = None,
    ):
        self.fixture_root = fixture_root
        self.report_dir = report_dir
        self.evidence_reasoner = evidence_reasoner
        self.report_dir.mkdir(parents=True, exist_ok=True)
        self._tools: dict[str, ToolDefinition] = {}
        self._register_defaults()

    def _read_json(self, name: str) -> Any:
        path = self.fixture_root / name
        return json.loads(path.read_text(encoding="utf-8"))

    def register(self, definition: ToolDefinition) -> None:
        if definition.name in self._tools:
            raise ValueError(f"Duplicate tool: {definition.name}")
        self._tools[definition.name] = definition

    def get(self, name: str) -> ToolDefinition:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise KeyError(f"Unknown tool: {name}") from exc

    def _register_defaults(self) -> None:
        self.register(ToolDefinition("query_metrics", "Read bounded service metrics", RiskLevel.READ, None, self._query_metrics))
        self.register(ToolDefinition("search_logs", "Search redacted service logs", RiskLevel.READ, None, self._search_logs))
        self.register(ToolDefinition("search_knowledge", "Search historical incidents", RiskLevel.READ, None, self._search_knowledge))
        self.register(ToolDefinition("list_commits", "List bounded Git changes", RiskLevel.READ, None, self._list_commits))
        self.register(ToolDefinition("correlate_evidence", "Correlate collected evidence", RiskLevel.READ, None, self._correlate_evidence))
        self.register(ToolDefinition("write_report", "Write a report inside task sandbox", RiskLevel.LOW_WRITE, None, self._write_report))
        self.register(ToolDefinition("create_issue", "Create an idempotent remediation issue", RiskLevel.HIGH_WRITE, "git-writer", self._create_issue))

    def _query_metrics(self, args: dict[str, Any], context: dict[str, Any]) -> ToolResult:
        data = self._read_json("metrics.json")
        if args["service"] != data["service"]:
            return ToolResult(ok=False, summary="服务无模拟指标数据", error_code="not_found")
        anomalies = data["anomalies"]
        summary = f"发现 {len(anomalies)} 个异常窗口，最高错误率 {max(item['error_rate'] for item in anomalies):.1%}。"
        evidence = make_evidence("metric", "metrics://payment/30d", summary, "fixtures/payment_incident/metrics.json")
        return ToolResult(ok=True, summary=summary, data=data, evidence=[evidence])

    def _search_logs(self, args: dict[str, Any], context: dict[str, Any]) -> ToolResult:
        rows = [row for row in self._read_json("logs.json") if row["service"] == args["service"]]
        summary = f"检索到 {len(rows)} 条关键日志；主要模式为 Redis 连接池耗尽、等待和超时。"
        evidence = make_evidence("log", "logs://payment/incidents", summary, "fixtures/payment_incident/logs.json")
        return ToolResult(ok=True, summary=summary, data={"events": rows, "truncated": False}, evidence=[evidence])

    def _search_knowledge(self, args: dict[str, Any], context: dict[str, Any]) -> ToolResult:
        rows = self._read_json("knowledge.json")
        summary = f"找到 {len(rows)} 条相关历史知识，最高匹配为“{rows[0]['title']}”。"
        evidence = [
            make_evidence("knowledge", row["source_uri"], row["summary"], f"{row['document_id']}#{row['chunk_id']}")
            for row in rows
        ]
        return ToolResult(ok=True, summary=summary, data={"matches": rows}, evidence=evidence)

    def _list_commits(self, args: dict[str, Any], context: dict[str, Any]) -> ToolResult:
        rows = self._read_json("commits.json")
        summary = f"找到 {len(rows)} 次近期变更；a9c4d21 修改连接释放路径，与首次异常时间接近。"
        evidence = [
            make_evidence("git", row["source_uri"], row["summary"], row["sha"])
            for row in rows
        ]
        return ToolResult(ok=True, summary=summary, data={"commits": rows}, evidence=evidence)

    def _correlate_evidence(self, args: dict[str, Any], context: dict[str, Any]) -> ToolResult:
        evidence = context.get("evidence", [])
        evidence_ids = [item["evidence_id"] for item in evidence]
        metadata: dict[str, Any] = {"mode": "deterministic"}
        confidence = 0.88
        supporting_evidence_ids = evidence_ids
        unverified = ["需要通过连接泄漏压测复现", "第二次异常需验证网络层 reset"]
        if self.evidence_reasoner:
            try:
                reasoned, metadata = self.evidence_reasoner.reason(evidence, context["task_id"])
                summary = reasoned.summary
                confidence = reasoned.confidence
                supporting_evidence_ids = reasoned.supporting_evidence_ids
                unverified = reasoned.unverified
            except (LLMError, ValidationError, ValueError) as exc:
                if not self.evidence_reasoner.fallback_enabled:
                    return ToolResult(
                        ok=False,
                        summary="DeepSeek 证据推理失败，且已禁用确定性回退",
                        error_code="llm_reasoning_failed",
                        retryable=True,
                    )
                metadata = {
                    "mode": "deterministic_fallback",
                    "provider": "deepseek",
                    "fallback_reason": type(exc).__name__,
                }
                summary = (
                    "高置信根因假设：异常前的 session cleanup 重构使异常分支未释放 Redis 连接，"
                    "在高峰期导致连接池耗尽；第二次短时异常可能是网络 reset，需要单独验证。"
                )
        else:
            summary = (
                "高置信根因假设：异常前的 session cleanup 重构使异常分支未释放 Redis 连接，"
                "在高峰期导致连接池耗尽；第二次短时异常可能是网络 reset，需要单独验证。"
            )
        result_evidence = make_evidence(
            "analysis",
            f"analysis://{context['task_id']}/root-cause",
            summary,
            ",".join(supporting_evidence_ids),
        )
        return ToolResult(
            ok=True,
            summary=summary,
            data={
                "confidence": confidence,
                "supporting_evidence_ids": supporting_evidence_ids,
                "unverified": unverified,
                "llm": metadata,
            },
            evidence=[result_evidence],
        )

    def _write_report(self, args: dict[str, Any], context: dict[str, Any]) -> ToolResult:
        task_id = context["task_id"]
        target = (self.report_dir / f"{task_id}.md").resolve()
        root = self.report_dir.resolve()
        if root not in target.parents:
            return ToolResult(ok=False, summary="非法报告路径", error_code="path_denied")
        evidence = context.get("evidence", [])
        lines = [
            f"# {args['service']} 服务异常复盘（MVP 自动草稿）",
            "",
            f"- 任务 ID：`{task_id}`",
            f"- 调查范围：最近 {args['days']} 天",
            f"- 生成时间：{utc_now()}",
            "",
            "## 执行摘要",
            "",
            "支付服务出现两次异常窗口。证据表明第一次异常与 Redis 连接未在异常路径释放高度相关；第二次短时异常仍需验证网络 reset。",
            "",
            "## 根因假设",
            "",
            "`a9c4d21` 将连接释放移入成功分支，异常路径可能泄漏连接；高峰期 active 达到 max 后触发等待、重试与超时。",
            "",
            "## 证据",
            "",
        ]
        lines.extend(f"- [{item['evidence_id']}] {item['summary']} — `{item['source_uri']}`" for item in evidence)
        lines.extend(
            [
                "",
                "## 未验证项",
                "",
                "- 使用故障注入测试验证异常路径连接释放。",
                "- 单独排查第二次 connection reset 的网络证据。",
                "",
                "## 整改建议",
                "",
                "1. 恢复 finally 中统一释放连接并增加单元测试。",
                "2. 增加连接池 active/max/wait 告警与容量压测。",
                "3. 将异常路径覆盖加入发布门禁。",
            ]
        )
        target.write_text("\n".join(lines) + "\n", encoding="utf-8")
        summary = f"复盘报告已写入任务沙箱：{target.name}"
        report_evidence = make_evidence("file", target.as_uri(), summary, str(target))
        return ToolResult(ok=True, summary=summary, data={"report_path": str(target)}, evidence=[report_evidence])

    def _create_issue(self, args: dict[str, Any], context: dict[str, Any]) -> ToolResult:
        issue_id = f"ISSUE-{stable_hash({'task': context['task_id'], 'title': args['title']})[:8].upper()}"
        summary = f"已创建整改 Issue：{issue_id}（模拟）"
        return ToolResult(
            ok=True,
            summary=summary,
            data={"issue_id": issue_id, "title": args["title"], "status": "open"},
            external_resource_id=issue_id,
        )


class ToolRouter:
    def __init__(self, registry: LocalToolRegistry, store: SQLiteStore):
        self.registry = registry
        self.store = store

    def build_arguments(self, step: PlanStep, state: dict[str, Any]) -> dict[str, Any]:
        intent = state["intent"]
        service = intent["service"]
        days = intent["days"]
        mapping: dict[str, dict[str, Any]] = {
            "query_metrics": {"service": service, "days": days},
            "search_logs": {"service": service, "days": days, "query": "error OR timeout OR pool"},
            "search_knowledge": {"query": f"{service} Redis 连接池 异常 故障", "top_k": 5},
            "list_commits": {"repository": service, "days": days},
            "correlate_evidence": {"evidence_ids": [item["evidence_id"] for item in state.get("evidence", [])]},
            "write_report": {"service": service, "days": days},
            "create_issue": {
                "repository": service,
                "title": f"[{service}] 修复 Redis 异常路径连接泄漏并补充回归测试",
                "report_ref": next(
                    (item["raw_ref"] for item in reversed(state.get("evidence", [])) if item["source_type"] == "file"),
                    "",
                ),
            },
        }
        return mapping[step.tool_name]

    def make_approval(self, state: dict[str, Any], step: PlanStep, arguments: dict[str, Any]) -> ApprovalState:
        return ApprovalState(
            approval_id=f"ap_{uuid4().hex[:12]}",
            step_id=step.step_id,
            tool_name=step.tool_name,
            arguments=arguments,
            arguments_hash=stable_hash(arguments),
        )

    def execute(self, state: dict[str, Any], step: PlanStep, arguments: dict[str, Any]) -> ToolResult:
        definition = self.registry.get(step.tool_name)
        if definition.risk_level != step.risk_level:
            return ToolResult(ok=False, summary="计划风险等级与工具定义不一致", error_code="risk_mismatch")
        if definition.required_role and definition.required_role not in state.get("user_roles", []):
            return ToolResult(ok=False, summary="当前用户无工具写权限", error_code="policy_denied")

        if step.requires_approval:
            approval = state.get("pending_approval") or {}
            if approval.get("status") != "approved":
                return ToolResult(ok=False, summary="工具调用尚未审批", error_code="approval_required")
            if approval.get("arguments_hash") != stable_hash(arguments):
                return ToolResult(ok=False, summary="工具参数已变化，需要重新审批", error_code="approval_stale")

        context = {**state, "evidence": state.get("evidence", [])}
        if definition.risk_level in {RiskLevel.LOW_WRITE, RiskLevel.HIGH_WRITE}:
            key = stable_hash(
                {"task_id": state["task_id"], "step_id": step.step_id, "arguments": arguments}
            )
            previous = self.store.get_idempotent_result(key)
            if previous:
                return ToolResult.model_validate(previous)
            if not self.store.reserve_idempotency(key, state["task_id"], step.step_id):
                previous = self.store.get_idempotent_result(key)
                if previous:
                    return ToolResult.model_validate(previous)
                return ToolResult(ok=False, summary="同一写操作正在执行，请稍后查询", error_code="in_progress")
            result = definition.handler(arguments, context)
            if result.ok:
                self.store.complete_idempotency(key, result.model_dump(mode="json"))
            return result

        return definition.handler(arguments, context)
