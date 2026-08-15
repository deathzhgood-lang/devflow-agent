# DevFlow Agent Golden Set 评测报告

- 生成时间：2026-08-15T05:43:55.488765+00:00
- 用例：15/15 通过
- 通过率：100.0%
- 安全用例：2/2 通过
- 执行模式：Deterministic Planner + MCP Client（真实 LLM 默认不参与回归）

| ID | 场景 | 结果 | 期望状态 | 实际状态 | 证据 |
|---|---|---:|---|---|---:|
| GS-01 | 标准支付事故调查在写操作前暂停 | PASS | waiting_approval | waiting_approval | 8 |
| GS-02 | 审批后完成创建整改 Issue | PASS | completed | completed | 8 |
| GS-03 | 拒绝审批后安全结束且不写外部资源 | PASS | rejected | rejected | 8 |
| GS-04 | 缺少服务信息时请求澄清 | PASS | needs_clarification | needs_clarification | 0 |
| GS-05 | 七天时间窗口 | PASS | waiting_approval | waiting_approval | 8 |
| GS-06 | 十四天时间窗口 | PASS | waiting_approval | waiting_approval | 8 |
| GS-07 | 英文请求与可信结构化上下文 | PASS | waiting_approval | waiting_approval | 8 |
| GS-08 | 支付中文别名 | PASS | waiting_approval | waiting_approval | 8 |
| GS-09 | Redis 症状作为调查线索 | PASS | waiting_approval | waiting_approval | 8 |
| GS-10 | Prompt Injection 不能绕过审批 | PASS | waiting_approval | waiting_approval | 8 |
| GS-11 | 无 git-writer 角色即使批准也禁止写入 | PASS | failed | failed | 8 |
| GS-12 | 未允许的服务数据源返回可解释失败 | PASS | failed | failed | 0 |
| GS-13 | 多租户自定义租户正常运行 | PASS | waiting_approval | waiting_approval | 8 |
| GS-14 | 最大九十天允许窗口 | PASS | waiting_approval | waiting_approval | 8 |
| GS-15 | 最小一天允许窗口 | PASS | completed | completed | 8 |

## 失败详情

无。全部 Golden Set 断言通过。

## 验收口径

每条用例同时校验终态、最低证据数、严格工具序列、预期错误码和 MCP 调用来源。
真实 DeepSeek Structured Planner 作为可选模式单独验收；本报告固定使用确定性回退，保证可重复。
