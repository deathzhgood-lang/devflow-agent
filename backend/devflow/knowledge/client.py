from __future__ import annotations

import httpx
from pydantic import ValidationError

from devflow.knowledge.models import KnowledgeHealth, KnowledgeQueryRequest, KnowledgeQueryResponse


class KnowledgeError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class KnowledgeConfigurationError(KnowledgeError):
    pass


class KnowledgeClient:
    """Strict remote adapter for Enterprise Knowledge Copilot."""

    RETRYABLE_STATUSES = {429, 502, 503, 504}

    def __init__(
        self,
        *,
        base_url: str | None,
        token: str | None,
        timeout_seconds: float = 5.0,
        max_retries: int = 1,
        transport: httpx.BaseTransport | None = None,
    ):
        self.base_url = base_url.rstrip("/") if base_url else None
        self.token = token
        self.timeout_seconds = timeout_seconds
        self.max_retries = max(0, max_retries)
        self.transport = transport

    def _configuration(self) -> tuple[str, str]:
        if not self.base_url:
            raise KnowledgeConfigurationError(
                "knowledge_not_configured",
                "KNOWLEDGE_API_BASE is not configured",
            )
        if not self.token:
            raise KnowledgeConfigurationError(
                "knowledge_not_configured",
                "KNOWLEDGE_API_TOKEN is not configured",
            )
        return self.base_url, self.token

    def health(self) -> KnowledgeHealth:
        base_url, _ = self._configuration()
        try:
            with httpx.Client(
                timeout=self.timeout_seconds,
                transport=self.transport,
                trust_env=False,
            ) as client:
                response = client.get(f"{base_url}/health")
                response.raise_for_status()
                return KnowledgeHealth.model_validate(response.json())
        except (httpx.HTTPError, ValidationError, ValueError) as exc:
            raise KnowledgeError("knowledge_health_failed", "Knowledge health check failed") from exc

    def query(self, request: KnowledgeQueryRequest) -> KnowledgeQueryResponse:
        base_url, token = self._configuration()
        headers = {
            "Authorization": f"Bearer {token}",
            "X-Request-ID": request.request_id,
            "Content-Type": "application/json",
        }
        last_error: KnowledgeError | None = None
        for attempt in range(self.max_retries + 1):
            try:
                with httpx.Client(
                    timeout=self.timeout_seconds,
                    transport=self.transport,
                    trust_env=False,
                ) as client:
                    response = client.post(
                        f"{base_url}/api/v1/retrieval/query",
                        headers=headers,
                        json=request.model_dump(mode="json"),
                    )
                if response.is_error:
                    try:
                        detail = response.json().get("error", {})
                    except ValueError:
                        detail = {}
                    default_codes = {
                        401: "unauthorized",
                        403: "forbidden",
                        422: "invalid_request",
                        429: "rate_limited",
                        503: "retrieval_unavailable",
                        504: "retrieval_timeout",
                    }
                    raise KnowledgeError(
                        str(detail.get("code") or default_codes.get(response.status_code, "retrieval_failed")),
                        str(detail.get("message") or f"Knowledge service returned HTTP {response.status_code}"),
                        retryable=(
                            response.status_code in self.RETRYABLE_STATUSES
                            and detail.get("retryable", True) is True
                        ),
                    )
                result = KnowledgeQueryResponse.model_validate(response.json())
                if result.tenant_id != request.tenant_id:
                    raise KnowledgeError(
                        "tenant_mismatch",
                        "Knowledge response tenant does not match the request",
                    )
                if result.request_id != request.request_id:
                    raise KnowledgeError(
                        "request_mismatch",
                        "Knowledge response request ID does not match the request",
                    )
                return result
            except httpx.TimeoutException as exc:
                last_error = KnowledgeError(
                    "retrieval_timeout",
                    "Knowledge retrieval timed out",
                    retryable=True,
                )
                last_error.__cause__ = exc
            except httpx.RequestError as exc:
                last_error = KnowledgeError(
                    "retrieval_unavailable",
                    "Knowledge service is unreachable",
                    retryable=True,
                )
                last_error.__cause__ = exc
            except (ValidationError, ValueError) as exc:
                raise KnowledgeError(
                    "invalid_citation_contract",
                    "Knowledge service returned an invalid response contract",
                ) from exc
            except KnowledgeError as exc:
                last_error = exc

            if last_error and (not last_error.retryable or attempt >= self.max_retries):
                raise last_error
        raise last_error or KnowledgeError("retrieval_failed", "Knowledge retrieval failed")
