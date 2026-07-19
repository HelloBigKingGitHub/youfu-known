#!/usr/bin/env bash
# scripts/cloudflare/setup_tunnel.sh
# 在 Pi 上装 cloudflared + 配置 + 启动 tunnel
#
# 前置:
#   1. Cloudflare 账号已添加域名 sxy.homes (NS 已改到 CF, 等待生效)
#   2. 创建了 API Token (权限: Tunnel:Edit, DNS:Edit, Account Settings:Read)
#   3. 你已经知道要绑定的子域名 (比如 kb.sxy.homes)
#
# 用法:
#   CF_TOKEN=<your_token> \
#   CF_ZONE=sxy.homes \
#   CF_SUBDOMAIN=kb \
#   bash scripts/cloudflare/setup_tunnel.sh

set -o pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../lib/common.sh"

CF_TOKEN="${CF_TOKEN:-}"
CF_ZONE="${CF_ZONE:-sxy.homes}"
CF_SUBDOMAIN="${CF_SUBDOMAIN:-kb}"
CF_TUNNEL_NAME="${CF_TUNNEL_NAME:-youfu-pi}"
PI_HOST="${PI_HOST:-}"
PI_USER="${PI_USER:-youfu}"
PI_PORT="${PI_PORT:-22}"
PI_SSH_KEY="${PI_SSH_KEY:-$HOME/.ssh/id_rsa_pi}"
PI_SUDO_PASS="${PI_SUDO_PASS:-}"

if [[ -z "${CF_TOKEN}" ]]; then
    read -r -s -p "[?] Cloudflare API Token: " CF_TOKEN
    echo
fi
[[ -z "${CF_TOKEN}" ]] && { log_error "缺 CF_TOKEN"; exit 1; }

if [[ -n "${PI_SUDO_PASS_FILE}" && -f "${PI_SUDO_PASS_FILE}" ]]; then
    PI_SUDO_PASS="$(cat "${PI_SUDO_PASS_FILE}")"
fi

if [[ -z "${PI_HOST}" ]]; then
    read -r -p "[?] Pi IP: " PI_HOST
fi

SSH_OPTS=( -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null
           -o ConnectTimeout=5 -p "${PI_PORT}" -i "${PI_SSH_KEY}" )

pi_run() { ssh "${SSH_OPTS[@]}" "${PI_USER}@${PI_HOST}" "$@"; }

# -------- 1. 通过 CF API 创建 Tunnel --------
log_step "1/6 在 Cloudflare 创建 Tunnel"

# 查 Account ID (zones 列表需要它)
ACCOUNT_ID=$(curl -fsS -H "Authorization: Bearer ${CF_TOKEN}" \
    "https://api.cloudflare.com/client/v4/accounts?per_page=1" \
    | python3 -c "import json,sys; print(json.load(sys.stdin)['result'][0]['id'])")
log_ok "Account ID: ${ACCOUNT_ID}"

# Zone ID
ZONE_ID=$(curl -fsS -H "Authorization: Bearer ${CF_TOKEN}" \
    "https://api.cloudflare.com/client/v4/zones?name=${CF_ZONE}" \
    | python3 -c "import json,sys; print(json.load(sys.stdin)['result'][0]['id'])")
log_ok "Zone ID: ${ZONE_ID} (${CF_ZONE})"

# Create tunnel
log_info "创建 tunnel: ${CF_TUNNEL_NAME}"
TUNNEL_RESP=$(curl -fsS -X POST \
    -H "Authorization: Bearer ${CF_TOKEN}" \
    -H "Content-Type: application/json" \
    "https://api.cloudflare.com/client/v4/accounts/${ACCOUNT_ID}/cfd_tunnel" \
    -d "{\"name\":\"${CF_TUNNEL_NAME}\",\"config_src\":\"cloudflare\"}")
TUNNEL_ID=$(echo "$TUNNEL_RESP" | python3 -c "import json,sys; print(json.load(sys.stdin)['result']['id'])")
TUNNEL_TOKEN=$(echo "$TUNNEL_RESP" | python3 -c "import json,sys; print(json.load(sys.stdin)['result']['token'])")
log_ok "Tunnel ID: ${TUNNEL_ID}"

# -------- 2. 加 DNS 记录 --------
log_step "2/6 加 DNS 记录: ${CF_SUBDOMAIN}.${CF_ZONE}"
curl -fsS -X POST \
    -H "Authorization: Bearer ${CF_TOKEN}" \
    -H "Content-Type: application/json" \
    "https://api.cloudflare.com/client/v4/zones/${ZONE_ID}/dns_records" \
    -d "{\"type\":\"CNAME\",\"name\":\"${CF_SUBDOMAIN}\",\"content\":\"${TUNNEL_ID}.cfargotunnel.com\",\"proxied\":true}" \
    > /dev/null
log_ok "DNS 已加 (CF 自动代理 + HTTPS)"

# -------- 3. Pi 上装 cloudflared --------
log_step "3/6 在 Pi 上装 cloudflared"
ARCH=$(pi_run "uname -m")
case "${ARCH}" in
    aarch64) CF_ARCH=arm64 ;;
    armv7l)  CF_ARCH=armhf ;;
    x86_64)  CF_ARCH=amd64 ;;
    *)
        log_error "未知架构: ${ARCH}"
        exit 1
        ;;
esac
log_info "Pi 架构: ${ARCH} → cloudflared-${CF_ARCH}.deb"

# 下载 .deb
TMP_DEB="/tmp/cloudflared.deb"
curl -fsSL -o "${TMP_DEB}" \
    "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${CF_ARCH}.deb"
log_ok "下载完成: $(ls -lh ${TMP_DEB} | awk '{print $5}')"

# 推 + 装
scp -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
    -i "${PI_SSH_KEY}" "${TMP_DEB}" "${PI_USER}@${PI_HOST}:/tmp/cloudflared.deb"

cat > /tmp/install_cf.exp <<EXP
set timeout 60
log_user 1
set password "$PI_SUDO_PASS"
spawn ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -i $PI_SSH_KEY $PI_USER@$PI_HOST "sudo -S dpkg -i /tmp/cloudflared.deb && which cloudflared && cloudflared --version"
expect {
    -re "assword.*" { send "\$password\r"; exp_continue }
    eof
}
EXP
expect /tmp/install_cf.exp
rm -f /tmp/install_cf.exp

# -------- 4. Pi 上写 tunnel credentials + config --------
log_step "4/6 Pi 上配置 tunnel"

# 推 tunnel token 文件 (CF 用 JSON 格式存 ~/.cloudflared/<TUNNEL_ID>.json)
mkdir -p /tmp/cf-cred
cat > "/tmp/cf-cred/${TUNNEL_ID}.json" <<EOF
{
  "AccountTag": "${ACCOUNT_ID}",
  "TunnelSecret": "$(echo $TUNNEL_TOKEN | cut -d. -f2 | base64 -d 2>/dev/null || echo placeholder)",
  "TunnelID": "${TUNNEL_ID}"
}
EOF
# 实际 token 是 base64 + . 格式, 需要 cloudflared 自己 decode
# 所以直接传完整 token 字符串让 cloudflared service 用
echo "${TUNNEL_TOKEN}" > /tmp/cf-cred/token.txt

scp -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
    -i "${PI_SSH_KEY}" /tmp/cf-cred/token.txt \
    "${PI_USER}@${PI_HOST}:/tmp/cf-token.txt"

# 在 Pi 上写 config.yml
cat > /tmp/cf-config.yml <<EOF
tunnel: ${TUNNEL_ID}
credentials-file: /home/${PI_USER}/.cloudflared/${TUNNEL_ID}.json
ingress:
  - hostname: ${CF_SUBDOMAIN}.${CF_ZONE}
    service: http://127.0.0.1:8000
  - service: http_status:404
EOF
scp -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
    -i "${PI_SSH_KEY}" /tmp/cf-config.yml \
    "${PI_USER}@${PI_HOST}:/tmp/cf-config.yml"

# Pi 上: 拷 credentials + 装 systemd service
cat > /tmp/setup_cf.exp <<EXP
set timeout 30
log_user 1
set password "$PI_SUDO_PASS"
spawn ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -i $PI_SSH_KEY $PI_USER@$PI_HOST
expect {
    -re "assword.*" { send "\$password\r" }
}
send "mkdir -p ~/.cloudflared && cp /tmp/cf-config.yml ~/.cloudflared/config.yml && cloudflared service install && sudo -S systemctl enable cloudflared && sudo -S cp /tmp/cf-token.txt /etc/cloudflared/ && sudo -S systemctl restart cloudflared\r"
expect -re "\[sudo\] password.*" { send "\$password\r" }
expect -re "\\\$ "
send "sleep 3 && sudo -S systemctl status cloudflared --no-pager -l | head -8\r"
expect -re "\[sudo\] password.*" { send "\$password\r" }
expect -re "\\\$ "
send "sudo -S journalctl -u cloudflared -n 20 --no-pager | tail -10\r"
expect -re "\[sudo\] password.*" { send "\$password\r" }
expect -re "\\\$ "
send "exit\r"
expect eof
EXP
expect /tmp/setup_cf.exp
rm -f /tmp/setup_cf.exp

# -------- 5. 验证 --------
log_step "5/6 验证 tunnel 状态"
sleep 5
HEALTH=$(curl -fsS -m 10 -o /dev/null -w "%{http_code}" "https://${CF_SUBDOMAIN}.${CF_ZONE}/api/health" 2>&1 || echo "000")
if [[ "${HEALTH}" == "200" ]]; then
    log_ok "🎉 外网访问通了: https://${CF_SUBDOMAIN}.${CF_ZONE}/api/health"
else
    log_warn "外网还没通 (HTTP ${HEALTH}), 检查 cloudflared 日志"
    log_info "ssh ${PI_USER}@${PI_HOST} 'sudo journalctl -u cloudflared -n 50'"
fi

# -------- 6. 锁服务 (绑 127.0.0.1) --------
log_step "6/6 锁定 youfu-known 为 127.0.0.1 (公网无法直连, 必须走 tunnel)"
bash "${SCRIPT_DIR}/../lock_down_service.sh" \
    PI_HOST="${PI_HOST}" PI_USER="${PI_USER}" \
    PI_SSH_KEY="${PI_SSH_KEY}" PI_SUDO_PASS="${PI_SUDO_PASS}" || true

echo
hr "-" 60
log_ok "Cloudflare Tunnel 配置完成!"
echo
log_info "外网访问: https://${CF_SUBDOMAIN}.${CF_ZONE}"
log_info "API:     https://${CF_SUBDOMAIN}.${CF_ZONE}/api/health"
echo
log_info "Tunnel ID: ${TUNNEL_ID}"
log_info "管理面板: https://one.dash.cloudflare.com/ → Zero Trust → Networks → Tunnels"