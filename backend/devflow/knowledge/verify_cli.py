from __future__ import annotations

import argparse
import json
import os
from uuid import uuid4

from devflow.config import settings
from devflow.knowledge.client import KnowledgeClient, KnowledgeError
from devflow.knowledge.models import KnowledgeFilters, KnowledgeQueryRequest


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the remote Knowledge Copilot contract")
    parser.add_argument("--query", default="登录接口持续返回 401，应该如何排查？")
    parser.add_argument("--tenant", default=os.getenv("KNOWLEDGE_TENANT_ID", "local-demo"))
    parser.add_argument("--user", default="devflow-integration")
    parser.add_argument("--groups", default=os.getenv("KNOWLEDGE_DEFAULT_GROUPS", "engineering"))
    parser.add_argument("--service", default="")
    parser.add_argument("--document-types", default="")
    parser.add_argument("--top-k", type=int, default=3)
    args = parser.parse_args()

    client = KnowledgeClient(
        base_url=settings.knowledge_api_base,
        token=settings.knowledge_api_token,
        timeout_seconds=settings.knowledge_timeout_seconds,
        max_retries=settings.knowledge_max_retries,
    )
    request_id = f"devflow-smoke-{uuid4().hex}"
    request = KnowledgeQueryRequest(
        query=args.query,
        tenant_id=args.tenant,
        user_id=args.user,
        groups=[item.strip() for item in args.groups.split(",") if item.strip()],
        filters=KnowledgeFilters(
            service=args.service or None,
            document_types=[
                item.strip() for item in args.document_types.split(",") if item.strip()
            ],
            tags=[],
        ),
        top_k=args.top_k,
        request_id=request_id,
    )
    try:
        health = client.health()
        response = client.query(request)
    except KnowledgeError as exc:
        print(json.dumps({"ok": False, "error_code": exc.code, "retryable": exc.retryable}))
        return 1

    output = {
        "ok": health.status == "ok",
        "health": health.status,
        "retrieval_ready": health.retrieval_ready,
        "tenant_matched": response.tenant_id == request.tenant_id,
        "request_id_matched": response.request_id == request_id,
        "query_id": response.query_id,
        "retrieval_version": response.retrieval_version,
        "evidence_count": len(response.evidence),
        "citations": [
            {
                "document_id": item.document_id,
                "chunk_id": item.chunk_id,
                "source_uri": item.source_uri,
                "score": item.score,
                "untrusted": item.metadata.untrusted_retrieved_content,
            }
            for item in response.evidence
        ],
        "latency_ms": response.latency_ms,
        "warnings": response.warnings,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0 if output["ok"] and output["tenant_matched"] and output["request_id_matched"] else 1
