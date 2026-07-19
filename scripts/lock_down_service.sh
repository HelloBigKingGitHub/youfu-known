#!/usr/bin/env bash
# scripts/lock_down_service.sh
# 把 youfu-known 改成只监听 127.0.0.1, 公网无法直接访问
# 配合 Cloudflare Tunnel 使用: CF 走 tunnel 进来 -> uvicorn 127.0.0.1:8000
#
# 用法: bash scripts/lock_down_service.sh

set -o pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib/common.sh"

PI_HOST="${PI_HOST:-}"
PI_USER="${PI_USER:-youfu}"
PI_PORT="${PI_PORT:-22}"
PI_SSH_KEY="${PI_SSH_KEY:-$HOME/.ssh/id_rsa_pi}"
PI_SUDO_PASS="${PI_SUDO_PASS:-}"

if [[ -n "${PI_SUDO_PASS_FILE}" && -f "${PI_SUDO_PASS_FILE}" ]]; then
    PI_SUDO_PASS="$(cat "${PI_SUDO_PASS_FILE}")"
fi

SSH_OPTS=( -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null
           -o ConnectTimeout=5 -p "${PI_PORT}" -i "${PI_SSH_KEY}" )

pi_run() {
    ssh "${SSH_OPTS[@]}" "${PI_USER}@${PI_HOST}" "$@"
}

if [[ -z "${PI_HOST}" ]]; then
    read -r -p "[?] Pi IP: " PI_HOST
fi

log_step "锁定 youfu-known 服务为 127.0.0.1 (公网访问关闭)"
log_warn "执行后, 公网 / 同网段将无法直接访问 :8000, 只能走 Cloudflare Tunnel"
read -r -p "[?] 确认? [y/N] " CONFIRM
if [[ ! "${CONFIRM}" =~ ^[Yy]$ ]]; then
    log_info "取消"
    exit 0
fi

# 推修好的 systemd unit (只监听 127.0.0.1)
cat > /tmp/youfu-known.service.locked <<'EOF'
[Unit]
Description=youfu-known - personal knowledge base + RAG service (locked to localhost)
Documentation=https://github.com/youfu/youfu-known
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=youfu
Group=youfu
WorkingDirectory=/home/youfu/youfu-known
Environment="YOUFU_KNOWN_ROOT=/home/youfu/youfu-known"
Environment="PATH=/home/youfu/youfu-known/.venv/bin:/usr/local/bin:/usr/bin:/bin"
# !! 关键: bind 127.0.0.1, 公网 / 同网段其它机器都不能直接访问 !!
ExecStart=/home/youfu/youfu-known/.venv/bin/uvicorn main:app \
    --host 127.0.0.1 \
    --port 8000 \
    --workers 1 \
    --no-access-log
Restart=on-failure
RestartSec=5
TimeoutStopSec=20
StandardOutput=append:/var/log/youfu-known/access.log
StandardError=append:/var/log/youfu-known/error.log

# Hardening
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=read-only
ReadWritePaths=/home/youfu/youfu-known/storage /var/log/youfu-known

[Install]
WantedBy=multi-user.target
EOF

# 推到 Pi
scp -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
    -i "${PI_SSH_KEY}" \
    /tmp/youfu-known.service.locked \
    "${PI_USER}@${PI_HOST}:/tmp/youfu-known.service.locked"

# 用 expect 装 unit + 重启 + 验证
cat > /tmp/lock_down.exp <<EXP
set timeout 30
log_user 1
set password "$PI_SUDO_PASS"
spawn ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -i $PI_SSH_KEY $PI_USER@$PI_HOST
expect {
    -re "assword.*" { send "\$password\r" }
}
send "sudo -S install -m 644 /tmp/youfu-known.service.locked /etc/systemd/system/youfu-known.service\r"
expect -re "\[sudo\] password.*" { send "\$password\r" }
expect -re "\\\$ "
send "sudo -S systemctl daemon-reload && sudo -S systemctl restart youfu-known\r"
expect -re "\[sudo\] password.*" { send "\$password\r" }
expect -re "\\\$ "
send "sudo -S systemctl status youfu-known --no-pager -l | head -8\r"
expect -re "\\\$ "
send "ss -tlnp 2>/dev/null | grep 8000 || echo NOT_LISTENING\r"
expect -re "\\\$ "
send "exit\r"
expect eof
EXP
expect /tmp/lock_down.exp
rm -f /tmp/lock_down.exp

echo
log_ok "youfu-known 现在只监听 127.0.0.1:8000"
log_info "验证: ssh ${PI_USER}@${PI_HOST} 'curl -s http://127.0.0.1:8000/api/health'"
log_info "外网访问必须通过 Cloudflare Tunnel"