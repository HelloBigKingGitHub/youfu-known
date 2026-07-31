#!/usr/bin/env bash
# scripts/install_nginx_pi.sh
# 在 Pi 上手动安装 nginx, 配置 youfu-known 反代
#
# 用途: 把 cloudflared 的 8001/8002 -> FastAPI 8000 / admin-web 5174
#
# 为什么是手动: 装 nginx + 写 /etc/nginx/* + 启 systemd 服务都要 sudo,
# Agent 跑不动。这个脚本设计成"Pi 上一行 sudo bash 跑完"。
#
# 用法 (Pi 上):
#   sudo bash scripts/install_nginx_pi.sh
#
# 它做什么:
#   1. apt install nginx (若无)
#   2. 拷 nginx/youfu-known.conf -> /etc/nginx/sites-available/
#   3. 建 symlink -> /etc/nginx/sites-enabled/
#   4. nginx -t 验证配置
#   5. systemctl enable --now nginx
#   6. 三个端到端 smoke 测 (8001 / 8002 / 8002/api/)
#
# 不做:
#   * 不改 /etc/cloudflared/config.yml (那个脚本在 scripts/cloudflare/)
#   * 不启 serve_admin_web / youfu-known.service (那是 deploy_pi.sh 的活)

set -o pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CONF_SRC="${PROJECT_ROOT}/nginx/youfu-known.conf"
CONF_NAME="youfu-known"
NGINX_AVAILABLE="/etc/nginx/sites-available/${CONF_NAME}.conf"
NGINX_ENABLED="/etc/nginx/sites-enabled/${CONF_NAME}.conf"

# -------- 0. 校验 root --------
if [[ "${EUID}" -ne 0 ]]; then
    echo "❌ 必须 sudo 跑 (apt install / 写 /etc/nginx/* / systemctl)"
    echo "   用法: sudo bash $0"
    exit 1
fi

# -------- 0b. 校验源文件存在 --------
if [[ ! -f "${CONF_SRC}" ]]; then
    echo "❌ 找不到源配置: ${CONF_SRC}"
    echo "   请在项目根目录跑这个脚本, 或者确认 nginx/youfu-known.conf 存在"
    exit 1
fi

step() { printf "\n\033[1;34m== %s ==\033[0m\n" "$*"; }
ok()   { printf "\033[1;32m✔ %s\033[0m\n" "$*"; }
warn() { printf "\033[1;33m⚠ %s\033[0m\n" "$*"; }
die()  { printf "\033[1;31m✘ %s\033[0m\n" "$*"; exit 1; }

# -------- 1. 装 nginx --------
step "1/5 装 nginx (apt)"
if command -v nginx >/dev/null 2>&1; then
    ok "nginx 已装: $(nginx -v 2>&1 | head -1)"
else
    apt-get update -y
    apt-get install -y nginx
    ok "nginx 已装"
fi

# -------- 2. 关掉 nginx 默认 site --------
step "2/5 关掉 nginx 默认 site (避免 80 端口冲突)"
if [[ -e /etc/nginx/sites-enabled/default ]]; then
    rm -f /etc/nginx/sites-enabled/default
    ok "移除 sites-enabled/default"
else
    ok "无默认 site, 跳过"
fi

# -------- 3. 拷配置 --------
step "3/5 部署 ${CONF_NAME}.conf"
install -m 644 "${CONF_SRC}" "${NGINX_AVAILABLE}"
ok "写 ${NGINX_AVAILABLE}"

# 建/更新 symlink (force 覆盖)
ln -sf "${NGINX_AVAILABLE}" "${NGINX_ENABLED}"
ok "链接 ${NGINX_ENABLED}"

# -------- 4. 验证配置 + 启服务 --------
step "4/5 nginx -t 验证配置"
nginx -t || die "nginx -t 失败, 请看上面输出"
ok "配置 OK"

systemctl enable nginx
systemctl restart nginx
sleep 1
if systemctl is-active --quiet nginx; then
    ok "nginx 已在跑"
else
    die "nginx 没起来, journalctl -u nginx -n 30"
fi

# -------- 5. Smoke 测试 --------
step "5/5 反代 smoke 测"
sleep 1

probe() {
    local url="$1"
    local expect="$2"
    local code
    code=$(curl -fsS -m 5 -o /dev/null -w "%{http_code}" "${url}" 2>/dev/null || echo "000")
    if [[ "${code}" == "${expect}" ]]; then
        ok "GET ${url} -> ${code}"
    else
        warn "GET ${url} -> ${code} (期望 ${expect}, 这可能意味着后端没启, 或 admin-web http.server 没启, 不影响 nginx 本身)"
    fi
}

probe "http://127.0.0.1:8001/api/health" "200"
probe "http://127.0.0.1:8002/" "200"
probe "http://127.0.0.1:8002/api/health" "200"

# -------- 完成 --------
echo
printf "\033[1;32m========================================\033[0m\n"
ok "nginx 反代装好了"
echo
echo "下一步 (Pi 上手动):"
echo "  1. 确认 cloudflared ingress 改成:"
echo "       - hostname: kb.sxy.homes    -> http://127.0.0.1:8001"
echo "       - hostname: admin.sxy.homes -> http://127.0.0.1:8002"
echo "     sudo systemctl restart cloudflared"
echo "  2. 确认 serve_admin_web.service 在跑 (admin-web/dist 静态 :5174):"
echo "     sudo systemctl status serve_admin_web"
echo "  3. 确认 youfu-known.service 在跑 (FastAPI :8000):"
echo "     sudo systemctl status youfu-known"
echo "  4. 浏览器开 https://admin.sxy.homes -> 应看到管理后台登录页"
echo
echo "诊断:"
echo "  sudo nginx -t                     # 配置检查"
echo "  sudo journalctl -u nginx -f       # 日志"
echo "  ss -tlnp | grep -E ':(8001|8002)' # 端口监听"
echo
printf "\033[1;32m========================================\033[0m\n"