#!/usr/bin/env bash
# scripts/install_pi_deps.sh
# 在树莓派上安装 youfu-known 所需的全部系统依赖
#
# 用法: PI_HOST=192.168.88.102 PI_USER=youfu PI_SUDO_PASS=*** bash scripts/install_pi_deps.sh
# 假设: Pi 用户 youfu 有 sudo (有密码或 NOPASSWD 均可)

set -o pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib/common.sh"

PI_HOST="${PI_HOST:-}"
PI_USER="${PI_USER:-youfu}"
PI_PORT="${PI_PORT:-22}"
PI_SSH_KEY="${PI_SSH_KEY:-$HOME/.ssh/id_rsa_pi}"
PI_SUDO_PASS="${PI_SUDO_PASS:-}"

if [[ -z "${PI_HOST}" ]]; then
    read -r -p "[?] Pi IP: " PI_HOST
fi
[[ -z "${PI_HOST}" ]] && { log_error "缺 PI_HOST"; exit 1; }

if [[ -z "${PI_SUDO_PASS}" ]]; then
    if [[ -n "${PI_SUDO_PASS_FILE}" && -f "${PI_SUDO_PASS_FILE}" ]]; then
        PI_SUDO_PASS="$(cat "${PI_SUDO_PASS_FILE}")"
    else
        read -r -s -p "[?] Pi ${PI_USER} 的 sudo 密码 (留空 = 假设 NOPASSWD): " PI_SUDO_PASS
        echo
    fi
fi

SSH_OPTS=( -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null
           -o ConnectTimeout=5 -p "${PI_PORT}" -i "${PI_SSH_KEY}" )

pi_run() {
    ssh "${SSH_OPTS[@]}" "${PI_USER}@${PI_HOST}" "$@"
}

# 跑 sudo 命令: 有密码用 expect, 无密码直接 sudo
# 优先尝试 NOPASSWD, 失败时回退到 expect + 密码
pi_sudo() {
    local cmd="$1"
    if [[ -z "${PI_SUDO_PASS}" ]]; then
        ssh "${SSH_OPTS[@]}" "${PI_USER}@${PI_HOST}" "sudo -n ${cmd}" \
            || { log_error "sudo -n 失败, 也无密码可喂"; return 1; }
    else
        # expect 喂密码
        local exp_file; exp_file=$(mktemp /tmp/pi-sudo-XXXXXX.exp)
        cat > "${exp_file}" <<EXP
set timeout 300
log_user 1
spawn ssh ${SSH_OPTS[@]} ${PI_USER}@${PI_HOST} "sudo -S -p 'sudo_pwd: ' bash -c '${cmd}'"
expect {
    "sudo_pwd:" { send "${PI_SUDO_PASS}\r"; exp_continue }
    eof
}
EXP
        expect "${exp_file}"
        local rc=$?
        rm -f "${exp_file}"
        return $rc
    fi
}

# -------- 1. 连通 --------
log_step "1/5 测试 SSH + sudo 权限"
log_info "目标: ${PI_USER}@${PI_HOST}"
log_info "Key:  ${PI_SSH_KEY}"

if ! pi_run "whoami" 2>/dev/null | grep -q "${PI_USER}"; then
    log_error "SSH 不通"
    exit 1
fi
log_ok "SSH 通"

# 测 sudo
if [[ -z "${PI_SUDO_PASS}" ]]; then
    if pi_run "sudo -n whoami 2>/dev/null" | grep -q root; then
        log_ok "NOPASSWD sudo 通"
    else
        log_warn "无 NOPASSWD sudo, 需要密码"
        exit 1
    fi
else
    if pi_sudo "whoami" 2>&1 | grep -q root; then
        log_ok "sudo + 密码 通"
    else
        log_error "sudo 失败, 密码错?"
        exit 1
    fi
fi

# -------- 2. 系统包 --------
log_step "2/5 装系统依赖 (apt update + install)"
log_info "libatlas-base-dev → libopenblas-dev (Debian 13 包名变了)"
pi_sudo "DEBIAN_FRONTEND=noninteractive apt-get update -qq 2>&1 | tail -2 && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3-venv python3-dev python3-pip build-essential libopenblas-dev libxml2-dev libxslt1-dev libffi-dev libssl-dev zlib1g-dev libjpeg-dev libpng-dev git curl ca-certificates rsync 2>&1 | tail -3" 2>&1 | tail -10
log_ok "系统包就绪"

# -------- 3. Node 20 (NodeSource) --------
log_step "3/5 装 Node 20 (NodeSource, 拉镜像要 1-3 分钟)"
if pi_run "node --version 2>/dev/null" | grep -qE "^v(1[89]|[2-9][0-9])"; then
    log_ok "Node 已装: $(pi_run 'node --version')"
else
    pi_sudo "curl -fsSL https://deb.nodesource.com/setup_20.x | bash - 2>&1 | tail -3 && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq nodejs 2>&1 | tail -3" 2>&1 | tail -10
    log_ok "Node: $(pi_run 'node --version') / npm: $(pi_run 'npm --version')"
fi

# -------- 4. 项目目录 --------
log_step "4/5 准备项目目录"
pi_run "mkdir -p ~/youfu-known && ls -ld ~/youfu-known" 2>&1 | tail -2
log_ok "项目目录: /home/${PI_USER}/youfu-known"

# -------- 5. 总结 --------
log_step "5/5 依赖安装完成"
echo
pi_run "echo '--- Pi 环境 ---'; uname -m; python3 --version; node --version 2>/dev/null || echo 'no node'; npm --version 2>/dev/null || echo 'no npm'; which rsync; echo '--- 磁盘 ---'; df -h / | tail -1" 2>&1 | sed 's/^/    /'

echo
hr "-" 60
log_ok "Pi 端依赖已全部就绪"
echo
log_info "下一步: 跑 deploy 推送代码并启动服务"
log_info "  PI_HOST=${PI_HOST} bash scripts/deploy_pi.sh"