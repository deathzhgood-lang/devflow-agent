from __future__ import annotations

from mcp.server import MCPServer

from devflow.models import PlanStep, TaskPlan, ToolResult
from devflow.tools import stable_hash
from devflow.store import SQLiteStore
from devflow.tools import LocalToolRegistry, ToolRouter
from mcp_servers.common import build_components


def create_server(
    store: SQLiteStore,
    registry: LocalToolRegistry,
    router: ToolRouter,
) -> MCPServer:
    server = MCPServer(
        "devflow-git",
        instructions=(
            "Git evidence server. Read operations are bounded to allowlisted fixtures. "
            "create_issue requires an approved task whose exact argument hash matches the stored approval."
        ),
    )

    @server.tool()
    def list_commits(repository: str, days: int = 30) -> ToolResult:
        """List bounded repository changes near an incident window; read-only."""
        return registry.get("list_commits").handler(
            {"repository": repository, "days": max(1, min(days, 90))},
            {"task_id": "mcp-read"},
        )

    @server.tool()
    def search_code(repository: str, query: str) -> dict:
        """Search the allowlisted demo code index without modifying a repository."""
        commits = registry._read_json("commits.json")
        query_lower = query.lower()
        matches = [
            item
            for item in commits
            if query_lower in (item["summary"] + " " + " ".join(item["files"])).lower()
        ]
        return {"repository": repository, "query": query, "matches": matches}

    @server.tool()
    def create_issue(
        task_id: str,
        repository: str,
        title: str,
        report_ref: str,
        tenant_id: str = "demo-tenant",
    ) -> ToolResult:
        """Create one remediation issue after verifying a stored, exact user approval."""
        state = store.get_state(task_id, tenant_id)
        if not state:
            return ToolResult(ok=False, error_code="task_not_found", summary="任务不存在")
        approval = state.get("pending_approval") or {}
        arguments = {"repository": repository, "title": title, "report_ref": report_ref}
        if (
            approval.get("status") != "approved"
            or approval.get("tool_name") != "create_issue"
            or approval.get("arguments_hash") != stable_hash(arguments)
        ):
            return ToolResult(ok=False, error_code="approval_required", summary="缺少与参数匹配的人工审批")
        plan = TaskPlan.model_validate(state["plan"])
        step: PlanStep = next(item for item in plan.steps if item.step_id == approval["step_id"])
        return router.execute(state, step, arguments)

    return server


store, registry, router = build_components()
mcp = create_server(store, registry, router)


if __name__ == "__main__":
    mcp.run("stdio")
