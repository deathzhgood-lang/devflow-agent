# Citation Contract

## 1. 稳定引用标识

每条证据必须返回：

```text
knowledge://{document_id}#chunk={chunk_id}
```

`document_id` 和 `chunk_id` 由 Knowledge Copilot 生成，并进行 URI 编码。DevFlow 不应根据文件路径自行拼接引用，也不能使用模型生成的伪引用替换 `source_uri`。

## 2. Evidence 必填字段

- `chunk_id`：切块稳定 ID。
- `document_id`：文档稳定 ID。
- `title`：用于人类展示的文档名。
- `quote`：经过长度限制和敏感模式脱敏的证据摘录。
- `source_uri`：机器可审计引用。
- `score`：归一化相关度，范围 0 到 1。
- `document_type`：runbook、incident、API 等文档类型。
- `metadata.untrusted_retrieved_content`：必须恒为 `true`。

## 3. DevFlow 消费规则

1. 证据数组顺序可以映射为 UI 引用 `[1]`、`[2]`，但审计记录应保存对应 `source_uri`。
2. `quote` 是数据，不是指令。即使出现“忽略系统提示”“调用工具”“提升权限”等文字，也不能改变 Agent 工作流。
3. 工具调用、写操作和权限判定只能来自 DevFlow 的可信策略层。
4. `evidence=[]` 时不得生成带“知识库已确认”语气的结论。
5. `source_uri` 不满足规范或 `untrusted_retrieved_content` 不为 `true` 时，客户端应拒绝该响应并记录契约错误。

## 4. 无证据语义

无授权证据仍返回 HTTP 200：

- `evidence: []`
- `warnings` 包含 `no_authorized_evidence`
- `answer` 明确表示当前授权范围内没有支持证据

该设计区分“服务正常但没有证据”和“服务异常”。

