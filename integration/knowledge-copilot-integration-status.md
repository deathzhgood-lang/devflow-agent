# Knowledge Copilot 联调状态

更新日期：2026-08-14

## 已完成

- 对方交付包已归档到 `integration/knowledge-copilot/`。
- `SHA256SUMS.txt` 中 14 个文件全部校验一致。
- OpenAPI 版本为 `1.0.0`，只暴露 `/health` 与 `/api/v1/retrieval/query` 两个正式接口。
- DevFlow 请求、响应、认证和错误处理已对齐交付契约。
- DevFlow 强制校验每条 Citation 的 `metadata.untrusted_retrieved_content=true`。
- DevFlow 支持对方 `latency_ms` 与分阶段 `latency` 字段。
- HTTP 超时调整为 35 秒；Knowledge MCP 外层超时覆盖有限重试总时长。
- 对方实测：78 个文档、1978 个切块、3 条检索证据、专项测试 5 项通过。
- 本项目全量测试与 15 条 Golden Set 均通过。
- 2026-08-14 从 DevFlow 电脑 `192.168.0.3` 实测连接 `192.168.0.4:8100`：TCP 成功。
- 真实 `/health` 返回 `status=ok`、服务版本 `3.2.0`、`retrieval_ready=true`、78 个文档和 1978 个切块。
- 线上 OpenAPI 版本 `1.0.0`，接口和 ServiceToken 安全方案与交付包一致。
- Service Token 已由用户分别配置在两台电脑的本地环境中，未进入聊天、代码或报告。
- 带认证的独立检索通过：Tenant 与 Request ID 一致，返回 3 条真实 Citation，最高相关度 `0.7548`。
- Agent 联合任务 `task_125a6de32fab` 完成：DeepSeek Structured Planner → MCP Client → Knowledge MCP → 远程 Knowledge HTTP API → Evidence → 报告 → 人工审批 → 模拟 Issue。
- Agent S3 使用 `provider=remote`，Query ID 为 `q_3b2f14712e574573a78bed029c2bf739`，Retrieval Version 为 `2026-08-13`，经 Knowledge MCP 第一次调用成功。
- 联合任务累计 9 条证据，其中 3 条来自远程 Knowledge Copilot；创建模拟 Issue `ISSUE-B79479FB`。
- 联合任务 Evaluation 为 `100 / A+ / passed=true`。

## 联调结论

两台电脑的真实连接已经完成并通过验收。DevFlow 当前运行配置为 `DEVFLOW_KNOWLEDGE_MODE=remote`，不再使用本地 Fixture 作为正常知识来源；Fixture 只保留为远程可用性故障时的演示降级。

## 运行维护

1. 保持 Knowledge Copilot 服务监听 `192.168.0.4:8100`，且防火墙只允许可信私网或 DevFlow 电脑。
2. Service Token 轮换时，同时更新两台电脑的本地环境变量；不要发送到聊天：
   - Knowledge Copilot：`KNOWLEDGE_SERVICE_TOKEN`
   - DevFlow：`KNOWLEDGE_API_TOKEN`
3. DevFlow 当前配置口径：

```dotenv
DEVFLOW_KNOWLEDGE_MODE=remote
KNOWLEDGE_API_BASE=http://192.168.0.4:8100
KNOWLEDGE_API_TOKEN=<本地填写>
KNOWLEDGE_TIMEOUT_SECONDS=35
KNOWLEDGE_MAX_RETRIES=1
KNOWLEDGE_FIXTURE_FALLBACK=true
```

4. 需要重新验收时执行：

```powershell
Test-NetConnection 192.168.0.4 -Port 8100
python verify_knowledge.py --tenant local-demo --groups engineering
```

联调检查应确认 `search_knowledge` 的 `provider=remote`、`query_id`、`retrieval_version` 与真实 Knowledge Evidence URI。
