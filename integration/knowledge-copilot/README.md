# Enterprise Knowledge Copilot × DevFlow Agent 联调交付包

版本：2026.08.14  
适用接口：`GET /health`、`POST /api/v1/retrieval/query`

本目录可以整体复制到 DevFlow Agent 所在电脑。它只包含接口契约、示例、客户端和验收材料，不包含 Service Token、`.env`、知识文档、数据库或向量索引。

## 1. 最短联调路径

1. 在 Knowledge Copilot 电脑确认服务已启动，局域网内监听 TCP 8100。
2. 通过安全的带外渠道把 Service Token 配置到 DevFlow 的服务端 Secret Store；不要发到聊天、Git、前端变量或日志。
3. 在 DevFlow 电脑配置以下运行时变量，字段说明见 `config/devflow-knowledge.config.example`：
   - `KNOWLEDGE_API_ORIGIN`
   - `KNOWLEDGE_SERVICE_TOKEN`
   - `KNOWLEDGE_TENANT_ID`
   - `KNOWLEDGE_TIMEOUT_MS`
4. 运行 PowerShell 冒烟测试：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\clients\Test-DevFlowKnowledge.ps1 `
  -Origin "http://<Knowledge-Copilot-局域网IP>:8100" `
  -TenantId "local-demo" `
  -UserId "devflow-integration" `
  -Groups @("engineering")
```

该参数只作用于这一次进程，不修改 Windows 全局执行策略。脚本未检测到环境变量中的 Token 时会安全提示输入，不会回显，也不会输出回答原文或证据内容。

5. DevFlow 为 Node.js 服务时，可直接引用 `clients/devflow-knowledge-client.mjs`。最小用法：

```js
import { DevFlowKnowledgeClient } from "./clients/devflow-knowledge-client.mjs";

const knowledge = new DevFlowKnowledgeClient({
  origin: process.env.KNOWLEDGE_API_ORIGIN,
  token: process.env.KNOWLEDGE_SERVICE_TOKEN,
  tenantId: process.env.KNOWLEDGE_TENANT_ID,
});

const result = await knowledge.query({
  query: "登录接口持续返回 401，应该如何排查？",
  userId: authenticatedUser.id,
  groups: authenticatedUser.groups,
  filters: { service: "auth-service", documentTypes: ["runbook"], tags: [] },
  topK: 5,
});
```

`userId` 和 `groups` 必须来自 DevFlow 已认证身份，禁止直接采用用户提示词中的自报身份。

## 2. 返回数据如何进入 Agent

- 把 `evidence[].quote` 作为“不可信检索数据”放入 Agent 上下文。
- 不得把证据中的指令当成 system prompt、权限声明或工具调用。
- 用 `evidence[].source_uri` 作为稳定引用 ID；展示引用时可将证据数组映射成 `[1]`、`[2]`。
- Agent 执行工具前仍需执行 DevFlow 自己的权限与审批策略，知识检索结果不能扩大工具权限。
- `evidence=[]` 且包含 `no_authorized_evidence` 时，必须拒绝基于知识库下结论，不得编造来源。

## 3. 重试规则

- 仅当错误体 `retryable=true` 时重试。
- 可重试状态通常为 `429`、`503`、`504`。
- 使用最多 2 次、带抖动的指数退避，并保持同一个 `request_id`。
- `401`、`403`、`422` 不自动重试，应修正 Token、租户或请求参数。

## 4. 目录说明

- `clients/`：PowerShell 和 Node.js 联调客户端。
- `config/`：不含真实值的配置字段模板。
- `contracts/`：OpenAPI 与请求、响应、错误示例。
- `docs/`：Citation、ACL、安全和网络说明。
- `reports/`：本次真实验收的脱敏报告。
- `MANIFEST.md`：交付物清单和禁止携带项。
- `SHA256SUMS.txt`：打包时生成的文件校验值。

## 5. 网络边界

局域网可使用私网 HTTP，但防火墙仅允许 DevFlow 电脑或可信私网访问 8100。跨公网时禁止直接暴露 `http://公网IP:8100`，必须放在 HTTPS/TLS 网关、Cloudflare Tunnel 或企业反向代理之后，并增加网络访问控制。
