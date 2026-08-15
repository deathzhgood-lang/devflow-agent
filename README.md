# DevFlow Agent — Enterprise AI Agent Platform

面向 2026 AI 应用开发岗位的企业级 Agent 求职项目。项目聚焦“研发故障调查与变更协同”，证明 AI 不只会回答问题，还能在权限、审批、审计和评测约束下，调用企业知识与工具完成跨系统任务。

当前仓库已包含可运行 MVP：FastAPI + LangGraph Runtime、SQLite 持久化、7 个 Skill、MCP Client 主链、Evidence Chain、人工审批、写操作幂等、4 个 MCP Server、可插拔远程 Knowledge Client、Prometheus 指标、Next.js 前端、Docker、43 个自动化测试和 15 条 Golden Set。

第二阶段已加入任务级 Agent Evaluation：对任务完成度、证据完备性、安全合规、审计可追溯性和执行可靠性进行确定性评分，并在操作台展示质量门、等级与完整事件时间线。

第三阶段加入 DeepSeek Hybrid Mode：使用 DeepSeek V4 JSON Output 完成意图识别、结构化计划和证据推理，Pydantic 与 Policy Catalog 负责校验；模型不可用或输出越界时自动回退到确定性执行路径。

## 项目组合定位

| 项目 | 负责的问题 | 核心能力 |
|---|---|---|
| Enterprise Knowledge Copilot | 企业知识如何被准确获取 | RAG、Hybrid Retrieval、Reranker、Citation |
| DevFlow Agent | 企业任务如何被可靠执行 | 可控工作流、Planning、Skill、Tool、MCP、Memory、HITL、Evaluation |

一句话边界：**RAG 负责提供有出处的知识，Agent 负责基于知识采取受控行动。**

## 文档导航

- [项目总设计](docs/01-Enterprise-AI-Agent-Platform-项目总设计.md)：业务定位、总体架构、Agent Brain、Planner、Skill、MCP、Tool、Memory、多模态、RAG 集成、安全评测与工程化。
- [MVP 开发路线与简历版](docs/02-MVP开发路线与简历版.md)：8 个开发阶段、模块清单、验收标准、演示脚本和一页简历描述。
- [面试手册](docs/03-Enterprise-AI-Agent-Platform-面试手册.md)：16 个知识章节和 50 道项目追问，每题含关注点、标准回答与深入扩展。
- [当前项目全景与验收报告](docs/04-当前项目全景与验收报告.md)：当前真实实现、验收证据、能力边界与生产化差距。
- [Knowledge Copilot 远程接入指南](docs/05-Knowledge-Copilot-远程接入指南.md)：跨电脑配置、请求/Citation Contract、降级策略和联调步骤。
- [项目背书与简历模板](docs/06-项目背书与简历模板.md)：量化证据、事实边界、岗位定制简历、面试话术与演示脚本。

## 推荐演示任务

> 分析最近一个月支付服务的异常情况，结合历史故障文档和最近代码变更定位可能原因，生成带证据的复盘报告；经我确认后创建整改 Issue。

这个任务同时覆盖数据查询、异常分析、知识检索、代码关联、报告生成、人工审批和写操作审计，能完整体现企业 Agent 的价值。

## 快速运行

### 本地开发

```powershell
# 后端（仓库根目录）
$env:PYTHONPATH = "backend"
python -m uvicorn devflow.api:app --reload --port 8000

# 前端（另一个终端）
Set-Location frontend
npm.cmd install
npm.cmd run dev
```

### 启用 DeepSeek

项目根目录的 `.env` 已准备好且被 Git 忽略。只在本机填写密钥：

```dotenv
DEVFLOW_LLM_ENABLED=true
DEEPSEEK_API_KEY=your-local-key
DEEPSEEK_MODEL=deepseek-v4-flash
```

重新启动后端后，`GET /health` 中应显示：

```json
{"llm":{"enabled":true,"mode":"deepseek_hybrid","provider":"deepseek","model":"deepseek-v4-flash"}}
```

可将模型切换为 `deepseek-v4-pro`，也可通过 `DEEPSEEK_THINKING=true` 开启思考模式。密钥不会进入前端、任务状态、事件、Trace 属性或日志。

### 接入远程 Knowledge Copilot

默认使用离线 Fixture。另一台电脑的 Knowledge API 就绪后，在 `.env` 中配置：

```dotenv
DEVFLOW_KNOWLEDGE_MODE=remote
KNOWLEDGE_API_BASE=http://<局域网IP>:8100
KNOWLEDGE_API_TOKEN=<只在本地填写>
KNOWLEDGE_TIMEOUT_SECONDS=35
KNOWLEDGE_MAX_RETRIES=1
KNOWLEDGE_FIXTURE_FALLBACK=true
```

完整契约和联调清单见 `docs/05-Knowledge-Copilot-远程接入指南.md`。

访问：

- 前端：http://localhost:3000
- API 文档：http://localhost:8000/docs
- 健康检查：http://localhost:8000/health
- Prometheus 指标：http://localhost:8000/metrics
- 任务评测：`GET /api/tasks/{task_id}/evaluation`
- 审计事件：`GET /api/tasks/{task_id}/audit`

### Docker

```powershell
docker compose up --build
```

### 验证

```powershell
python -m pytest
python evaluate.py
Set-Location frontend
npm.cmd run typecheck
npm.cmd run build
```

`python evaluate.py` 会固定使用 Deterministic Planner + MCP Client，生成
`evaluation/reports/golden-set-latest.md` 与 `.json`；真实 DeepSeek 不参与该可重复回归基线。

## 可运行闭环

1. Intent Detection 识别服务与时间范围。
2. Planner 生成 7 步、带依赖和风险等级的结构化计划。
3. Runtime 依次收集指标、日志、知识、Git 变更并形成根因假设。
4. Workspace Tool 在任务沙箱生成带 Evidence ID 的复盘报告。
5. `create_issue` 前暂停，等待人工批准或拒绝。
6. 批准后按参数哈希恢复执行并幂等创建模拟 Issue；拒绝则不产生写操作。
7. Evaluation Engine 对五个质量维度加权评分，并执行高风险审批、证据来源和状态一致性硬门禁。

## Agent 评测体系

| 维度 | 权重 | 核心检查 |
|---|---:|---|
| 任务完成度 | 25% | 成功步骤比例、安全暂停与跳过状态 |
| 证据完备性 | 25% | Evidence 数量、来源类型、URI、内容哈希、根因分析 |
| 安全合规 | 25% | 高风险工具审批、参数哈希、审批生命周期一致性 |
| 审计可追溯性 | 15% | 核心事件覆盖率、事件顺序与节点记录 |
| 执行可靠性 | 10% | 运行错误与失败步骤 |

总分达到 85 且没有硬门禁失败才算通过。评分过程完全确定、可解释，适合回归测试和面试现场演示；生产环境可在此基础上叠加 LLM-as-Judge 与人工标注集。

## MCP Server

使用官方 MCP Python SDK 2.x：

```powershell
$env:PYTHONPATH = "backend;."
python -m mcp_servers.observability_server
python -m mcp_servers.knowledge_server
python -m mcp_servers.git_server
python -m mcp_servers.workspace_server
```

- Observability：`query_metrics`、`search_logs`、`get_trace`
- Knowledge：`search_knowledge`
- Git：`list_commits`、`search_code`、`create_issue`
- Workspace：`read_report`、`correlate_evidence`、`write_report`、`list_reports`

Runtime 默认通过 MCP Client 路由全部 7 个计划工具。客户端 Gateway 先检查角色、风险和审批，Git MCP 写工具会再次验证持久任务中的审批状态与精确参数哈希；MCP 元数据本身不会被当作授权。传输层带超时与有限重试，响应丢失后的写重试由幂等记录收敛。

## 设计原则

1. 业务闭环优先，不为展示技术强行添加功能。
2. 采用“确定性骨架 + 有界 LLM 决策”，不做完全自由 Agent。
3. 默认只读；写操作必须经过策略检查、人工审批和幂等保护。
4. 所有结论绑定证据，所有工具调用可追踪、可恢复、可评测。
5. MVP 只做单 Agent 编排；多 Agent 仅在职责与权限真正需要隔离时再引入。

## 当前实现边界

- 默认使用确定性 Planner 和脱敏模拟企业数据，保证没有 API Key 也能复现和回归；生产 LLM Planner 只需实现同一 Pydantic/JSON Schema 契约。
- 本地 MVP 使用 SQLite；生产设计迁移为 PostgreSQL Checkpoint + Redis 热状态。
- Issue 创建是带稳定 ID 的模拟外部写入，不会修改真实 Git 平台。
- 当前实现没有自动修改生产配置、部署、删除或任意 Shell/SQL 能力。
- 不虚构生产效果指标；简历量化结果必须从真实评测报告中填写。
