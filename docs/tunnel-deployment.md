# 内网穿透部署文档 (Cloudflare Tunnel)

> **项目**: youfu-known  
> **目标**: 把 Pi 上的服务 (端口 8000) 通过 Cloudflare Tunnel 暴露成 `https://kb.sxy.homes`  
> **难度**: 中等 — 需要 Cloudflare 账号 + 一个域名 + Pi 上 systemd 基础  
> **预计时间**: 30-60 分钟  

## 1. 方案选择

| 方案 | 优点 | 缺点 | 选? |
|---|---|---|---|
| **Cloudflare Tunnel** | 免费 / 隐藏 IP / 自动 HTTPS / 不需要公网 IP | 需要 Cloudflare 账号 / 域名 | ✅ |
| frp | 老牌 / 国内友好 | 需要公网 VPS / 自己维护服务端 | |
| ngrok | 简单 | 免费版不稳定 / 不适合生产 | |
| Tailscale | 极简 | 用户需要装客户端 | |

**我们选 Cloudflare Tunnel** (你不需要公网 IP, 只要域名 NS 指到 Cloudflare)。

## 2. 前置条件

**账号 + 域名**:
- 1 个 Cloudflare 账号 (https://dash.cloudflare.com/sign-up)
- 1 个域名 (如 `example.com`), NS 记录已指向 Cloudflare

**树莓派**:
- 已装好 OS (Raspberry Pi OS Lite 64-bit)
- 能 SSH 登录 (默认端口 22, 用户 `youfu`, 我们用密钥)
- Pi 有互联网出站 (Cloudflare Tunnel 是出站连接, 不需要入站)

**本地**:
- 任何 SSH 客户端 + curl

## 3. 安装 cloudflared

### 3.1 Pi 上装 cloudflared

```bash
# 一键安装脚本 (官方)
curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg \
  | sudo tee /usr/share/keyrings/cloudflare-main.gpg >/dev/null

echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared $(lsb_release -cs) main" \
  | sudo tee /etc/apt/sources.list.d/cloudflared.list

sudo apt update && sudo apt install -y cloudflared

# 验证
cloudflared --version
# 期望: cloudflared version 2026.7.2 或更新
```

### 3.2 本机装 cloudflared (可选, 用于登录)

**Mac**:
```bash
brew install cloudflared
```

**Linux/WSL**: 同上 apt

## 4. 登录 Cloudflare 创建 Tunnel

**两种方式** — 选一种:

### 方式 A: 命名 Tunnel (推荐, 可复用)

```bash
# 4.1 本机登录 (会弹出浏览器授权)
cloudflared tunnel login
# 浏览器选域名, 给 token

# 4.2 创建命名 tunnel
cloudflared tunnel create youfu-tunnel
# 输出: Created tunnel youfu-tunnel with id 4ea6f88d-591b-4925-a5fa-f0764c51e3fb
# credentials-file: /home/youfu/.cloudflared/4ea6f88d-591b-4925-a5fa-f0764c51e3fb.json

# 4.3 把 credentials JSON 拷到 Pi
# 本机:
scp ~/.cloudflared/4ea6f88d-*.json youfu@192.168.88.102:/tmp/
# Pi:
sudo mkdir -p /etc/cloudflared
sudo mv /tmp/4ea6f88d-*.json /etc/cloudflared/
sudo chown root:root /etc/cloudflared/4ea6f88d-*.json
sudo chmod 600 /etc/cloudflared/4ea6f88d-*.json

# 4.4 在 Cloudflare DNS 绑域名
# 本机 (或 Cloudflare 网页):
cloudflared tunnel route dns youfu-tunnel kb.sxy.homes
# 期望: Added CNAME kb.sxy.homes pointing to 4ea6f88d-591b-4925-a5fa-f0764c51e3fb.cfargotunnel.com
```

### 方式 B: Quick Tunnel (临时, 每次 token 变)

```bash
# Pi 上跑 (会输出临时域名, 没用, 仅测试)
cloudflared tunnel --url http://127.0.0.1:8000
# 输出: https://random-words.trycloudflare.com (临时, 重启丢)
```

**生产用方式 A**。

## 5. 配置 ingress (路由规则)

### 5.1 Pi 上写 `/etc/cloudflared/config.yml`

```yaml
tunnel: 4ea6f88d-591b-4925-a5fa-f0764c51e3fb
credentials-file: /etc/cloudflared/4ea6f88d-591b-4925-a5fa-f0764c51e3fb.json

ingress:
  # 主域名 → youfu-known 后端
  - hostname: kb.sxy.homes
    service: http://127.0.0.1:8000
  # 后台域名 (Phase 2 用)
  - hostname: admin.kb.sxy.homes
    service: http://127.0.0.1:8000
  # 必须有兜底
  - service: http_status:404
```

**关键点**:
- `tunnel: <UUID>` — 命名 tunnel 的 UUID
- `credentials-file` — JSON 凭证路径
- `ingress` — 顺序匹配, 第一个命中为准; 最后必须有兜底
- `service: http://127.0.0.1:8000` — Pi 上的后端 (你fu-known 8000 端口)

### 5.2 测试配置

```bash
cloudflared tunnel --config /etc/cloudflared/config.yml youfu-tunnel
# 看日志: 注册 + 建连接 + 报 200
# 期望日志:
#   INF Connection established connIndex=0 ...
#   INF Connection established connIndex=1 ...
```

Ctrl+C 退出, 上 systemd。

## 6. systemd 开机自启

### 6.1 安装 systemd unit

```bash
sudo cloudflared service install
# 自动创建 /etc/systemd/system/cloudflared.service
```

**生成的 service 文件** 应该是这样:

```ini
[Unit]
Description=Cloudflare Tunnel client
After=network-online.target
Wants=network-online.target

[Service]
TimeoutStartSec=15
Type=notify
ExecStart=/usr/bin/cloudflared --no-autoupdate tunnel run --token-file /etc/cloudflared/token
Restart=on-failure
RestartSec=5s

[Install]
WantedBy=multi-user.target
```

**⚠️ 注意**: `--token-file` 模式是老式 quick tunnel, 你需要改成 `--config` 模式:

```bash
sudo tee /etc/systemd/system/cloudflared.service >/dev/null <<'EOF'
[Unit]
Description=Cloudflare Tunnel client (named tunnel)
After=network-online.target
Wants=network-online.target

[Service]
Type=notify
ExecStart=/usr/bin/cloudflared --no-autoupdate --config /etc/cloudflared/config.yml run
Restart=on-failure
RestartSec=5s
TimeoutStartSec=15

[Install]
WantedBy=multi-user.target
EOF
```

### 6.2 启动 + 自启

```bash
sudo systemctl daemon-reload
sudo systemctl enable cloudflared
sudo systemctl start cloudflared
sudo systemctl status cloudflared
# 期望: Active: active (running)
```

### 6.3 (可选) 自动更新

```bash
# /etc/systemd/system/cloudflared-update.service
sudo tee /etc/systemd/system/cloudflared-update.service >/dev/null <<'EOF'
[Unit]
Description=Update cloudflared
After=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/bin/cloudflared update

[Install]
WantedBy=multi-user.target
EOF

# /etc/systemd/system/cloudflared-update.timer
sudo tee /etc/systemd/system/cloudflared-update.timer >/dev/null <<'EOF'
[Unit]
Description=Update cloudflared weekly

[Timer]
OnCalendar=weekly
Persistent=true

[Install]
WantedBy=timers.target
EOF

sudo systemctl enable cloudflared-update.timer
```

## 7. 验证部署

### 7.1 看进程

```bash
ps aux | grep cloudflared | grep -v grep
# 期望: root 跑 /usr/bin/cloudflared --config /etc/cloudflared/config.yml run
```

### 7.2 看日志

```bash
sudo journalctl -u cloudflared -f
# 期望:
#   INF Starting tunnel ...
#   INF Connection established connIndex=0 ...
```

### 7.3 测访问

```bash
# 本机:
curl -I https://kb.sxy.homes
# 期望: HTTP/2 200 + cf-cache-status: DYNAMIC

curl -s https://kb.sxy.homes/api/health
# 期望: {"code":0,"data":{"status":"ok"}}
```

### 7.4 浏览器访问

打开 https://kb.sxy.homes → 看到 youfu-known 登录页。

## 8. 故障排查

### 8.1 tunnel 起不来

```bash
# 看日志
sudo journalctl -u cloudflared --no-pager -n 50

# 常见错误:
# "Tunnel not found" → credentials-file 路径错
# "Failed to load" → config.yml 格式错
# "Permission denied" → JSON credentials 文件权限 600
```

### 8.2 域名不通

```bash
# 看 DNS
dig kb.sxy.homes +short
# 期望: 你fu-related.cloudflare-dns.com (类似 cfargotunnel)

# 或 dig CNAME
dig CNAME kb.sxy.homes +short

# 没指过来 → cloudflared tunnel route dns 没跑, 或 DNS 缓存
```

### 8.3 后端 502

```bash
# tunnel 起来了但后端没起:
ps aux | grep youfu-known | grep -v grep
# 没看到 → 你fu-known 没跑:
sudo systemctl status youfu-known
sudo systemctl restart youfu-known
```

### 8.4 HSTS 缓存问题

```bash
# 浏览器记得之前的 502, 清缓存:
# Chrome: DevTools → Application → Clear storage
# 或 curl: curl -k https://kb.sxy.homes
```

## 9. 安全配置

### 9.1 Cloudflare Access (可选, 后台域名用)

如果想 admin.kb.sxy.homes 加 Cloudflare Access 邮箱认证:

1. Cloudflare Zero Trust dashboard → Access → Applications
2. 加 Self-hosted: `admin.kb.sxy.homes`
3. Policy: `emails end with @yourcompany.com`

这样后端**不需认证**, Cloudflare 拦着。

### 9.2 Rate Limiting

Cloudflare dashboard → Security → WAF → Rate limit rules:
- 10 requests / 10s / IP (防滥用)

### 9.3 Bot Fight Mode

Cloudflare dashboard → Security → Bots:
- 开启 "Bot Fight Mode" (免费)

## 10. 完整命令清单 (一键脚本)

```bash
#!/bin/bash
# install_cloudflared.sh - 一键部署
set -e

PI_HOST="youfu@192.168.88.102"

# === 本机 ===
echo "== 本机: 登录 Cloudflare =="
cloudflared tunnel login

echo "== 本机: 创建 tunnel =="
cloudflared tunnel create youfu-tunnel

echo "== 本机: 绑定 DNS =="
cloudflared tunnel route dns youfu-tunnel kb.sxy.homes

echo "== 本机: 拷 credentials 到 Pi =="
scp ~/.cloudflared/$(cloudflared tunnel info youfu-tunnel | grep -oP '[0-9a-f-]{36}').json $PI_HOST:/tmp/

# === Pi ===
echo "== Pi: 装 cloudflared =="
ssh $PI_HOST "curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg | sudo tee /usr/share/keyrings/cloudflare-main.gpg >/dev/null && \
echo 'deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared bookworm main' | sudo tee /etc/apt/sources.list.d/cloudflared.list && \
sudo apt update && sudo apt install -y cloudflared"

echo "== Pi: 配 config.yml =="
ssh $PI_HOST "sudo mkdir -p /etc/cloudflared && \
sudo mv /tmp/*.json /etc/cloudflared/credentials.json && \
sudo chmod 600 /etc/cloudflared/credentials.json"

# 上传 config.yml
cat > /tmp/config.yml <<EOF
tunnel: $(cloudflared tunnel info youfu-tunnel | grep -oP '[0-9a-f-]{36}' | head -1)
credentials-file: /etc/cloudflared/credentials.json

ingress:
  - hostname: kb.sxy.homes
    service: http://127.0.0.1:8000
  - service: http_status:404
EOF
scp /tmp/config.yml $PI_HOST:/tmp/
ssh $PI_HOST "sudo mv /tmp/config.yml /etc/cloudflared/config.yml"

echo "== Pi: 装 systemd service =="
ssh $PI_HOST "sudo cloudflared service install && \
sudo systemctl daemon-reload && \
sudo systemctl enable cloudflared && \
sudo systemctl restart cloudflared"

echo "== 验证 =="
sleep 5
curl -I https://kb.sxy.homes
echo "== 完成 =="
```

## 11. 后续

- **多域名**: 在 config.yml ingress 加多行, 每行一个 hostname → 后端端口
- **多后端**: 不同 hostname → 不同端口 (如 kb.sxy.homes:8000, admin.kb.sxy.homes:8001)
- **负载均衡**: Cloudflare dashboard → Traffic → Load Balancers
- **健康检查**: Cloudflare dashboard → Traffic → Health Checks

## 12. 常见问题 FAQ

**Q: 域名需要付费吗?**  
A: 不需要. Cloudflare Tunnel 免费版支持无限域名.

**Q: Tunnel 流量有限制吗?**  
A: 免费版无限流量, 但有限速 (Enterprise 才无限速).

**Q: cloudflared 版本多久更新?**  
A: 每月. 启用 cloudflared-update.timer 自动更新.

**Q: 我可以同时用 SSH + Tunnel 吗?**  
A: 可以, 互不影响. SSH 走 22, Tunnel 走 443 出站.

**Q: 后端能拿到真实 IP 吗?**  
A: 可以. cloudflared 加 `cf-connecting-ip` header. 后端 FastAPI 用 `request.headers['cf-connecting-ip']`.

**Q: 升级 Cloudflare Tunnel 版本?**  
A: `sudo apt upgrade cloudflared` 或启 cloudflared-update.timer.

**Q: 备份配置?**  
A: `/etc/cloudflared/config.yml` + `credentials.json` 必须备份. 没了不能恢复 tunnel (要重新创建).

## 13. 参考链接

- 官方文档: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/
- systemd 部署: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/deploy-tunnels/
- FAQ: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/faq/

---

**最后更新**: 2026-07-30  
**维护者**: youfu-known 团队  
**测试环境**: Raspberry Pi 4 (aarch64), Debian 12 (bookworm), cloudflared 2026.7.2  
**适用版本**: youfu-known v0.1.x 及以上