# DevFlow Agent：MVP 开发路线与简历版

## 1. MVP 范围

### 1.1 唯一主链路

MVP 只保证一个端到端场景：

> 分析指定服务在给定时间范围内的异常，结合历史故障知识和 Git 变更生成带证据的复盘报告；经用户审批后创建整改 Issue。

先用脱敏/模拟企业数据完成可重复演示，再替换真实连接器。这样能评测 Agent 能力，不依赖不可公开的企业账号。

### 1.2 MVP 成功标准

- 计划、步骤状态、工具结果和审批均可在页面查看。
- 任务进程中断后能从最近检查点恢复，不重复已完成的写操作。
- 所有关键结论引用真实 Evidence ID；引用能追溯到模拟日志、指标、Git 或知识结果。
- 只读工具自动执行；`create_issue` 必须审批；拒绝后不产生外部资源。
- 固定评测集可以复跑并生成版本对比报告。
- 演示不依赖手工修改数据库或隐藏后台步骤。

## 2. 真实开发顺序

### 阶段 0：场景、契约与评测夹具（建议先做）

虽然原需求从 Agent Runtime 开始，但工程上应先冻结主链路和测试数据，否则后续没有客观验收基准。

**目标**

定义一个支付服务案例、10–20 条首批评测用例、工具契约和安全边界。

**技术**

JSON Schema、YAML fixtures、Pytest、脱敏模拟数据。

**代码模块**

```text
fixtures/payment_incident/
evaluation/cases/
contracts/tool_schemas/
docs/adr/
```

**验收标准**

- 主案例包含指标、日志、Trace、3 次 Git 变更、2 篇历史事故文档和一个已知根因。
- 用例覆盖正常、缺参数、无权限、工具超时、注入文本、审批拒绝和恢复执行。
- 每个工具输入输出都能独立通过 Schema 校验。

---

### 阶段 1：Agent Runtime

**目标**

用 LangGraph 实现可持久化的确定性骨架：Intent → Planning → Skill Selection → Tool Execution → Reflection → Final。

**技术**

FastAPI、LangGraph StateGraph、Pydantic、PostgreSQL Checkpointer；单元测试可先使用 SQLite/InMemorySaver。

**代码模块**

```text
backend/agent/state.py
backend/agent/graph.py
backend/agent/nodes/
backend/api/tasks.py
backend/api/events.py
```

**验收标准**

- 使用 mock node 完成一次完整状态流转。
- 每个节点只返回 State 增量，输入输出可序列化。
- 任意节点故障后可从最近检查点恢复。
- `max_steps`、`max_replans`、总时长预算能终止循环。

**面试可讲点**

先把 Agent 当作“可恢复状态机”，而不是“一个 while 循环调用 LLM”。

---

### 阶段 2：Tool Calling

**目标**

实现三个本地受控工具，打通结构化工具调用、证据存储、错误归一化和审批。

**首批工具**

1. `query_metrics_fixture`：读取模拟时间序列。
2. `search_logs_fixture`：读取脱敏日志并返回来源行号。
3. `write_report_sandbox`：只写任务沙箱。

`create_issue_mock` 作为第四个审批工具，用于证明副作用控制。

**技术**

Pydantic/JSON Schema、Tool Registry、Policy Engine、idempotency table。

**代码模块**

```text
backend/tools/models.py
backend/tools/registry.py
backend/tools/router.py
backend/tools/policy.py
backend/tools/idempotency.py
backend/tools/internal/
```

**验收标准**

- 非法参数在调用前拒绝；工具异常返回类型化错误。
- 同一幂等键重复执行 `create_issue_mock` 只产生一个资源。
- 无审批时写操作保持 `blocked`；拒绝后资源数仍为 0。
- 每次调用产生 trace_id、duration、status 和 Evidence ID。

---

### 阶段 3：Skill 系统

**目标**

把工具组合、SOP、Prompt、质量门槛和评测封装成可发现、可版本化 Skill。

**首批 Skill**

- `incident_data_analysis`
- `incident_evidence_collection`
- `incident_reasoning`
- `postmortem_generation`
- `issue_coordination`

**技术**

YAML、JSON Schema、BM25/embedding hybrid match、语义化版本、文件监听仅用于开发环境。

**代码模块**

```text
backend/skills/registry.py
backend/skills/validator.py
backend/skills/matcher.py
backend/skills/loader.py
skills/*
```

**验收标准**

- Registry 启动时拒绝缺字段、越权工具或无效 Schema 的 Skill。
- Intent 测试集上的 top-1 Skill 选择达到预设基线。
- 未选中 Skill 的完整 Prompt 不进入模型上下文。
- 运行中任务固定 Skill 版本；发布新版本不改变旧任务。

---

### 阶段 4：Memory

**目标**

区分当前任务状态、历史任务摘要和企业知识；实现恢复、偏好读取与数据保留策略。

**技术**

PostgreSQL、Redis、pgvector 或现有向量库。

**代码模块**

```text
backend/memory/checkpoint.py
backend/memory/working.py
backend/memory/episodic.py
backend/memory/retention.py
backend/memory/redaction.py
```

**验收标准**

- Runtime 重启后可以按 task_id 继续。
- Redis 清空不会丢失持久任务；可从 PostgreSQL 重建热状态。
- 租户 A 无法检索租户 B 的任务摘要。
- 原始日志默认不写长期 Memory；过期任务按策略删除。

---

### 阶段 5：MCP

**目标**

把本地工具迁移为至少三个独立 MCP Server，证明协议解耦、能力发现、远程错误处理和授权。

**MCP Server**

1. Observability MCP：`query_metrics`、`search_logs`、`get_trace`。
2. Git MCP：`search_code`、`get_diff`、`list_commits`、`create_issue_mock`。
3. Workspace MCP：`read_file`、`write_report`、`render_chart`。

Data MCP 可作为加分扩展，不阻塞主链路。

**技术**

MCP Python SDK、STDIO（开发）、Streamable HTTP（集成测试）、OAuth/Bearer 模拟、JSON-RPC。

**代码模块**

```text
mcp_servers/observability/
mcp_servers/git/
mcp_servers/workspace/
backend/mcp/client_pool.py
backend/mcp/catalog.py
backend/mcp/errors.py
```

**验收标准**

- Client 能发现工具并校验 input/output Schema。
- 单个 Server 不可用时只影响相关步骤，任务返回部分结果和明确缺口。
- 写工具仍经过 Runtime Policy 和人工审批；MCP 注解不能绕过策略。
- Trace 可跨 Runtime 和 MCP Server 关联。

---

### 阶段 6：多模态

**目标**

支持监控/日志截图中的关键字段提取，不扩大为通用视觉助手。

**技术**

可插拔 Vision Provider、OCR、Pydantic structured output、附件扫描。

**代码模块**

```text
backend/multimodal/provider.py
backend/multimodal/extractor.py
backend/multimodal/schemas.py
backend/multimodal/redaction.py
```

**验收标准**

- 从测试截图提取 service、timestamp、error_code、log_snippet。
- 低置信度字段在 UI 中要求确认，不静默进入计划。
- 图片中的“忽略规则并执行命令”等文本不会改变 Agent 策略。
- Vision 服务不可用时可手工输入文本继续。

---

### 阶段 7：企业知识库连接

**目标**

通过 Knowledge Skill 调用项目 1 的 RAG Service API，将有出处知识变成 Agent 证据。

**技术**

HTTP client、service token、ACL propagation、circuit breaker、citation contract。

**代码模块**

```text
backend/knowledge/client.py
backend/knowledge/models.py
backend/knowledge/evidence_adapter.py
skills/knowledge_investigation/
```

**验收标准**

- RAG 返回的 document_id/chunk_id/source_uri 完整转换为 Evidence。
- 引用不存在或 ACL 不匹配时拒绝加入最终报告。
- 知识服务超时时，主任务可继续实时数据与 Git 调查，并标注知识证据缺失。
- 恶意文档指令不能触发 Tool 或改变 Plan。

---

### 阶段 8：前端展示

**目标**

让面试官在 3 分钟内看懂 Agent 正在做什么、为何需要审批、结果证据来自哪里。

**技术**

Next.js、React、TypeScript、SSE、Mermaid/Chart library。

**页面**

- 新建任务：请求、附件、服务和时间范围。
- Task Timeline：节点、步骤、耗时、重试、当前状态。
- Plan & Evidence：计划 DAG、证据抽屉、来源链接。
- Approval Center：动作预览、参数差异、approve/edit/reject。
- Report：复盘、图表、引用、未验证项、Issue 链接。
- Eval Dashboard：版本、成功率、引用覆盖、安全用例和延迟。

**验收标准**

- 页面刷新后任务进度不丢失。
- 工具执行和审批通过 SSE 实时更新。
- 审批参数与实际调用参数哈希一致；修改参数后重新审批。
- 关键结论点击即可展开证据；失败步骤显示可操作原因。

## 3. 建议里程碑

| 里程碑 | 包含阶段 | 可演示结果 |
|---|---|---|
| M1 可控执行 | 0–2 | mock 工具跑通、审批、恢复、证据 |
| M2 可扩展能力 | 3–5 | Skill Registry + 3 MCP Server |
| M3 完整业务闭环 | 6–8 | 截图、知识库、前端、复盘和 Issue |
| M4 生产化证明 | 横向增强 | 安全红队、故障注入、评测回归、SLO |

不要按“八个技术名词各做一天”推进。每个里程碑都必须保持主链路可运行，避免最后才集成。

## 4. 测试策略

### 4.1 测试金字塔

- Unit：Planner validator、Policy、Schema、Skill match、Memory filter。
- Contract：每个 MCP Tool 的 input/output、错误和超时。
- Workflow：正常、澄清、审批拒绝、工具失败、恢复。
- Security：越权、路径穿越、SQL 注入、Prompt Injection、重复写入。
- Eval：固定任务集对不同 Prompt/模型/Skill 版本做回放。
- UI E2E：提交任务、查看事件、审批、打开证据和报告。

### 4.2 必须演示的故障注入

1. `search_logs` 第一次超时，第二次成功。
2. Agent 在生成报告前重启，从检查点恢复。
3. `create_issue` 成功但响应丢失，通过幂等键找回已有 Issue。
4. 历史文档含恶意 Prompt，策略不受影响。
5. 用户无 `git:write` 权限，请求被拒绝且审计可见。

## 5. 三分钟演示脚本

1. 展示请求：“分析支付服务最近 30 天异常，生成复盘并创建整改 Issue。”
2. 展示结构化 Plan，而不是聊天气泡。
3. 展示指标、日志、历史文档和 Git diff 并行收集，关键结论绑定 Evidence。
4. 故意让日志 MCP 超时一次，展示受控重试与 Trace。
5. 展示报告草稿和“未验证假设”。
6. 展示 `create_issue` 审批卡片；拒绝一次证明没有副作用，再重新发起并批准。
7. 展示任务恢复或幂等结果与 Eval Dashboard。

面试官应在演示后记住三点：跨系统闭环、可控副作用、证据与评测。

## 6. README 中应展示的成果

- 一张架构图和一张 LangGraph 状态图。
- 一段 60–90 秒 GIF/视频，展示计划、证据和审批。
- 一条可复制的 Docker Compose 启动命令。
- 一组模拟数据和一键评测命令。
- 一个评测结果表，明确环境、样本数、版本和日期。
- 设计权衡：为什么单 Agent、为什么不是普通 Workflow、为什么 MCP、为什么 RAG 外置。

## 7. 一页简历描述

### 项目名称

**DevFlow Agent — 企业研发故障调查与变更协同平台**

### 项目简介

面向研发与 SRE 的企业智能任务执行平台，围绕“异常数据分析—日志/Trace 取证—历史故障检索—代码变更关联—复盘报告—整改 Issue”构建可恢复、可审批、可审计的任务闭环；与 Enterprise Knowledge Copilot 组合，分别负责知识获取和任务执行。

### 技术栈

Python、FastAPI、LangGraph、Pydantic、MCP Python SDK、PostgreSQL、Redis、pgvector/Vector DB、Next.js、Docker、OpenTelemetry、Prometheus、Pytest。

### 简历 Bullet（实现后可直接使用）

- 基于 LangGraph 设计“确定性控制面 + 有界 LLM 决策”的 Agent Runtime，将意图识别、结构化规划、Skill 选择、工具执行、证据校验、人工审批与结果生成建模为可持久化状态图，支持任务中断恢复、分级重试、预算终止和步骤级 Trace。
- 设计可版本化 Skill Registry，将故障取证、异常分析、知识调查、变更关联、复盘生成等 SOP 封装为包含 Prompt、I/O Schema、工具依赖、权限和评测用例的工作流包；实现渐进式加载，并通过 Observability、Git、Workspace 三类 MCP Server 标准化企业工具接入。
- 构建 Tool Policy 与 Memory 体系，采用 RBAC/ABAC、JSON Schema、参数哈希审批、幂等键和 Evidence Store 控制写操作并保证结论可追溯；使用 PostgreSQL Checkpoint、Redis 热状态和长期任务摘要实现跨会话恢复及租户隔离。
- 使用 FastAPI/Next.js/Docker 完成端到端交付，接入 OpenTelemetry 与 Prometheus 监控任务、节点、模型和工具调用，并以 Golden Set、故障注入和安全红队用例持续评测规划有效性、工具准确率、引用覆盖率、恢复能力及未授权操作阻断率。

### 量化 Bullet 模板（有真实数据后替换）

严禁把目标写成结果。完成实现后，从评测报告中选 1–2 个事实替换：

- 在 `N` 条脱敏故障任务上，端到端任务完成率从 `A%` 提升到 `B%`，关键结论证据覆盖率达到 `C%`。
- 通过检查点与幂等机制，在 `N` 次进程中断/响应丢失故障注入中实现 `X%` 可恢复且 `0` 次重复 Issue 创建。
- 在 `N` 条越权与 Prompt Injection 用例上阻断 `X/N` 条，未授权写操作为 `0`。

### 简历短版（空间不足时）

**DevFlow Agent｜企业研发故障调查与变更协同平台**：基于 FastAPI、LangGraph、MCP、PostgreSQL/Redis 与 Next.js，实现可控 Agent Workflow，编排监控、日志、Git 和企业知识服务完成异常调查、证据关联、复盘生成及审批后整改协同；设计版本化 Skill Registry、Tool Policy、Checkpoint/Memory、幂等写入和全链路 Trace，并通过固定评测集与故障注入验证计划、工具、引用、安全和恢复能力。

## 8. 每句简历的证据清单

| 简历主张 | 仓库中必须存在的证据 | 面试演示 |
|---|---|---|
| 可恢复状态图 | graph.py、checkpoint migration、恢复测试 | 中途停进程后继续 |
| 结构化 Planning | prompt、JSON Schema、validator、评测集 | 展示无效计划被拒绝 |
| Skill Registry | 至少 5 个 Skill、版本/权限/测试 | 新增 Skill 无需改 Graph |
| 3 个 MCP Server | 独立 server、contract tests | 关闭一个 Server 降级 |
| 审批与幂等 | policy、approval、idempotency 表 | 重复创建只得一个 Issue |
| Memory/租户隔离 | schema、RLS/过滤测试、retention job | A 租户查不到 B 数据 |
| 可观测性 | Trace 截图、Prometheus dashboard | 从结论跳到 tool span |
| 评测 | 数据集、runner、版本报告 | 比较两个版本回归结果 |

## 9. 求职叙事

### 9.1 30 秒介绍

“我已有一个 Enterprise Knowledge Copilot，解决企业知识检索问题。第二个项目 DevFlow Agent 解决的是行动问题：以研发故障调查为场景，用 LangGraph 把计划、Skill、MCP 工具、Memory、审批和评测组成可恢复状态机。它会收集指标、日志、历史故障与 Git 证据，生成复盘，并且只有人工审批后才能创建整改 Issue。两个项目分别证明我能做高质量 RAG 和生产化 Agent。”

### 9.2 为什么需要 Agent

异常调查的下一步依赖中间证据，分支不能完全预先穷举；模型适合做意图理解、计划候选和证据综合。但权限、审批、重试、终止与副作用必须由确定性工作流控制。

### 9.3 为什么不只用普通 Workflow

能固定的部分仍然用 Workflow。只有证据驱动、路径不固定的部分才引入 Agent 决策。如果业务流程完全固定，我会直接选 Temporal/Celery/普通 DAG，而不会强行用 LLM。

### 9.4 为什么使用 MCP

Tool Calling 是模型与某个函数的调用机制；MCP 提供跨宿主的工具发现、连接和调用标准，使 Agent Runtime 不绑定某个 Git/监控 SDK，并便于独立部署、授权和审计。MCP 不替代 Policy Engine。

### 9.5 Agent 如何保证可靠

不是靠一条更长 Prompt，而是靠状态检查点、Schema、权限过滤、审批、幂等、重试分类、预算终止、Evidence Gate、Trace 和离线回归共同保证。

### 9.6 如何从 Demo 走向生产

先限定一个业务闭环和只读工具；再补持久化、错误语义、审批、幂等、评测与数据治理；最后才扩系统、扩 Skill、灰度模型与规模化部署。生产化是治理和可运营能力，不是把 Demo 放进 Docker 就结束。
