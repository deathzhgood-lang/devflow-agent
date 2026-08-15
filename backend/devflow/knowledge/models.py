from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class KnowledgeFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    service: str | None = Field(default=None, min_length=2, max_length=64)
    document_types: list[str] = Field(default_factory=lambda: ["incident", "runbook"], max_length=10)
    tags: list[str] = Field(default_factory=list, max_length=20)


class KnowledgeQueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=3, max_length=1000)
    tenant_id: str = Field(min_length=1, max_length=64)
    user_id: str = Field(min_length=1, max_length=64)
    groups: list[str] = Field(default_factory=list, max_length=50)
    filters: KnowledgeFilters = Field(default_factory=KnowledgeFilters)
    top_k: int = Field(default=5, ge=1, le=20)
    request_id: str = Field(min_length=1, max_length=128)


class KnowledgeEvidenceMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    service: str | None = None
    heading: str | None = None
    page_start: int | None = None
    page_end: int | None = None
    updated_at: str | None = None
    tags: list[str] = Field(default_factory=list)
    untrusted_retrieved_content: Literal[True]


class KnowledgeLatency(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_ms: int = Field(ge=0)
    retrieval_ms: int = Field(ge=0)
    reranker_ms: int | None = Field(default=None, ge=0)


class KnowledgeCitation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str = Field(min_length=1, max_length=256)
    chunk_id: str = Field(min_length=1, max_length=256)
    title: str = Field(min_length=1, max_length=500)
    quote: str = Field(min_length=1, max_length=4000)
    source_uri: str = Field(min_length=3, max_length=2000)
    score: float = Field(ge=0, le=1)
    document_type: str = Field(min_length=1, max_length=64)
    metadata: KnowledgeEvidenceMetadata

    @field_validator("source_uri")
    @classmethod
    def source_must_be_stable_uri(cls, value: str) -> str:
        if not value.startswith(("knowledge://", "https://", "http://")):
            raise ValueError("source_uri must use knowledge, http or https scheme")
        return value


class KnowledgeQueryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query_id: str = Field(min_length=1, max_length=256)
    answer: str = Field(default="", max_length=20000)
    evidence: list[KnowledgeCitation] = Field(default_factory=list, max_length=20)
    retrieval_version: str = Field(min_length=1, max_length=256)
    tenant_id: str = Field(min_length=1, max_length=64)
    request_id: str = Field(min_length=1, max_length=128)
    latency_ms: float | None = Field(default=None, ge=0)
    latency: KnowledgeLatency | None = None
    warnings: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def citations_are_unique(self) -> "KnowledgeQueryResponse":
        refs = [(item.document_id, item.chunk_id, item.source_uri) for item in self.evidence]
        if len(refs) != len(set(refs)):
            raise ValueError("duplicate knowledge citations")
        return self


class KnowledgeHealth(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: str
    service: str | None = None
    version: str | None = None
    retrieval_ready: bool | None = None
    retrieval_version: str | None = None
