# 认证、ACL 与安全边界

## Service Token

- Bearer Service Token 只认证 DevFlow 服务调用方，不代表最终用户权限。
- Token 在 Knowledge Copilot 端绑定固定 `tenant_id`，请求体不能扩大租户范围。
- Token 只能保存在 DevFlow 服务端 Secret Store 或进程环境中。
- 禁止放入浏览器变量、Git、配置示例、错误消息、URL 查询参数或日志。
- 轮换 Token 后应重启服务端进程，并同步更新 DevFlow Secret；旧 Token 立即停止使用。

## 最终用户上下文

- `user_id` 和 `groups` 必须由 DevFlow 已认证会话产生。
- 禁止从自然语言问题中提取“我是管理员”等声明作为授权依据。
- Knowledge Copilot 在检索前构建授权文档 ID 范围，再执行 Dense、BM25、RRF 与 Reranker。
- Evidence 构造阶段会再次检查文档 ID，形成双重边界。

## ACL 顺序

```text
Service Token
  -> tenant binding
  -> Knowledge Space 状态与归属
  -> 用户/用户组空间权限
  -> 文档 access_level 与 allowed_users/allowed_groups
  -> service/document_types/tags 元数据过滤
  -> Hybrid Retrieval
  -> Evidence 二次 ID 检查
```

## Prompt Injection

所有证据均带 `metadata.untrusted_retrieved_content=true`。DevFlow 必须保持系统提示、授权策略、工具审批与检索文本分层，不能让知识文档中的文字修改 Agent 权限或触发工具。

## 日志

允许记录：request ID、query ID、tenant hash、top-k、证据数量、延迟、错误码。  
禁止记录：Authorization Header、Service Token、原始问题、完整文档文本、数据库连接密码。

## HTTP 状态处理

- `401`：缺少或错误 Token；不重试。
- `403`：Token 与租户不匹配；不重试。
- `422`：Schema、top-k 或 Request-ID 错误；修正请求后再发。
- `429`：限流；可按 `retryable` 退避重试。
- `503`、`504`：暂时不可用或超时；可做有界重试。

