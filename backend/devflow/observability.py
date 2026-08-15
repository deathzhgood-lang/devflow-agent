from __future__ import annotations

from opentelemetry import trace
from prometheus_client import CollectorRegistry, Counter, Histogram


REGISTRY = CollectorRegistry()
HTTP_REQUESTS = Counter(
    "devflow_http_requests_total",
    "HTTP requests handled by the API",
    ("method", "route", "status"),
    registry=REGISTRY,
)
TASKS = Counter(
    "devflow_tasks_total",
    "Agent tasks by terminal status",
    ("status",),
    registry=REGISTRY,
)
TOOL_CALLS = Counter(
    "devflow_tool_calls_total",
    "Tool calls by bounded tool name and status",
    ("tool", "status"),
    registry=REGISTRY,
)
TOOL_DURATION = Histogram(
    "devflow_tool_duration_seconds",
    "Tool execution duration",
    ("tool",),
    registry=REGISTRY,
)
MCP_CALLS = Counter(
    "devflow_mcp_calls_total",
    "MCP calls by bounded server, tool and transport status",
    ("server", "tool", "status"),
    registry=REGISTRY,
)
MCP_DURATION = Histogram(
    "devflow_mcp_duration_seconds",
    "MCP transport duration",
    ("server", "tool"),
    registry=REGISTRY,
)
LLM_CALLS = Counter(
    "devflow_llm_calls_total",
    "LLM calls by provider, model, purpose and status",
    ("provider", "model", "purpose", "status"),
    registry=REGISTRY,
)
LLM_DURATION = Histogram(
    "devflow_llm_duration_seconds",
    "LLM request duration by provider, model and purpose",
    ("provider", "model", "purpose"),
    registry=REGISTRY,
)
LLM_TOKENS = Counter(
    "devflow_llm_tokens_total",
    "LLM tokens by provider, model and token type",
    ("provider", "model", "token_type"),
    registry=REGISTRY,
)

tracer = trace.get_tracer("devflow-agent", "0.1.0")
