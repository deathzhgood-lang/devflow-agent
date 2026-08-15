import { DevFlowKnowledgeClient } from "./devflow-knowledge-client.mjs";

const required = ["KNOWLEDGE_API_ORIGIN", "KNOWLEDGE_SERVICE_TOKEN", "KNOWLEDGE_TENANT_ID"];
const missing = required.filter((name) => !process.env[name]);
if (missing.length) {
  throw new Error(`Missing server-side configuration: ${missing.join(", ")}`);
}

const client = new DevFlowKnowledgeClient({
  origin: process.env.KNOWLEDGE_API_ORIGIN,
  token: process.env.KNOWLEDGE_SERVICE_TOKEN,
  tenantId: process.env.KNOWLEDGE_TENANT_ID,
  timeoutMs: Number(process.env.KNOWLEDGE_TIMEOUT_MS || 35_000),
});

const health = await client.health();
const result = await client.query({
  query: "登录接口返回 401 时应该如何排查？",
  userId: "devflow-smoke-test",
  groups: (process.env.KNOWLEDGE_DEFAULT_GROUPS || "engineering").split(",").map((item) => item.trim()),
  filters: { documentTypes: [], tags: [] },
  topK: 3,
  requestId: `devflow-smoke-${crypto.randomUUID()}`,
});

console.log(JSON.stringify({
  health: health.status,
  retrievalReady: health.retrieval_ready,
  requestIdMatched: result.request_id.startsWith("devflow-smoke-"),
  tenantMatched: result.tenant_id === process.env.KNOWLEDGE_TENANT_ID,
  evidenceCount: result.evidence.length,
  citationContractValid: result.evidence.every((item) => /^knowledge:\/\/[^#]+#chunk=.+$/.test(item.source_uri)),
  untrustedMarkerValid: result.evidence.every((item) => item.metadata.untrusted_retrieved_content === true),
  latencyMs: result.latency_ms,
}, null, 2));

