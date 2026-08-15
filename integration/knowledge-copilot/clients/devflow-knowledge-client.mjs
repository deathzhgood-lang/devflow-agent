export class KnowledgeServiceError extends Error {
  constructor(message, { status = 0, code = "network_error", retryable = false, requestId = null } = {}) {
    super(message);
    this.name = "KnowledgeServiceError";
    this.status = status;
    this.code = code;
    this.retryable = retryable;
    this.requestId = requestId;
  }
}

function sleep(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function cleanList(values, field) {
  const cleaned = [...new Set((values || []).map((value) => String(value).trim()).filter(Boolean))];
  if (cleaned.length !== (values || []).length) {
    throw new TypeError(`${field} must contain unique, non-empty values`);
  }
  return cleaned;
}

function validateEvidence(evidence) {
  if (!Array.isArray(evidence)) throw new TypeError("Knowledge response evidence must be an array");
  for (const item of evidence) {
    if (!/^knowledge:\/\/[^#]+#chunk=.+$/.test(item?.source_uri || "")) {
      throw new TypeError("Knowledge response contains an invalid source_uri");
    }
    if (item?.metadata?.untrusted_retrieved_content !== true) {
      throw new TypeError("Knowledge response is missing the untrusted-content marker");
    }
  }
}

export class DevFlowKnowledgeClient {
  constructor({ origin, token, tenantId, timeoutMs = 35_000, maxRetries = 2 }) {
    if (!origin || !/^https?:\/\//.test(origin)) throw new TypeError("A valid KNOWLEDGE_API_ORIGIN is required");
    if (!token) throw new TypeError("KNOWLEDGE_SERVICE_TOKEN is required");
    if (!tenantId) throw new TypeError("KNOWLEDGE_TENANT_ID is required");
    this.origin = origin.replace(/\/$/, "");
    this.token = token;
    this.tenantId = tenantId;
    this.timeoutMs = Number(timeoutMs) || 35_000;
    this.maxRetries = Math.max(0, Number(maxRetries) || 0);
  }

  async health() {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), Math.min(this.timeoutMs, 10_000));
    try {
      const response = await fetch(`${this.origin}/health`, { signal: controller.signal });
      if (!response.ok) throw new KnowledgeServiceError("Knowledge health check failed", { status: response.status });
      return await response.json();
    } finally {
      clearTimeout(timer);
    }
  }

  async query({ query, userId, groups = [], filters = {}, topK = 5, requestId = crypto.randomUUID() }) {
    if (!query || String(query).trim().length < 2) throw new TypeError("query must contain at least 2 characters");
    if (!userId) throw new TypeError("userId must come from the authenticated DevFlow user");

    const payload = {
      query: String(query).trim(),
      tenant_id: this.tenantId,
      user_id: String(userId),
      groups: cleanList(groups, "groups"),
      filters: {
        service: filters.service || null,
        document_types: cleanList(filters.documentTypes || [], "documentTypes"),
        tags: cleanList(filters.tags || [], "tags"),
      },
      top_k: Number(topK),
      request_id: String(requestId),
    };

    for (let attempt = 0; attempt <= this.maxRetries; attempt += 1) {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), this.timeoutMs);
      try {
        const response = await fetch(`${this.origin}/api/v1/retrieval/query`, {
          method: "POST",
          headers: {
            authorization: `Bearer ${this.token}`,
            "content-type": "application/json",
            "x-request-id": payload.request_id,
          },
          body: JSON.stringify(payload),
          signal: controller.signal,
        });
        const body = await response.json().catch(() => ({}));
        if (!response.ok) {
          const detail = body?.error || {};
          const error = new KnowledgeServiceError(detail.message || `Knowledge request failed (${response.status})`, {
            status: response.status,
            code: detail.code || "http_error",
            retryable: detail.retryable === true,
            requestId: detail.request_id || payload.request_id,
          });
          if (error.retryable && attempt < this.maxRetries) {
            await sleep(250 * 2 ** attempt + Math.floor(Math.random() * 100));
            continue;
          }
          throw error;
        }
        if (body.request_id !== payload.request_id) throw new TypeError("Knowledge response request_id mismatch");
        if (body.tenant_id !== this.tenantId) throw new TypeError("Knowledge response tenant_id mismatch");
        validateEvidence(body.evidence);
        return body;
      } catch (error) {
        if (error?.name === "AbortError") {
          if (attempt < this.maxRetries) {
            await sleep(250 * 2 ** attempt + Math.floor(Math.random() * 100));
            continue;
          }
          throw new KnowledgeServiceError("Knowledge request timed out", {
            status: 504,
            code: "client_timeout",
            retryable: true,
            requestId: payload.request_id,
          });
        }
        throw error;
      } finally {
        clearTimeout(timer);
      }
    }
    throw new KnowledgeServiceError("Knowledge request failed", { requestId: payload.request_id });
  }
}

