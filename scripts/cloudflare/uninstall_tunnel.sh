#!/usr/bin/env bash
# scripts/cloudflare/uninstall_tunnel.sh
# 卸载 cloudflared + tunnel + DNS 记录 + 恢复 youfu-known 监听 0.0.0.0

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

if [[ -n "${PI_SUDO_PASS_FILE}" && -f "${PI_SUDO_PASS_FILE}" ]]; then
    PI_SUDO_PASS="$(cat "${PI_SUDO_PASS_FILE}")"
fi

if [[ -z "${CF_TOKEN}" ]]; then
    read -r -s -p "[?] CF Token: " CF_TOKEN
    echo
fi
if [[ -z "${PI_HOST}" ]]; then
    read -r -p "[?] Pi IP: " PI_HOST
fi

log_warn "这会删除 CF Tunnel + DNS 记录 + 卸载 cloudflared + 恢复 youfu-known 监听 0.0.0.0"
read -r -p "[?] 确认卸载? [y/N] " CONFIRM
[[ ! "${CONFIRM}" =~ ^[Yy]$ ]] && { log_info "取消"; exit 0; }

# 1. 查 tunnel ID (按名字)
ACCOUNT_ID=$(curl -fsS -H "Authorization: Bearer ${CF_TOKEN}" \
    "https://api.cloudflare.com/client/v4/accounts?per_page=1" \
    | python3 -c "import json,sys; print(json.load(sys.stdin)['result'][0]['id'])")
ZONE_ID=$(curl -fsS -H "Authorization: Bearer ${CF_TOKEN}" \
    "https://api.cloudflare.com/client/v4/zones?name=${CF_ZONE}" \
    | python3 -c "import json,sys; print(json.load(sys.stdin)['result'][0]['id'])")

TUNNEL_ID=$(curl -fsS -H "Authorization: Bearer ${CF_TOKEN}" \
    "https://api.cloudflare.com/client/v4/accounts/${ACCOUNT_ID}/cfd_tunnel?name=${CF_TUNNEL_NAME}" \
    | python3 -c "import json,sys; rs=json.load(sys.stdin)['result']; print(rs[0]['id'] if rs else '')")
if [[ -z "${TUNNEL_ID}" ]]; then
    log_warn "找不到 tunnel ${CF_TUNNEL_NAME}, 跳过 CF 端清理"
else
    log_info "删除 tunnel ${TUNNEL_ID}"
    curl -fsS -X DELETE -H "Authorization: Bearer ${CF_TOKEN}" \
        "https://api.cloudflare.com/client/v4/accounts/${ACCOUNT_ID}/cfd_tunnel/${TUNNEL_ID}" \
        > /dev/null && log_ok "tunnel 删除"
fi

# 2. 删 DNS 记录
DNS_ID=$(curl -fsS -H "Authorization: Bearer ${CF_TOKEN}" \
    "https://api.cloudflare.com/client/v4/zones/${ZONE_ID}/dns_records?type=CNAME&name=${CF_SUBDOMAIN}.${CF_ZONE}" \
    | python3 -c "import json,sys; rs=json.load(sys.stdin)['result']; print(rs[0]['id'] if rs else '')")
if [[ -n "${DNS_ID}" ]]; then
    log_info "删除 DNS 记录 ${CF_SUBDOMAIN}.${CF_ZONE}"
    curl -fsS -X DELETE -H "Authorization: Bearer ${CF_TOKEN}" \
        "https://api.cloudflare.com/client/v4/zones/${ZONE_ID}/dns_records/${DNS_ID}" \
        > /dev/null && log_ok "DNS 删除"
fi

# 3. Pi 上卸载 cloudflared
SSH_OPTS=( -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null
           -o ConnectTimeout=5 -p "${PI_PORT}" -i "${PI_SSH_KEY}" )
ssh "${SSH_OPTS[@]}" "${PI_USER}@${PI_HOST}" \
    "sudo -S systemctl disable --now cloudflared 2>&1 || true; \
     sudo -S cloudflared service uninstall 2>&1 || true; \
     sudo -S rm -rf /etc/cloudflared /home/${PI_USER}/.cloudflared /var/log/cloudflared"

log_ok "cloudflared 已卸载"

# 4. 恢复 youfu-known 监听 0.0.0.0
log_info "恢复 youfu-known 监听 0.0.0.0"
cat > /tmp/youfu-known.service.open <<'EOF'
[Unit]
Description=youfu-known - personal knowledge base + RAG service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=youfu
Group=youfu
WorkingDirectory=/home/youfu/youfu-known
Environment="YOUFU_KNOWN_ROOT=/home/youfu/youfu-known"
Environment="PATH=/home/youfu/youfu-known/.venv/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart=/home/youfu/youfu-known/.venv/bin/uvicorn main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --workers 1 \
    --no-access-log
Restart=on-failure
RestartSec=5
StandardOutput=append:/var/log/youfu-known/access.log
StandardError=append:/var/log/youfu-known/error.log
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

scp -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
    -i "${PI_SSH_KEY}" /tmp/youfu-known.service.open \
    "${PI_USER}@${PI_HOST}:/tmp/youfu-known.service.open"

cat > /tmp/unlock.exp <<EXP
set timeout 30
log_user 1
set password "$PI_SUDO_PASS"
spawn ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -i $PI_SSH_KEY $PI_USER@$PI_HOST
expect {
    -re "assword.*" { send "\$password\r" }
}
send "sudo -S install -m 644 /tmp/youfu-known.service.open /etc/systemd/system/youfu-known.service\r"
expect -re "\[sudo\] password.*" { send "\$password\r" }
expect -re "\\\$ "
send "sudo -S systemctl daemon-reload && sudo -S systemctl restart youfu-known\r"
expect -re "\[sudo\] password.*" { send "\$password\r" }
expect -re "\\\$ "
send "exit\r"
expect eof
EXP
expect /tmp/unlock.exp
rm -f /tmp/unlock.exp

log_ok "卸载完成 - youfu-known 已恢复监听 0.0.0.0"