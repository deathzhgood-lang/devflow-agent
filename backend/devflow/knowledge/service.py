from __future__ import annotations

from typing import Any

from devflow.config import Settings
from devflow.knowledge.client import KnowledgeClient, KnowledgeError
from devflow.knowledge.evidence_adapter import response_to_evidence
from devflow.knowledge.models import KnowledgeFilters, KnowledgeQueryRequest
from devflow.models import ToolResult
from devflow.tools import LocalToolRegistry


class KnowledgeService:
    """Select remote RAG or fixtures without weakening authorization failures."""

    def __init__(
        self,
        settings: Settings,
        registry: LocalToolRegistry,
        client: KnowledgeClient | None = None,
    ):
        self.settings = settings
        self.registry = registry
        self.client = client or KnowledgeClient(
            base_url=settings.knowledge_api_base,
            token=settings.knowledge_api_token,
            timeout_seconds=settings.knowledge_timeout_seconds,
            max_retries=settings.knowledge_max_retries,
        )

    def search(self, args: dict[str, Any]) -> ToolResult:
        if self.settings.knowledge_mode == "fixture":
            result = self._fixture(args)
            result.data = {**result.data, "provider": "fixture"}
            return result
        if self.settings.knowledge_mode != "remote":
            return ToolResult(
                ok=False,
                summary=f"未知知识服务模式：{self.settings.knowledge_mode}",
                error_code="knowledge_mode_invalid",
            )

        request = KnowledgeQueryRequest(
            query=args["query"],
            tenant_id=args["tenant_id"],
            user_id=args["user_id"],
            groups=args.get("groups", []),
            filters=KnowledgeFilters(
                service=args.get("service"),
                document_types=args.get("document_types", ["incident", "runbook"]),
                tags=args.get("tags", []),
            ),
            top_k=args.get("top_k", 5),
            request_id=args["request_id"],
        )
        try:
            response = self.client.query(request)
            evidence = response_to_evidence(response)
            warnings = list(response.warnings)
            answer = response.answer if evidence else ""
            if response.answer and not evidence:
                warnings.append("未返回可验证引用，远程 answer 已丢弃")
            summary = (
                f"远程知识库返回 {len(evidence)} 条可追溯引用"
                if evidence
                else "远程知识库未找到匹配引用"
            )
            return ToolResult(
                ok=True,
                summary=summary,
                data={
                    "provider": "remote",
                    "query_id": response.query_id,
                    "answer": answer,
                    "retrieval_version": response.retrieval_version,
                    "warnings": warnings,
                    "matches": [item.model_dump(mode="json") for item in response.evidence],
                },
                evidence=evidence,
            )
        except KnowledgeError as exc:
            # Demo fixtures may replace availability failures only. Authorization and
            # contract failures remain visible and never borrow local evidence.
            if exc.retryable and self.settings.knowledge_fixture_fallback:
                fallback = self._fixture(args)
                fallback.summary = f"远程知识服务不可用，已使用脱敏 Fixture：{fallback.summary}"
                fallback.data = {
                    **fallback.data,
                    "provider": "fixture_fallback",
                    "remote_error_code": exc.code,
                }
                return fallback
            return ToolResult(
                ok=True,
                summary=f"知识证据已安全跳过：{exc.code}",
                data={
                    "provider": "remote_degraded",
                    "degraded": True,
                    "remote_error_code": exc.code,
                    "warnings": ["知识服务未提供可验证证据，后续结论不得视为已获得历史知识支持"],
                },
                evidence=[],
            )

    def _fixture(self, args: dict[str, Any]) -> ToolResult:
        return self.registry.get("search_knowledge").handler(
            {"query": args["query"], "top_k": args.get("top_k", 5)},
            {"task_id": args.get("task_id", "mcp-read")},
        )
