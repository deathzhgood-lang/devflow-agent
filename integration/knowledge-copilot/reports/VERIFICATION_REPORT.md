# DevFlow 联调验收报告

验收日期：2026-08-14  
服务：Enterprise Knowledge Copilot Service API  
接口端口：8100

## 实际运行验证

| 检查项 | 结果 |
|---|---:|
| `GET /health` | HTTP 200 |
| `POST /api/v1/retrieval/query` | HTTP 200 |
| 健康状态 | `ok` |
| Retrieval ready | `true` |
| 当前聚合文档数 | 78 |
| 当前聚合切块数 | 1978 |
| 本次检索证据数 | 3 |
| 模型预热后的端到端检索延迟快照 | 1980–2459 ms |
| FastAPI 重启后的首次冷请求延迟 | 29067 ms |
| request_id 回传一致 | 通过 |
| tenant_id 回传一致 | 通过 |
| `knowledge://...#chunk=...` | 通过 |
| 不可信证据标记 | 通过 |
| OpenAPI 包含两个正式接口 | 通过 |
| OpenAPI 检出真实 Service Token | 否 |

延迟为本机实测快照，不作为吞吐量或稳定性基准结论。冷请求包含 BGE-M3 与 Reranker 首次加载；标准 `start-demo.ps1` 会主动预热模型。DevFlow 默认超时因此设为 35 秒，生产环境应增加常驻预热与独立推理服务。

## 真实安全矩阵

| 场景 | 预期 | 实际 |
|---|---:|---:|
| 缺少 Service Token，Request-ID 合法 | 401 | 401 |
| Service Token 错误 | 401 | 401 |
| Token 请求其他租户 | 403 | 403 |
| 缺少 `X-Request-ID` | 422 | 422 |
| Header 与 Body Request-ID 不一致 | 422 | 422 |
| 从 8100 访问 `/api/documents` | 404 | 404 |
| 运行日志检出真实 Service Token | 否 | 否 |

## 自动化专项测试

执行范围：

- `backend/tests/test_service_retrieval_api.py`
- `backend/tests/test_service_retrieval_acl.py`

结果：`5 passed`。  
覆盖成功响应、无证据、Token 认证、租户绑定、严格 Schema、Request-ID、超时与内部错误归一化、端口隔离、检索前 ACL、文档 ACL、跨租户隔离、稳定引用及 Prompt Injection 不可信标记。

存在 1 条 Starlette `TestClient` 依赖弃用警告，不影响接口功能，后续依赖升级时处理即可。

交付包自带客户端也已实测：Node.js 客户端通过，PowerShell 客户端通过；两者均验证 request ID、tenant、Citation URI 和不可信证据标记，且不输出 Token、回答正文或证据原文。

## 验收结论

接口、认证、ACL、Citation Contract 和专项测试满足两台电脑联调交付条件。局域网可在限定防火墙范围内开始联调；跨公网前必须增加 TLS 和网络访问控制。
