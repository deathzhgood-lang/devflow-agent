from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field, model_validator


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class TaskStatus(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    NEEDS_CLARIFICATION = "needs_clarification"
    COMPLETED = "completed"
    FAILED = "failed"
    REJECTED = "rejected"


class StepStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"
    SKIPPED = "skipped"


class RiskLevel(StrEnum):
    READ = "read"
    LOW_WRITE = "low_write"
    HIGH_WRITE = "high_write"
    PROHIBITED = "prohibited"


class ApprovalDecision(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"


class CreateTaskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request: str = Field(min_length=3, max_length=4000)
    service: str | None = Field(default=None, pattern=r"^[a-z0-9-]{2,64}$")
    days: int | None = Field(default=None, ge=1, le=90)
    user_id: str = Field(default="demo-user", min_length=1, max_length=64)
    tenant_id: str = Field(default="demo-tenant", min_length=1, max_length=64)
    user_roles: list[str] = Field(default_factory=lambda: ["developer", "git-writer"])


class ApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: ApprovalDecision
    reason: str | None = Field(default=None, max_length=500)


class IntentResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: Literal["incident_investigation"] = "incident_investigation"
    service: str | None
    days: int = Field(ge=1, le=90)
    deliverable: Literal["postmortem"] = "postmortem"
    create_issue: bool = True
    confidence: float = Field(ge=0, le=1)
    clarification_questions: list[str] = Field(default_factory=list, max_length=3)


class PlanStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_id: str = Field(pattern=r"^S[1-8]$")
    title: str = Field(min_length=1, max_length=120)
    skill_id: str = Field(min_length=1, max_length=100)
    tool_name: str = Field(min_length=1, max_length=100)
    depends_on: list[str] = Field(default_factory=list)
    success_criteria: list[str] = Field(min_length=1)
    risk_level: RiskLevel
    requires_approval: bool = False
    status: StepStatus = StepStatus.PENDING
    retry_count: int = Field(default=0, ge=0, le=2)
    result_summary: str | None = None


class TaskPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ready", "needs_clarification", "rejected"]
    goal: str = Field(min_length=1, max_length=300)
    clarification_questions: list[str] = Field(default_factory=list, max_length=3)
    steps: list[PlanStep] = Field(default_factory=list, max_length=8)
    completion_criteria: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_graph(self) -> "TaskPlan":
        ids = [step.step_id for step in self.steps]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate step_id")
        known: set[str] = set()
        for step in self.steps:
            unknown = set(step.depends_on) - known
            if unknown:
                raise ValueError(f"{step.step_id} has unknown or forward dependencies: {unknown}")
            known.add(step.step_id)
            if step.risk_level == RiskLevel.HIGH_WRITE and not step.requires_approval:
                raise ValueError(f"{step.step_id} high_write requires approval")
            if step.risk_level == RiskLevel.PROHIBITED:
                raise ValueError(f"{step.step_id} uses a prohibited risk level")
        return self


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    source_type: Literal["metric", "log", "trace", "git", "knowledge", "file", "analysis"]
    source_uri: str
    collected_at: str = Field(default_factory=utc_now)
    content_hash: str
    summary: str
    raw_ref: str


class ToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    summary: str
    data: dict[str, Any] = Field(default_factory=dict)
    evidence: list[Evidence] = Field(default_factory=list)
    external_resource_id: str | None = None
    retryable: bool = False
    error_code: str | None = None


class ApprovalState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approval_id: str
    step_id: str
    tool_name: str
    arguments: dict[str, Any]
    arguments_hash: str
    status: Literal["pending", "approved", "rejected"] = "pending"
    requested_at: str = Field(default_factory=utc_now)
    decided_at: str | None = None
    decided_by: str | None = None
    reason: str | None = None


class AgentState(TypedDict, total=False):
    task_id: str
    tenant_id: str
    user_id: str
    user_roles: list[str]
    request: str
    request_context: dict[str, Any]
    status: str
    intent: dict[str, Any]
    plan: dict[str, Any]
    current_step_index: int
    selected_skill: str | None
    evidence: list[dict[str, Any]]
    tool_results: list[dict[str, Any]]
    pending_approval: dict[str, Any] | None
    errors: list[dict[str, Any]]
    replan_count: int
    final_answer: str | None
    created_at: str
    updated_at: str


class Event(BaseModel):
    event_id: int | None = None
    task_id: str
    event_type: str
    node: str | None = None
    message: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utc_now)


class TaskView(BaseModel):
    task_id: str
    status: TaskStatus
    request: str
    intent: dict[str, Any] = Field(default_factory=dict)
    plan: dict[str, Any] = Field(default_factory=dict)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    pending_approval: dict[str, Any] | None = None
    final_answer: str | None = None
    errors: list[dict[str, Any]] = Field(default_factory=list)
    created_at: str
    updated_at: str

