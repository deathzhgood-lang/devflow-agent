from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from time import perf_counter
from typing import Any, Literal
from uuid import uuid4

from langgraph.graph import END, START, StateGraph

from devflow.config import PROJECT_ROOT, Settings, settings
from devflow.evaluation import EvaluationReport, TaskEvaluator
from devflow.llm import DeepSeekClient, DeepSeekEvidenceReasoner, LLMUnavailableError
from devflow.mcp_client import MCPToolClient, MCPToolGateway, build_inprocess_servers
from devflow.models import (
    AgentState,
    ApprovalDecision,
    ApprovalRequest,
    CreateTaskRequest,
    Event,
    PlanStep,
    StepStatus,
    TaskPlan,
    TaskStatus,
    TaskView,
    utc_now,
)
from devflow.observability import TASKS, TOOL_CALLS, TOOL_DURATION, tracer
from devflow.planner import DeterministicPlanner, HybridPlanner
from devflow.skills import SkillRegistry
from devflow.store import SQLiteStore
from devflow.tools import LocalToolRegistry, ToolRouter


class DevFlowRuntime:
    def __init__(self, app_settings: Settings = settings):
        self.settings = app_settings
        self.store = SQLiteStore(app_settings.db_path)
        self.llm_client: DeepSeekClient | None = None
        self.llm_mode = "deterministic"
        deterministic_planner = DeterministicPlanner()
        if app_settings.llm_enabled:
            try:
                self.llm_client = DeepSeekClient(app_settings)
                self.planner = HybridPlanner(
                    self.llm_client,
                    fallback=deterministic_planner,
                    fallback_enabled=app_settings.llm_fallback_enabled,
                )
                self.llm_mode = "deepseek_hybrid"
            except LLMUnavailableError:
                if not app_settings.llm_fallback_enabled:
                    raise
                self.planner = deterministic_planner
                self.llm_mode = "deterministic_missing_key"
        else:
            self.planner = deterministic_planner
        self.skills = SkillRegistry(PROJECT_ROOT / "skills")
        self.skills.load()
        evidence_reasoner = (
            DeepSeekEvidenceReasoner(
                self.llm_client,
                fallback_enabled=app_settings.llm_fallback_enabled,
            )
            if self.llm_client
            else None
        )
        self.local_tools = LocalToolRegistry(
            PROJECT_ROOT / "fixtures" / "payment_incident",
            app_settings.report_dir,
            evidence_reasoner=evidence_reasoner,
        )
        self.local_tool_router = ToolRouter(self.local_tools, self.store)
        self.mcp_servers = {}
        self.mcp_client = None
        if app_settings.tool_mode == "mcp":
            self.mcp_servers = build_inprocess_servers(
                self.store,
                self.local_tools,
                self.local_tool_router,
                app_settings,
            )
            self.mcp_client = MCPToolClient(self.mcp_servers)
            self.tool_router = MCPToolGateway(
                self.local_tool_router,
                self.mcp_client,
                timeout_seconds=app_settings.mcp_timeout_seconds,
                max_retries=app_settings.mcp_max_retries,
                tool_timeouts={
                    "search_knowledge": (
                        app_settings.knowledge_timeout_seconds
                        * (app_settings.knowledge_max_retries + 1)
                        + 5
                    )
                },
            )
        elif app_settings.tool_mode == "local":
            self.tool_router = self.local_tool_router
        else:
            raise ValueError(f"unsupported DEVFLOW_TOOL_MODE: {app_settings.tool_mode}")
        self.evaluator = TaskEvaluator()
        self.graph = self._build_graph()

    def _build_graph(self):
        builder = StateGraph(AgentState)
        builder.add_node("intent_detection", self._intent_node)
        builder.add_node("planning", self._planning_node)
        builder.add_node("skill_selection", self._skill_selection_node)
        builder.add_node("tool_execution", self._tool_execution_node)
        builder.add_node("reflection", self._reflection_node)
        builder.add_node("final_response", self._final_response_node)

        builder.add_edge(START, "intent_detection")
        builder.add_conditional_edges(
            "intent_detection",
            self._route_after_intent,
            {"plan": "planning", "final": "final_response"},
        )
        builder.add_conditional_edges(
            "planning",
            self._route_after_planning,
            {"select": "skill_selection", "final": "final_response"},
        )
        builder.add_edge("skill_selection", "tool_execution")
        builder.add_conditional_edges(
            "tool_execution",
            self._route_after_tool,
            {"reflect": "reflection", "pause": END},
        )
        builder.add_conditional_edges(
            "reflection",
            self._route_after_reflection,
            {"continue": "skill_selection", "final": "final_response"},
        )
        builder.add_edge("final_response", END)
        return builder.compile()

    def _save(
        self,
        state: AgentState,
        updates: dict[str, Any],
        *,
        node: str,
        event_type: str,
        message: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        merged: AgentState = {**state, **updates}
        merged["updated_at"] = utc_now()
        self.store.save_state(merged)
        self.store.add_event(
            Event(
                task_id=merged["task_id"],
                event_type=event_type,
                node=node,
                message=message,
                payload=payload or {},
            )
        )
        return updates

    def _intent_node(self, state: AgentState) -> dict[str, Any]:
        if state.get("intent"):
            return {}
        intent = self.planner.detect_intent(state["request"], state.get("request_context", {}))
        llm_metadata = self._planner_metadata()
        status = TaskStatus.NEEDS_CLARIFICATION if intent.clarification_questions else TaskStatus.RUNNING
        return self._save(
            state,
            {"intent": intent.model_dump(mode="json"), "status": status.value},
            node="intent_detection",
            event_type="intent_detected",
            message=f"识别为故障调查任务，服务：{intent.service or '待确认'}",
            payload={**intent.model_dump(mode="json"), "llm": llm_metadata},
        )

    def _planning_node(self, state: AgentState) -> dict[str, Any]:
        if state.get("plan"):
            return {}
        from devflow.models import IntentResult

        intent = IntentResult.model_validate(state["intent"])
        plan = self.planner.create_plan(intent)
        llm_metadata = self._planner_metadata()
        status = TaskStatus.NEEDS_CLARIFICATION if plan.status == "needs_clarification" else TaskStatus.RUNNING
        return self._save(
            state,
            {"plan": plan.model_dump(mode="json"), "status": status.value},
            node="planning",
            event_type="plan_created",
            message=f"生成 {len(plan.steps)} 步结构化计划",
            payload={"goal": plan.goal, "step_count": len(plan.steps), "llm": llm_metadata},
        )

    def _skill_selection_node(self, state: AgentState) -> dict[str, Any]:
        plan = TaskPlan.model_validate(state["plan"])
        succeeded = {step.step_id for step in plan.steps if step.status == StepStatus.SUCCEEDED}
        selected_index: int | None = None
        for index, step in enumerate(plan.steps):
            if step.status == StepStatus.PENDING and set(step.depends_on).issubset(succeeded):
                selected_index = index
                break
        if selected_index is None:
            return self._save(
                state,
                {"selected_skill": None},
                node="skill_selection",
                event_type="skill_selection_empty",
                message="没有可执行的待办步骤",
            )

        step = plan.steps[selected_index]
        skill = self.skills.get(step.skill_id)
        self.skills.validate_binding(step.skill_id, step.tool_name)
        return self._save(
            state,
            {"selected_skill": f"{skill.skill_id}@{skill.version}", "current_step_index": selected_index},
            node="skill_selection",
            event_type="skill_selected",
            message=f"选择 Skill：{skill.name} v{skill.version}",
            payload={"step_id": step.step_id, "tool_name": step.tool_name},
        )

    def _tool_execution_node(self, state: AgentState) -> dict[str, Any]:
        plan = TaskPlan.model_validate(state["plan"])
        index = state.get("current_step_index", 0)
        step = plan.steps[index]
        arguments = self.tool_router.build_arguments(step, state)

        if step.requires_approval:
            approval = state.get("pending_approval")
            if not approval or approval.get("status") == "pending":
                if not approval:
                    approval = self.tool_router.make_approval(state, step, arguments).model_dump(mode="json")
                step.status = StepStatus.BLOCKED
                plan.steps[index] = step
                return self._save(
                    state,
                    {
                        "plan": plan.model_dump(mode="json"),
                        "pending_approval": approval,
                        "status": TaskStatus.WAITING_APPROVAL.value,
                    },
                    node="tool_execution",
                    event_type="approval_requested",
                    message=f"工具 {step.tool_name} 等待人工审批",
                    payload=approval,
                )

        step.status = StepStatus.RUNNING
        plan.steps[index] = step
        interim: AgentState = {**state, "plan": plan.model_dump(mode="json")}
        self.store.save_state(interim)
        self.store.add_event(
            Event(
                task_id=state["task_id"],
                event_type="tool_started",
                node="tool_execution",
                message=f"执行 {step.tool_name}",
                payload={"step_id": step.step_id, "arguments": arguments},
            )
        )

        started = perf_counter()
        with tracer.start_as_current_span(f"tool.{step.tool_name}") as span:
            span.set_attribute("devflow.task_id", state["task_id"])
            span.set_attribute("devflow.step_id", step.step_id)
            span.set_attribute("devflow.skill_id", step.skill_id)
            result = self.tool_router.execute(interim, step, arguments)
            span.set_attribute("devflow.tool.ok", result.ok)
            if result.error_code:
                span.set_attribute("devflow.tool.error_code", result.error_code)
        TOOL_DURATION.labels(tool=step.tool_name).observe(perf_counter() - started)
        TOOL_CALLS.labels(tool=step.tool_name, status="ok" if result.ok else "error").inc()
        step.status = StepStatus.SUCCEEDED if result.ok else StepStatus.FAILED
        step.result_summary = result.summary
        plan.steps[index] = step
        evidence = [*state.get("evidence", []), *[item.model_dump(mode="json") for item in result.evidence]]
        results = [
            *state.get("tool_results", []),
            {
                "step_id": step.step_id,
                "tool_name": step.tool_name,
                "arguments": arguments,
                "result": result.model_dump(mode="json"),
            },
        ]
        updates: dict[str, Any] = {
            "plan": plan.model_dump(mode="json"),
            "evidence": evidence,
            "tool_results": results,
            "status": TaskStatus.RUNNING.value if result.ok else TaskStatus.FAILED.value,
            "pending_approval": None if result.ok else state.get("pending_approval"),
        }
        if not result.ok:
            updates["errors"] = [
                *state.get("errors", []),
                {"step_id": step.step_id, "code": result.error_code, "message": result.summary},
            ]
        return self._save(
            state,
            updates,
            node="tool_execution",
            event_type="tool_succeeded" if result.ok else "tool_failed",
            message=result.summary,
            payload={"step_id": step.step_id, "tool_name": step.tool_name, "ok": result.ok},
        )

    def _reflection_node(self, state: AgentState) -> dict[str, Any]:
        plan = TaskPlan.model_validate(state["plan"])
        failed = [step for step in plan.steps if step.status == StepStatus.FAILED]
        pending = [step for step in plan.steps if step.status == StepStatus.PENDING]
        if failed:
            status = TaskStatus.FAILED.value
            message = f"质量门发现失败步骤：{', '.join(step.step_id for step in failed)}"
        elif pending:
            status = TaskStatus.RUNNING.value
            message = f"证据门通过，继续执行剩余 {len(pending)} 步"
        else:
            status = TaskStatus.RUNNING.value
            message = f"全部步骤完成，共收集 {len(state.get('evidence', []))} 条证据"
        return self._save(
            state,
            {"status": status},
            node="reflection",
            event_type="reflection_completed",
            message=message,
            payload={"failed": len(failed), "pending": len(pending), "evidence": len(state.get("evidence", []))},
        )

    def _final_response_node(self, state: AgentState) -> dict[str, Any]:
        status = state.get("status")
        if status == TaskStatus.NEEDS_CLARIFICATION.value:
            questions = state.get("intent", {}).get("clarification_questions", [])
            answer = "需要补充信息：" + "；".join(questions)
            final_status = TaskStatus.NEEDS_CLARIFICATION
        elif status == TaskStatus.FAILED.value:
            answer = "任务未完整完成。" + "；".join(item["message"] for item in state.get("errors", []))
            final_status = TaskStatus.FAILED
        else:
            report_path = ""
            issue_id = ""
            for item in state.get("tool_results", []):
                data = item["result"].get("data", {})
                report_path = data.get("report_path", report_path)
                issue_id = data.get("issue_id", issue_id)
            answer = (
                f"调查完成：共收集 {len(state.get('evidence', []))} 条可追溯证据。"
                f"复盘报告：{report_path or '未生成'}；整改 Issue：{issue_id or '未创建'}。"
                "主要假设为异常路径未释放 Redis 连接导致高峰期连接池耗尽；"
                "第二次网络 reset 仍标记为未验证项。"
            )
            final_status = TaskStatus.COMPLETED
        TASKS.labels(status=final_status.value).inc()
        return self._save(
            state,
            {"final_answer": answer, "status": final_status.value},
            node="final_response",
            event_type="task_finished",
            message=answer,
        )

    @staticmethod
    def _route_after_intent(state: AgentState) -> Literal["plan", "final"]:
        return "final" if state.get("status") == TaskStatus.NEEDS_CLARIFICATION.value else "plan"

    @staticmethod
    def _route_after_planning(state: AgentState) -> Literal["select", "final"]:
        return "final" if state.get("status") == TaskStatus.NEEDS_CLARIFICATION.value else "select"

    @staticmethod
    def _route_after_tool(state: AgentState) -> Literal["reflect", "pause"]:
        return "pause" if state.get("status") == TaskStatus.WAITING_APPROVAL.value else "reflect"

    @staticmethod
    def _route_after_reflection(state: AgentState) -> Literal["continue", "final"]:
        if state.get("status") == TaskStatus.FAILED.value:
            return "final"
        plan = TaskPlan.model_validate(state["plan"])
        return "continue" if any(step.status == StepStatus.PENDING for step in plan.steps) else "final"

    def create_and_run(self, request: CreateTaskRequest) -> TaskView:
        task_id = f"task_{uuid4().hex[:12]}"
        state: AgentState = {
            "task_id": task_id,
            "tenant_id": request.tenant_id,
            "user_id": request.user_id,
            "user_roles": request.user_roles,
            "request": request.request,
            "request_context": {"service": request.service, "days": request.days},
            "status": TaskStatus.CREATED.value,
            "intent": {},
            "plan": {},
            "current_step_index": 0,
            "selected_skill": None,
            "evidence": [],
            "tool_results": [],
            "pending_approval": None,
            "errors": [],
            "replan_count": 0,
            "final_answer": None,
            "created_at": utc_now(),
            "updated_at": utc_now(),
        }
        self.store.create_task(state)
        self.store.add_event(Event(task_id=task_id, event_type="task_created", message="任务已创建"))
        final_state = self.graph.invoke(state, {"recursion_limit": 50})
        return self.to_view(final_state)

    def approve_and_resume(
        self,
        task_id: str,
        approval_request: ApprovalRequest,
        *,
        tenant_id: str = "demo-tenant",
        decided_by: str = "demo-user",
    ) -> TaskView:
        state = self.store.get_state(task_id, tenant_id)
        if not state:
            raise KeyError(task_id)
        approval = deepcopy(state.get("pending_approval"))
        if not approval or approval.get("status") != "pending":
            raise ValueError("task has no pending approval")
        approval["decided_at"] = utc_now()
        approval["decided_by"] = decided_by
        approval["reason"] = approval_request.reason

        plan = TaskPlan.model_validate(state["plan"])
        step = next(item for item in plan.steps if item.step_id == approval["step_id"])
        if approval_request.decision == ApprovalDecision.REJECT:
            approval["status"] = "rejected"
            step.status = StepStatus.SKIPPED
            step.result_summary = "用户拒绝写操作"
            state.update(
                {
                    "pending_approval": approval,
                    "plan": plan.model_dump(mode="json"),
                    "status": TaskStatus.REJECTED.value,
                    "final_answer": "调查与报告已完成，但用户拒绝创建整改 Issue；未产生外部写操作。",
                }
            )
            self.store.save_state(state)
            self.store.add_event(
                Event(task_id=task_id, event_type="approval_rejected", node="approval", message=state["final_answer"])
            )
            return self.to_view(state)

        approval["status"] = "approved"
        step.status = StepStatus.PENDING
        state.update(
            {
                "pending_approval": approval,
                "plan": plan.model_dump(mode="json"),
                "status": TaskStatus.RUNNING.value,
            }
        )
        self.store.save_state(state)
        self.store.add_event(
            Event(task_id=task_id, event_type="approval_approved", node="approval", message="写操作已批准")
        )
        final_state = self.graph.invoke(state, {"recursion_limit": 50})
        return self.to_view(final_state)

    def resume_task(self, task_id: str, tenant_id: str = "demo-tenant") -> TaskView:
        """Resume a persisted running task after a worker/process interruption."""
        state = self.store.get_state(task_id, tenant_id)
        if not state:
            raise KeyError(task_id)
        if state.get("status") != TaskStatus.RUNNING.value:
            raise ValueError(f"task cannot be resumed from status {state.get('status')}")
        self.store.add_event(
            Event(task_id=task_id, event_type="task_resumed", node="recovery", message="任务从持久化状态恢复")
        )
        final_state = self.graph.invoke(state, {"recursion_limit": 50})
        return self.to_view(final_state)

    def get_task(self, task_id: str, tenant_id: str = "demo-tenant") -> TaskView | None:
        state = self.store.get_state(task_id, tenant_id)
        return self.to_view(state) if state else None

    def list_tasks(self, tenant_id: str = "demo-tenant") -> list[TaskView]:
        return [self.to_view(state) for state in self.store.list_states(tenant_id)]

    def llm_status(self) -> dict[str, Any]:
        return {
            "enabled": self.llm_client is not None,
            "mode": self.llm_mode,
            "provider": "deepseek" if self.llm_client else None,
            "model": self.settings.deepseek_model if self.llm_client else None,
            "thinking": self.settings.deepseek_thinking if self.llm_client else False,
            "fallback_enabled": self.settings.llm_fallback_enabled,
        }

    def tool_status(self) -> dict[str, Any]:
        return {
            "mode": self.settings.tool_mode,
            "transport": "mcp-client" if self.settings.tool_mode == "mcp" else "in-process-direct",
            "servers": sorted(self.mcp_servers),
            "timeout_seconds": self.settings.mcp_timeout_seconds,
            "max_retries": self.settings.mcp_max_retries,
            "knowledge": {
                "mode": self.settings.knowledge_mode,
                "remote_configured": bool(
                    self.settings.knowledge_api_base and self.settings.knowledge_api_token
                ),
                "fixture_fallback": self.settings.knowledge_fixture_fallback,
                "http_timeout_seconds": self.settings.knowledge_timeout_seconds,
                "mcp_timeout_seconds": (
                    self.settings.knowledge_timeout_seconds
                    * (self.settings.knowledge_max_retries + 1)
                    + 5
                ),
            },
        }

    def _planner_metadata(self) -> dict[str, Any]:
        consume = getattr(self.planner, "consume_metadata", None)
        return consume() if consume else {"mode": "deterministic"}

    def evaluate_task(
        self,
        task_id: str,
        tenant_id: str = "demo-tenant",
    ) -> EvaluationReport | None:
        state = self.store.get_state(task_id, tenant_id)
        if not state:
            return None
        return self.evaluator.evaluate(state, self.store.list_events(task_id))

    @staticmethod
    def to_view(state: AgentState) -> TaskView:
        return TaskView(
            task_id=state["task_id"],
            status=TaskStatus(state["status"]),
            request=state["request"],
            intent=state.get("intent", {}),
            plan=state.get("plan", {}),
            evidence=state.get("evidence", []),
            pending_approval=state.get("pending_approval"),
            final_answer=state.get("final_answer"),
            errors=state.get("errors", []),
            created_at=state["created_at"],
            updated_at=state["updated_at"],
        )
