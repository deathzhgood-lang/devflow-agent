from __future__ import annotations

import asyncio
from typing import Any

from mcp import Client
from mcp.server import MCPServer

from devflow.models import PlanStep, RiskLevel, ToolResult
from devflow.config import Settings
from devflow.knowledge.service import KnowledgeService
from devflow.observability import MCP_CALLS, MCP_DURATION
from devflow.store import SQLiteStore
from devflow.tools import LocalToolRegistry, ToolRouter, stable_hash


class MCPCallError(RuntimeError):
    """Base error for a failed MCP transport call."""


class MCPTimeoutError(MCPCallError):
    """The MCP transport did not return before the configured deadline."""


class MCPResponseLostError(MCPCallError):
    """The server may have completed the operation, but the response was lost."""


def build_inprocess_servers(
    store: SQLiteStore,
    registry: LocalToolRegistry,
    router: ToolRouter,
    settings: Settings,
) -> dict[str, MCPServer]:
    """Bind MCP servers to the exact store and tool registry used by one runtime."""
    from mcp_servers.git_server import create_server as create_git_server
    from mcp_servers.knowledge_server import create_server as create_knowledge_server
    from mcp_servers.observability_server import create_server as create_observability_server
    from mcp_servers.workspace_server import create_server as create_workspace_server

    return {
        "observability": create_observability_server(registry),
        "knowledge": create_knowledge_server(KnowledgeService(settings, registry)),
        "git": create_git_server(store, registry, router),
        "workspace": create_workspace_server(store, router),
    }


class MCPToolClient:
    """MCP Client transport used by the Agent runtime and contract tests."""

    def __init__(self, servers: dict[str, MCPServer]):
        self.servers = servers

    async def list_tools(self, server_name: str) -> list[str]:
        async with Client(self.servers[server_name]) as client:
            result = await client.list_tools()
            return [tool.name for tool in result.tools]

    async def call_tool(self, server_name: str, tool_name: str, arguments: dict[str, Any]) -> Any:
        async with Client(self.servers[server_name]) as client:
            return await client.call_tool(tool_name, arguments)

    def call_tool_sync(
        self,
        server_name: str,
        tool_name: str,
        arguments: dict[str, Any],
        timeout_seconds: float,
    ) -> ToolResult:
        async def invoke() -> Any:
            return await asyncio.wait_for(
                self.call_tool(server_name, tool_name, arguments),
                timeout=timeout_seconds,
            )

        try:
            response = asyncio.run(invoke())
        except TimeoutError as exc:
            raise MCPTimeoutError(f"MCP call timed out: {server_name}.{tool_name}") from exc
        except MCPCallError:
            raise
        except Exception as exc:
            raise MCPCallError(f"MCP call failed: {server_name}.{tool_name}: {exc}") from exc

        payload = getattr(response, "structured_content", None)
        if not isinstance(payload, dict):
            raise MCPResponseLostError(f"MCP response has no structured content: {server_name}.{tool_name}")
        return ToolResult.model_validate(payload)


class MCPToolGateway:
    """Policy-enforcing runtime gateway; all actual tool work crosses MCP Client."""

    TOOL_SERVERS = {
        "query_metrics": "observability",
        "search_logs": "observability",
        "search_knowledge": "knowledge",
        "list_commits": "git",
        "correlate_evidence": "workspace",
        "write_report": "workspace",
        "create_issue": "git",
    }

    def __init__(
        self,
        local_router: ToolRouter,
        client: MCPToolClient,
        *,
        timeout_seconds: float = 10.0,
        max_retries: int = 1,
        tool_timeouts: dict[str, float] | None = None,
    ):
        self.local_router = local_router
        self.registry = local_router.registry
        self.store = local_router.store
        self.client = client
        self.timeout_seconds = timeout_seconds
        self.max_retries = max(0, max_retries)
        self.tool_timeouts = tool_timeouts or {}

    def build_arguments(self, step: PlanStep, state: dict[str, Any]) -> dict[str, Any]:
        return self.local_router.build_arguments(step, state)

    def make_approval(self, state: dict[str, Any], step: PlanStep, arguments: dict[str, Any]):
        return self.local_router.make_approval(state, step, arguments)

    def _policy_error(
        self,
        state: dict[str, Any],
        step: PlanStep,
        arguments: dict[str, Any],
    ) -> ToolResult | None:
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
        return None

    @staticmethod
    def _mcp_arguments(state: dict[str, Any], step: PlanStep, arguments: dict[str, Any]) -> dict[str, Any]:
        if step.tool_name == "search_knowledge":
            return {
                **arguments,
                "task_id": state["task_id"],
                "tenant_id": state["tenant_id"],
                "user_id": state["user_id"],
                "groups": state.get("user_roles", []),
                "service": state.get("intent", {}).get("service"),
                "request_id": f"{state['task_id']}:{step.step_id}",
            }
        if step.tool_name in {"correlate_evidence", "write_report"}:
            return {"task_id": state["task_id"], "tenant_id": state["tenant_id"]}
        if step.tool_name == "create_issue":
            return {
                "task_id": state["task_id"],
                "tenant_id": state["tenant_id"],
                **arguments,
            }
        return arguments

    def execute(self, state: dict[str, Any], step: PlanStep, arguments: dict[str, Any]) -> ToolResult:
        policy_error = self._policy_error(state, step, arguments)
        if policy_error:
            return policy_error
        server_name = self.TOOL_SERVERS.get(step.tool_name)
        if not server_name:
            return ToolResult(ok=False, summary="工具未映射到 MCP Server", error_code="mcp_tool_unmapped")

        mcp_arguments = self._mcp_arguments(state, step, arguments)
        last_error: MCPCallError | None = None
        for attempt in range(1, self.max_retries + 2):
            from time import perf_counter

            started = perf_counter()
            try:
                result = self.client.call_tool_sync(
                    server_name,
                    step.tool_name,
                    mcp_arguments,
                    self.tool_timeouts.get(step.tool_name, self.timeout_seconds),
                )
                MCP_CALLS.labels(server=server_name, tool=step.tool_name, status="ok").inc()
                result.data = {
                    **result.data,
                    "_mcp": {"server": server_name, "tool": step.tool_name, "attempt": attempt},
                }
                return result
            except MCPCallError as exc:
                last_error = exc
                MCP_CALLS.labels(server=server_name, tool=step.tool_name, status="error").inc()
            finally:
                MCP_DURATION.labels(server=server_name, tool=step.tool_name).observe(
                    perf_counter() - started
                )

        code = "mcp_timeout" if isinstance(last_error, MCPTimeoutError) else "mcp_transport_error"
        return ToolResult(
            ok=False,
            retryable=True,
            error_code=code,
            summary=f"MCP 工具调用失败，已重试 {self.max_retries} 次：{last_error}",
            data={"_mcp": {"server": server_name, "tool": step.tool_name}},
        )
