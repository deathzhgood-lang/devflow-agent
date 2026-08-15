# 网络与 TLS 联调说明

## 同一局域网

1. Knowledge Copilot 服务监听 `0.0.0.0:8100`。
2. DevFlow 配置 `http://<Knowledge-Copilot-私网IP>:8100`。
3. Windows 防火墙仅对 Private 配置文件和 DevFlow 电脑 IP 或可信子网开放 TCP 8100。
4. 不要关闭防火墙，也不要建立 Any/Any 的长期入站规则。

示例规则中的地址必须替换为实际可信私网范围：

```powershell
New-NetFirewallRule `
  -DisplayName "Enterprise Knowledge Copilot - DevFlow" `
  -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8100 `
  -Profile Private -RemoteAddress "192.168.1.0/24"
```

DevFlow 电脑可先检查连通性：

```powershell
Test-NetConnection <Knowledge-Copilot-私网IP> -Port 8100
Invoke-RestMethod http://<Knowledge-Copilot-私网IP>:8100/health
```

## 跨公网或不同网络

禁止直接开放无 TLS 的 8100 公网端口。应使用以下任一方式：

- Cloudflare Tunnel，将公网 HTTPS 主机名转发到本机 `127.0.0.1:8100`；
- 企业 HTTPS 反向代理，并限制来源 IP、mTLS 或 Zero Trust Access；
- VPN/组网工具，让两台电脑通过私网地址通信。

公网配置中的 `KNOWLEDGE_API_ORIGIN` 必须使用 `https://`。TLS 网关负责证书，FastAPI 仍只在内网或回环地址提供 HTTP Origin。

## 接口边界

8100 端口只发布：

- `GET /health`
- `POST /api/v1/retrieval/query`
- `/docs` 与 `/openapi.json`

文档上传、用户管理等管理接口在 8100 应返回 404。

