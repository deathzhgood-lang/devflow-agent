from __future__ import annotations

from devflow.knowledge.models import KnowledgeQueryResponse
from devflow.models import Evidence, utc_now
from devflow.tools import stable_hash


def response_to_evidence(response: KnowledgeQueryResponse) -> list[Evidence]:
    """Convert only server-validated citations; retrieved text remains untrusted data."""
    return [
        Evidence(
            evidence_id=f"ev_knowledge_{stable_hash({'query': response.query_id, 'ref': item.source_uri})[:12]}",
            source_type="knowledge",
            source_uri=item.source_uri,
            collected_at=utc_now(),
            content_hash=stable_hash(
                {
                    "document_id": item.document_id,
                    "chunk_id": item.chunk_id,
                    "source_uri": item.source_uri,
                    "quote": item.quote,
                }
            ),
            summary=f"{item.title}：{item.quote}",
            raw_ref=f"{item.document_id}#{item.chunk_id}",
        )
        for item in response.evidence
    ]
