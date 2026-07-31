# 内网穿透部署文档 (Cloudflare Tunnel + nginx)

> **项目**: youfu-known
> **目标**: 把 Pi 上的服务通过 Cloudflare Tunnel 暴露成 `https://kb.sxy.homes`
> 和 `https://admin.sxy.homes`, 由 nginx 做 80/443 后面的反向代理
> **难度**: 中等 — 需要 Cloudflare 账号 + 一个域名 + Pi 上 systemd 基础 + nginx 基础
> **预计时间**: 30-60 分钟

## 1. 方案选择

| 方案 | 优点 | 缺点 | 选? |
|---|---|---|---|
| **Cloudflare Tunnel + nginx** | 免费 / 隐藏 IP / 自动 HTTPS / 不需要公网 IP / nginx 拆分多 SPA | 需要 Cloudflare 账号 / 域名 | ✅ |
| frp | 老牌 / 国内友好 | 需要公网 VPS / 自己维护服务端 | |
| ngrok | 简单 | 免费版不稳定 / 不适合生产 | |
| Tailscale | 极简 | 用户需要装客户端 | |

**我们选 Cloudflare Tunnel + nginx**。

**为什么加 nginx?** 之前是 cloudflared → FastAPI 单进程, 用 Host 头分
发两个 SPA (kb + admin)。这种"单进程 host 头分发"模式在新场景下不
够干净:

1. admin SPA (`admin-web/dist`) 跟 FastAPI 完全没关系, 它就是个静态
   包, 不该塞在 Python 进程里;
2. 前后端分离是事实, admin SPA 跟 API 已经分两个 origin (cookie 用
   `Domain=.sxy.homes` 串联), 加 nginx 把它们的"拆分"显式化, 排错
   比靠 Host 头分发清晰得多;
3. 浏览器/调试工具对"同源不同端口"的拓扑有标准的解读 (CORS preflight、
   SameSite=None 行为), nginx 把这件事做成配置文件 + 可观察的监听
   端口, 比"改 Python 代码换 dispatcher"更稳妥。

所以现在的拓扑是:

```
   公网浏览器
       │  (HTTPS, Cloudflare 终止 TLS)
       ▼
   cloudflared (127.0.0.1)        ← Pi 上
       │
       │  hostname: kb.sxy.homes       → http://127.0.0.1:8001
       │  hostname: admin.sxy.homes    → http://127.0.0.1:8002
       │
       ▼
   nginx (sites-available/youfu-known.conf)
       │
       │  listen :8001
       │    → proxy_pass http://127.0.0.1:8000   (FastAPI, SPA + API)
       │
       │  listen :8002
       │    location /api/  → proxy_pass http://127.0.0.1:8000   (FastAPI)
       │    location /      → proxy_pass http://127.0.0.1:5174   (admin-web)
       │
       ▼
   127.0.0.1:8000 (uvicorn)        127.0.0.1:5174 (python -m http.server)
   web/dist + /api/*                 admin-web/dist (静态)
```

所有内部端口都绑 127.0.0.1, 公网必须经 Cloudflare Tunnel 进来。

## 2. 前置条件

**账号 + 域名**:
- 1 个 Cloudflare 账号 (https://dash.cloudflare.com/sign-up)
- 1 个域名 (如 `example.com`), NS 记录已指向 Cloudflare

**树莓派**:
- 已装好 OS (Raspberry Pi OS Lite 64-bit)
- 能 SSH 登录 (默认端口 22, 用户 `youfu`, 我们用密钥)
- Pi 有互联网出站 (Cloudflare Tunnel 是出站连接, 不需要入站)
- 已装好 youfu-known 后端 + admin-web/dist (见 `scripts/install.sh`)

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
cloudflared tunnel route dns youfu-tunnel admin.sxy.homes
# 期望: Added CNAME kb.sxy.homes / admin.sxy.homes pointing to 4ea6f88d-...cfargotunnel.com
```

### 方式 B: Quick Tunnel (临时, 每次 token 变)

```bash
# Pi 上跑 (会输出临时域名, 没用, 仅测试)
cloudflared tunnel --url http://127.0.0.1:8001
# 输出: https://random-words.trycloudflare.com (临时, 重启丢)
```

**生产用方式 A**。

## 5. 配置 ingress (路由规则)

### 5.1 Pi 上写 `/etc/cloudflared/config.yml`

注意这里 ingress 指向 **nginx** 的 8001 / 8002, 不是直连 FastAPI:

```yaml
tunnel: 4ea6f88d-591b-4925-a5fa-f0764c51e3fb
credentials-file: /etc/cloudflared/4ea6f88d-591b-4925-a5fa-f0764c51e3fb.json

ingress:
  # 主域名 → nginx :8001 (KB SPA + API, 单 origin)
  - hostname: kb.sxy.homes
    service: http://127.0.0.1:8001
  # 后台域名 → nginx :8002 (admin SPA + /api/* 反代到 FastAPI)
  - hostname: admin.sxy.homes
    service: http://127.0.0.1:8002
  # 必须有兜底
  - service: http_status:404
```

**关键点**:
- `tunnel: <UUID>` — 命名 tunnel 的 UUID
- `credentials-file` — JSON 凭证路径
- `ingress` — 顺序匹配, 第一个命中为准; 最后必须有兜底
- `service: http://127.0.0.1:8001` / `:8002` — Pi 上的 nginx 监听端口
  (不要直连 :8000, 那会让 admin SPA 没 nginx 反代, CORS 仍能工作但
  没 "前后端分离" 的清晰分层)

### 5.2 测试配置

```bash
cloudflared tunnel --config /etc/cloudflared/config.yml youfu-tunnel
# 看日志: 注册 + 建连接 + 报 200
# 期望日志:
#   INF Connection established connIndex=0 ...
#   INF Connection established connIndex=1 ...
```

Ctrl+C 退出, 上 systemd。

## 6. 安装并配置 nginx

nginx 在项目里之前没用过, 这是新加的层。配置和安装脚本都已放进仓库:

```
nginx/youfu-known.conf                # 反代配置
scripts/install_nginx_pi.sh           # Pi 上一键装 (要 sudo)
```

### 6.1 Pi 上一键装 nginx

```bash
# Pi 上, 项目根目录
sudo bash scripts/install_nginx_pi.sh
```

这个脚本会自动:
1. `apt install -y nginx` (若没装)
2. 关掉 nginx 默认 site (避免 80 端口冲突)
3. `cp nginx/youfu-known.conf /etc/nginx/sites-available/`
4. `ln -s` 到 `sites-enabled/`
5. `nginx -t` 验证配置
6. `systemctl enable --now nginx`
7. 三个 smoke 测 (8001, 8002, 8002/api/health)

### 6.2 手工 step (跟脚本做一样的事)

```bash
sudo apt install -y nginx
sudo cp nginx/youfu-known.conf /etc/nginx/sites-available/youfu-known.conf
sudo ln -s /etc/nginx/sites-available/youfu-known.conf /etc/nginx/sites-enabled/youfu-known.conf
sudo rm -f /etc/nginx/sites-enabled/default   # 关默认
sudo nginx -t
sudo systemctl enable nginx
sudo systemctl restart nginx
```

### 6.3 配置总览 (nginx/youfu-known.conf)

```nginx
upstream youfu_api  { server 127.0.0.1:8000; keepalive 8; }
upstream admin_web  { server 127.0.0.1:5174; keepalive 4; }

# kb.sxy.homes: 全打到 FastAPI
server {
    listen 127.0.0.1:8001;
    server_name _;
    client_max_body_size 200m;
    location / { proxy_pass http://youfu_api; ... }
}

# admin.sxy.homes: /api/* 打 FastAPI, 其它打 admin-web
server {
    listen 127.0.0.1:8002;
    server_name admin.sxy.homes;
    client_max_body_size 50m;
    location /api/ { proxy_pass http://youfu_api; ... }
    location /     { proxy_pass http://admin_web; ... }
}
```

### 6.4 验证 nginx

```bash
# 配置语法
sudo nginx -t
# 期望: nginx: configuration file ... test is successful

# 监听端口
ss -tlnp | grep -E ':(8001|8002) '
# 期望: 看到 nginx 监听 127.0.0.1:8001 和 127.0.0.1:8002

# 后端可达 (FastAPI :8000 起着, serve_admin_web :5174 起着)
curl -I http://127.0.0.1:8001/api/health
curl -I http://127.0.0.1:8002/             # 看到 admin SPA index.html
curl -I http://127.0.0.1:8002/api/health   # 透过 nginx 打到 FastAPI
```

## 7. systemd 开机自启

### 7.1 Pi 上的三个 unit

```
youfu-known.service      # FastAPI :8000       (deploy_pi.sh 装)
serve_admin_web.service  # python -m http.server :5174 (admin-web/dist)
nginx.service            # nginx :8001/:8002   (install_nginx_pi.sh 装)
cloudflared.service      # Cloudflare Tunnel   (cloudflare setup_tunnel.sh 装)
```

确认都启了:

```bash
systemctl is-active youfu-known serve_admin_web nginx cloudflared
# 期望: 4 个都是 active
```

### 7.2 cloudflared systemd unit

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

### 7.3 启动 + 自启

```bash
sudo systemctl daemon-reload
sudo systemctl enable youfu-known serve_admin_web nginx cloudflared
sudo systemctl start  youfu-known serve_admin_web nginx cloudflared

# 逐个查
sudo systemctl status youfu-known --no-pager -l | head -8
sudo systemctl status serve_admin_web --no-pager -l | head -8
sudo systemctl status nginx --no-pager -l | head -8
sudo systemctl status cloudflared --no-pager -l | head -8
```

### 7.4 (可选) 自动更新 cloudflared

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

## 8. 验证部署

### 8.1 看进程

```bash
ps aux | grep -E "cloudflared|nginx|uvicorn|http.server" | grep -v grep
# 期望: cloudflared, nginx (master + worker), uvicorn, http.server 都在跑
```

### 8.2 看日志

```bash
sudo journalctl -u cloudflared -f
sudo journalctl -u nginx       -f
sudo journalctl -u youfu-known -f
# 期望:
#   INF Starting tunnel ...
#   INF Connection established connIndex=0 ...
```

### 8.3 端到端测

```bash
# 本机:
curl -I https://kb.sxy.homes
# 期望: HTTP/2 200 + cf-cache-status: DYNAMIC

curl -s https://kb.sxy.homes/api/health
# 期望: {"code":0,"data":{"status":"ok"}}

curl -I https://admin.sxy.homes
# 期望: HTTP/2 200, Content-Type: text/html (admin SPA)

curl -s https://admin.sxy.homes/api/health
# 期望: {"code":0,"data":{"status":"ok"}}
# (admin SPA 透过 nginx :8002/api/ 反代到 FastAPI)
```

### 8.4 浏览器访问

打开 https://kb.sxy.homes → 看到 youfu-known 登录页。
打开 https://admin.sxy.homes → 看到管理后台登录页。

跨子域登录: 在 kb.sxy.homes 登录后, 浏览器应该自动把 cookie (`Domain=.sxy.homes`)
带到 admin.sxy.homes; 直接开 admin.sxy.homes 不需要再登录。

## 9. 故障排查

### 9.1 tunnel 起不来

```bash
sudo journalctl -u cloudflared --no-pager -n 50
# 常见错误:
# "Tunnel not found" → credentials-file 路径错
# "Failed to load" → config.yml 格式错
# "Permission denied" → JSON credentials 文件权限 600
```

### 9.2 域名不通

```bash
dig kb.sxy.homes +short
# 期望: <TUNNEL_ID>.cfargotunnel.com

dig CNAME admin.sxy.homes +short
# 期望: <TUNNEL_ID>.cfargotunnel.com

# 没指过来 → cloudflared tunnel route dns 没跑, 或 DNS 缓存
```

### 9.3 后端 502

```bash
# tunnel 起来了但 nginx 拿不到后端:
ss -tlnp | grep -E ':(8000|5174) '
# 没看到 → 相应的 service 没起:
sudo systemctl status youfu-known
sudo systemctl status serve_admin_web

# 看到 8000 / 5174 在听, 但 nginx 还是 502:
sudo nginx -t       # 配置错?
sudo journalctl -u nginx -n 50 --no-pager
```

### 9.4 admin.sxy.homes CORS 报错

```bash
# 浏览器 DevTools Console: "CORS policy: ... Origin https://admin.sxy.homes is not allowed"
# 检查 CORS allowlist:
grep -n ADMIN_CORS_ORIGINS app/api/__init__.py
# 必须有 "https://admin.sxy.homes"
```

### 9.5 admin SPA 拿不到 cookie

```bash
# 登录后开 admin.sxy.homes 还是 401 → cookie 没跨子域带过来
# 1. 检查 cookie Domain 属性:
grep -n "cookie_domain\|sxy.homes" app/api/auth.py
# 必须 .sxy.homes (Secure=True 时才设)

# 2. 检查 nginx 没把 cookie 路径 strip 掉:
curl -v -X POST https://kb.sxy.homes/api/auth/login \
    -H "Content-Type: application/json" \
    -d '{"username":"...","password":"..."}' \
    2>&1 | grep -i "set-cookie"
# 期望: Set-Cookie: session_token=...; Domain=.sxy.homes; Secure; SameSite=None
```

### 9.6 HSTS 缓存问题

```bash
# 浏览器记得之前的 502, 清缓存:
# Chrome: DevTools → Application → Clear storage
# 或 curl: curl -k https://kb.sxy.homes
```

## 10. 安全配置

### 10.1 Cloudflare Access (可选, 后台域名用)

如果想 admin.sxy.homes 加 Cloudflare Access 邮箱认证:

1. Cloudflare Zero Trust dashboard → Access → Applications
2. 加 Self-hosted: `admin.sxy.homes`
3. Policy: `emails end with @yourcompany.com`

这样后端**不需认证**, Cloudflare 拦着。

### 10.2 Rate Limiting

Cloudflare dashboard → Security → WAF → Rate limit rules:
- 10 requests / 10s / IP (防滥用)

### 10.3 Bot Fight Mode

Cloudflare dashboard → Security → Bots:
- 开启 "Bot Fight Mode" (免费)

### 10.4 nginx + cloudflared 都没暴露公网

| 进程 | 监听 | 公网可达? |
|---|---|---|
| cloudflared | 出站 (HTTPS 443) | ✅ 主动建连 |
| nginx | 127.0.0.1:8001, :8002 | ❌ 只本机 |
| uvicorn | 127.0.0.1:8000 | ❌ 只本机 |
| http.server | 127.0.0.1:5174 | ❌ 只本机 |

公网 → 必须经 cloudflared (CF 终止 TLS) → nginx → 后端。任意一层
直接暴露在 0.0.0.0 都是配置 bug, 应立即修。

## 11. 完整命令清单 (一键脚本)

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
cloudflared tunnel route dns youfu-tunnel admin.sxy.homes

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

# 上传 config.yml (重点: ingress 指 nginx 的端口, 不是 FastAPI)
TUNNEL_ID=$(cloudflared tunnel info youfu-tunnel | grep -oP '[0-9a-f-]{36}' | head -1)
cat > /tmp/config.yml <<EOF
tunnel: ${TUNNEL_ID}
credentials-file: /etc/cloudflared/credentials.json

ingress:
  - hostname: kb.sxy.homes
    service: http://127.0.0.1:8001
  - hostname: admin.sxy.homes
    service: http://127.0.0.1:8002
  - service: http_status:404
EOF
scp /tmp/config.yml $PI_HOST:/tmp/
ssh $PI_HOST "sudo mv /tmp/config.yml /etc/cloudflared/config.yml"

echo "== Pi: 装 nginx =="
ssh $PI_HOST "cd /home/youfu/youfu-known && sudo bash scripts/install_nginx_pi.sh"

echo "== Pi: 装 systemd service (cloudflared) =="
ssh $PI_HOST "sudo cloudflared service install && \
sudo systemctl daemon-reload && \
sudo systemctl enable cloudflared youfu-known serve_admin_web nginx && \
sudo systemctl restart cloudflared"

echo "== 验证 =="
sleep 5
curl -I https://kb.sxy.homes
curl -I https://admin.sxy.homes
echo "== 完成 =="
```

## 12. 后续

- **多域名**: 在 cloudflared config.yml ingress 加多行, 每行一个 hostname → nginx 端口
- **多后端**: nginx sites-available 加 server block, 听不同端口
- **负载均衡**: Cloudflare dashboard → Traffic → Load Balancers
- **健康检查**: Cloudflare dashboard → Traffic → Health Checks

## 13. 常见问题 FAQ

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
nginx 透传时保留 `X-Real-IP` / `X-Forwarded-For`, 不要 strip.

**Q: 为什么 admin SPA 不直接放 FastAPI 里?**
A: 现在是"前后端分离"架构, admin SPA 是独立 Vite 构建产物, 跟 FastAPI
是不同技术栈, 静态文件让 python -m http.server 服务, nginx 反代,
清晰且部署独立. 浏览器对跨子域+跨端口的 API 调用有标准 CORS 处理
(我们 allowlist + SameSite=None cookie + Domain=.sxy.homes 都配齐了).

**Q: 升级 Cloudflare Tunnel 版本?**
A: `sudo apt upgrade cloudflared` 或启 cloudflared-update.timer.

**Q: 升级 nginx 配置?**
A: 编辑项目里的 `nginx/youfu-known.conf`, 推到 Pi,
`sudo cp nginx/youfu-known.conf /etc/nginx/sites-available/ && sudo nginx -t && sudo systemctl reload nginx`.

**Q: 备份配置?**
A: `/etc/cloudflared/config.yml` + `credentials.json` + `/etc/nginx/sites-available/youfu-known.conf` + `nginx/youfu-known.conf` (仓库) 都要备份.

## 14. 参考链接

- 官方文档: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/
- systemd 部署: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/deploy-tunnels/
- FAQ: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/faq/
- nginx 反代文档: https://nginx.org/en/docs/http/ngx_http_proxy_module.html

---

**最后更新**: 2026-07-31
**维护者**: youfu-known 团队
**测试环境**: Raspberry Pi 4 (aarch64), Debian 12 (bookworm), cloudflared 2026.7.2, nginx 1.22.x
**适用版本**: youfu-known v0.2.x (前后端分离架构)