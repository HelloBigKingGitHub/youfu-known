# 外网访问配置指南

把局域网内的 Pi 服务暴露到公网, 走 Cloudflare Tunnel。

## 架构

```
[公网用户] ──HTTPS──> [Cloudflare Edge] ──tunnel──> [cloudflared on Pi] ──HTTP 127.0.0.1──> [uvicorn :8000]
```

特点:
- ✅ 完全免费 (Cloudflare Zero Trust 免费版)
- ✅ 自动 HTTPS
- ✅ 无需路由器端口转发 / 公网 IP 暴露
- ✅ 国内访问速度尚可 (CF 在长沙/广州等有节点)
- ✅ Pi 上只听 127.0.0.1, 公网/局域网其它机器无法直接访问 :8000

## 前置准备 (一次性, 30 分钟)

### 1. 把 sxy.homes 加到 Cloudflare

1. 注册/登录 https://dash.cloudflare.com
2. Add a Site → 输入 `sxy.homes` → Select Free Plan
3. Cloudflare 给 2 个 nameserver 地址 (形如 `xxx.ns.cloudflare.com`)
4. 去你的域名注册商 (阿里云/腾讯云/Gandi 等) 把 NS 改成这 2 个
5. 等 24-48 小时 NS 生效 (CF 控制台会显示 "Active")

### 2. 创建 Cloudflare API Token

1. https://dash.cloudflare.com/profile/api-tokens → Create Token
2. **Create Custom Token**
3. 权限:
   - `Account` → `Cloudflare Tunnel: Edit`
   - `Account` → `Account Settings: Read`
   - `Zone` → `DNS: Edit`
4. Zone Resources: Include → Specific zone → `sxy.homes`
5. TTL: 你定
6. Create → **复制 Token** (只显示一次)

### 3. (可选) 准备好你希望对外的子域名

建议 `kb.sxy.homes` (知识库, 短好记)

## 一键安装

```bash
export CF_TOKEN=<你的 API Token>
export CF_ZONE=sxy.homes
export CF_SUBDOMAIN=kb

bash scripts/cloudflare/setup_tunnel.sh
```

脚本会:
1. 调 Cloudflare API 创建 tunnel (name: `youfu-pi`)
2. 在 DNS 加 CNAME: `kb.sxy.homes` → `<tunnel-id>.cfargotunnel.com` (proxied)
3. Pi 上下载装 `cloudflared` (.deb 包)
4. 写 `/home/youfu/.cloudflared/config.yml`
5. 装 systemd unit + 启动 cloudflared
6. 锁定 youfu-known 服务为 `127.0.0.1:8000` (只有 tunnel 能访问)
7. 验证 `https://kb.sxy.homes/api/health`

## 访问地址

- **API**: `https://kb.sxy.homes/api/health`
- **Web UI**: `https://kb.sxy.homes`
- **API docs**: `https://kb.sxy.homes/docs`

## 管理命令

```bash
# 看 tunnel 状态
ssh -i ~/.ssh/id_rsa_pi youfu@<Pi_IP> \
    "sudo systemctl status cloudflared"

# 看 tunnel 日志
ssh -i ~/.ssh/id_rsa_pi youfu@<Pi_IP> \
    "sudo journalctl -u cloudflared -n 50 -f"

# 重启 tunnel
ssh -i ~/.ssh/id_rsa_pi youfu@<Pi_IP> \
    "sudo systemctl restart cloudflared"

# 重启 youfu-known (本地)
ssh -i ~/.ssh/id_rsa_pi youfu@<Pi_IP> \
    "sudo systemctl restart youfu-known"
```

## 添加更多子域名

如要加 `docs.sxy.homes` 指向另一个端口 (比如端口 9000 的另一个服务):

1. 编辑 `/home/youfu/.cloudflared/config.yml`:

```yaml
tunnel: <TUNNEL_ID>
credentials-file: /home/youfu/.cloudflared/<TUNNEL_ID>.json
ingress:
  - hostname: kb.sxy.homes
    service: http://127.0.0.1:8000
  - hostname: docs.sxy.homes      # 新加
    service: http://127.0.0.1:9000
  - service: http_status:404
```

2. CF 后台 Zero Trust → Tunnels → Public Hostname → Add → 填 `docs` / `sxy.homes` / `http://localhost:9000`
3. `sudo systemctl restart cloudflared`

## 安全说明

### 默认已经做的

- ✅ youfu-known 监听 `127.0.0.1:8000`, 局域网/公网无法直接访问
- ✅ 所有流量强制走 Cloudflare Tunnel (HTTPS)
- ✅ Cloudflare Tunnel 自动屏蔽常见扫描/攻击 (内置 WAF)

### 没做的 (后续可加)

- ❌ **Cloudflare Access** (登录页): 任何拿到 URL 的人都能访问。如果需要密码保护, 在 Zero Trust → Access → Applications 加策略
- ❌ **速率限制**: 大量请求可能扣 CF 免费套餐额度

### 如果你只想要自己用

CF 后台 → Zero Trust → Access → Add Application:
- Application name: kb
- Domain: `kb.sxy.homes`
- Policy: Allow → Email = `your@email.com`

这样只有你的邮箱登录后能访问, 别人拿到 URL 也进不去。

## 故障排查

### 外网 curl 返回 502

```bash
ssh pi "sudo journalctl -u cloudflared -n 50"
# 看是否有 "connection refused" 等错误
```

### Pi 上 youfu-known 启动了但 tunnel 看不到

```bash
# Pi 内网自测
ssh pi "curl http://127.0.0.1:8000/api/health"
# 应返回 ok

# 看 tunnel 进程
ssh pi "ps aux | grep cloudflared | grep -v grep"
```

### DNS 解析问题

如果 `https://kb.sxy.homes` 解析不到 CF, 在 Cloudflare DNS 检查记录是否 Active。NS 切换可能要等 24-48 小时。

## 卸载

```bash
bash scripts/cloudflare/uninstall_tunnel.sh
```

会:
1. 删除 CF DNS 记录
2. 删除 CF Tunnel
3. Pi 上卸载 cloudflared systemd service
4. youfu-known 改回监听 0.0.0.0 (局域网可用)