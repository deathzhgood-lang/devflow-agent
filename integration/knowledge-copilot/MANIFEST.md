# 交付清单

## 包含

- 两个正式接口的 OpenAPI 契约
- 严格请求、成功响应和错误响应示例
- Node.js 集成客户端
- Windows PowerShell 冒烟测试
- Citation Contract
- Service Token、租户、用户组与 ACL 说明
- 局域网与 TLS 部署说明
- 脱敏验收报告
- SHA-256 文件校验表

## 明确不包含

- 真实 Service Token 或任何 Authorization 值
- `.env` 文件
- DeepSeek、OpenAI 或其他模型 API Key
- 数据库密码、JWT 私钥、证书私钥
- SQLite 数据库、Qdrant 目录、Embedding 缓存
- 原始知识库、用户上传文档、真实检索原文
- 运行日志或包含请求头的抓包文件

## 交付对象

此包用于 DevFlow Agent 服务端集成，不应分发到浏览器前端或公开静态资源目录。

