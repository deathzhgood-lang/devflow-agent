import asyncio

from devflow.mcp_client import MCPToolClient
from mcp_servers.git_server import mcp as git_mcp
from mcp_servers.knowledge_server import mcp as knowledge_mcp
from mcp_servers.observability_server import mcp as observability_mcp
from mcp_servers.workspace_server import mcp as workspace_mcp


def test_mcp_servers_discover_and_call_tools() -> None:
    async def scenario() -> None:
        client = MCPToolClient(
            {
                "observability": observability_mcp,
                "git": git_mcp,
                "knowledge": knowledge_mcp,
                "workspace": workspace_mcp,
            }
        )
        observability_tools = await client.list_tools("observability")
        git_tools = await client.list_tools("git")
        workspace_tools = await client.list_tools("workspace")
        knowledge_tools = await client.list_tools("knowledge")
        assert {"query_metrics", "search_logs", "get_trace"}.issubset(observability_tools)
        assert {"list_commits", "search_code", "create_issue"}.issubset(git_tools)
        assert {"search_knowledge"}.issubset(knowledge_tools)
        assert {"read_report", "correlate_evidence", "write_report", "list_reports"}.issubset(
            workspace_tools
        )

        result = await client.call_tool(
            "observability",
            "query_metrics",
            {"service": "payment", "days": 30},
        )
        assert result.is_error is False
        assert result.structured_content["ok"] is True

        denied = await client.call_tool(
            "git",
            "create_issue",
            {
                "task_id": "missing",
                "repository": "payment",
                "title": "should not exist",
                "report_ref": "none",
            },
        )
        assert denied.structured_content["ok"] is False

    asyncio.run(scenario())
