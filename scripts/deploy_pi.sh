#!/usr/bin/env bash
# scripts/deploy_pi.sh
# 把 youfu-known 部署到树莓派
#
# 流程:
#   0. 检查本地 git 状态 (未 commit 的改动会阻止 deploy)
#      若有远端 origin, 自动 push 到 main
#   1. 验证 SSH 连通 (expect + 密码 或 sshpass 或 key)
#   2. rsync 同步项目代码到 Pi (排除 .venv/node_modules/storage 等)
#   3. Pi 上跑 install.sh (拉依赖、构建前端、注册服务)
#   4. Pi 上跑 start.sh, 显示状态
#
# 用法:
#   PI_HOST=192.168.88.102 \
#   PI_USER=youfu \
#   PI_PASSWORD='xxx' \
#   bash scripts/deploy_pi.sh
#
#   # 默认值 (可省略):
#   PI_HOST=         (必填)
#   PI_USER=youfu
#   PI_PORT=22
#   PI_PASSWORD=     (若用 key 认证, 留空)
#   PI_INSTALL_DIR=/opt/youfu-known
#   PI_PORT_HTTP=8000
#   SKIP_GIT_PUSH=1  (跳过 git 推送, 默认会自动 push main)

set -o pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"

# -------- 参数 --------
PI_HOST="${PI_HOST:-}"
PI_USER="${PI_USER:-youfu}"
PI_PORT="${PI_PORT:-22}"
PI_PASSWORD="${PI_PASSWORD:-}"
PI_INSTALL_DIR="${PI_INSTALL_DIR:-/opt/youfu-known}"
PI_PORT_HTTP="${PI_PORT_HTTP:-8000}"

# -------- 询问缺失的必填项 --------
if [[ -z "${PI_HOST}" ]]; then
    read -r -p "[?] Pi 的 IP 或主机名 (例如 192.168.88.102): " PI_HOST
fi
if [[ -z "${PI_HOST}" ]]; then
    log_error "缺 PI_HOST"
    exit 1
fi
if [[ -z "${PI_PASSWORD}" ]]; then
    # 给一次输入密码的机会 (不显示明文)
    read -r -s -p "[?] Pi 密码 (留空 = 试 key 认证): " PI_PASSWORD
    echo
fi

# -------- SSH 工具函数 --------
SSH_OPTS=( -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null
           -o ConnectTimeout=5 -p "${PI_PORT}"
           -i "${PI_SSH_KEY:-${HOME}/.ssh/id_rsa_pi}" )

# 在 Pi 上跑一条命令, stdout 透传
# 用法: pi_run "command" 或 pi_run <<'EOF' ... EOF
pi_run() {
    local cmd
    if [[ $# -gt 0 ]]; then
        cmd="$*"
    else
        cmd="$(cat)"
    fi

    if [[ -n "${PI_PASSWORD}" ]] && command -v expect >/dev/null 2>&1; then
        # 用 expect (有密码时)
        local exp_file; exp_file=$(mktemp /tmp/pi-run-XXXXXX.exp)
        cat > "${exp_file}" <<EXP
set timeout 300
log_user 1
spawn ssh ${SSH_OPTS[@]} ${PI_USER}@${PI_HOST} {${cmd}}
expect {
    -re ".*assword.*" { send "${PI_PASSWORD}\r"; exp_continue }
    eof
}
EXP
        expect "${exp_file}"
        local rc=$?
        rm -f "${exp_file}"
        return ${rc}
    elif [[ -n "${PI_PASSWORD}" ]] && command -v sshpass >/dev/null 2>&1; then
        sshpass -p "${PI_PASSWORD}" ssh "${SSH_OPTS[@]}" "${PI_USER}@${PI_HOST}" "${cmd}"
    else
        # 免密 (key 认证)
        ssh "${SSH_OPTS[@]}" "${PI_USER}@${PI_HOST}" "${cmd}"
    fi
}

# 在 Pi 上 sudo 跑 (不需要密码通过 sudoers NOPASSWD; 否则 expect 输密码)
pi_sudo() {
    if [[ "${PI_USER}" == "root" ]]; then
        pi_run "$*"
    else
        pi_run "sudo $*"
    fi
}

# -------- 1. 探测 --------
log_step "1/5 测试 SSH 连通"
log_info "目标: ${PI_USER}@${PI_HOST}:${PI_PORT}"
log_info "认证: $(if [[ -n ${PI_PASSWORD} ]]; then echo 'password (via expect/sshpass)'; else echo 'key (assumed)'; fi)"

if pi_run "echo OK" 2>&1 | grep -q OK; then
    log_ok "SSH 通"
else
    log_error "SSH 失败, 检查 IP / 端口 / 用户 / 密码 / 防火墙"
    exit 1
fi

# 看 Pi 基础环境
log_info "Pi 系统信息:"
pi_run "uname -a; echo ARCH=\$(uname -m); head -1 /etc/os-release; cat /proc/device-tree/model 2>/dev/null | tr -d '\0' || echo 'no_dt'; python3 --version 2>&1; node --version 2>&1" 2>&1 | sed 's/^/    /'

# -------- 1. Git 状态 + push --------
if [[ "${SKIP_GIT_PUSH:-0}" != "1" ]]; then
    log_step "1/6 检查本地 git 状态"
    if git rev-parse --is-inside-work-tree &>/dev/null; then
        # 拒绝 dirty 工作区 (避免推送半成品)
        if ! git diff --quiet HEAD 2>/dev/null; then
            log_error "本地 git 有未提交的改动, 请先 commit 或 stash"
            log_error "若确认要强行 deploy, 设 SKIP_GIT_PUSH=1 跳过 git push 步骤"
            git status --short | head -10
            exit 1
        fi
        # 推送当前分支 (如已配 origin)
        if git remote get-url origin &>/dev/null; then
            local_branch=$(git rev-parse --abbrev-ref HEAD)
            log_info "推送本地 main 到 origin..."
            if git push origin "${local_branch}" 2>&1 | tail -3; then
                log_info "✓ 已推送到 $(git remote get-url origin)"
            else
                log_warn "⚠️ git push 失败 (可能无网络或远端无权限), 继续 deploy"
            fi
        else
            log_info "未配 origin remote, 跳过 git push"
        fi
    else
        log_warn "非 git 仓库, 跳过 git push"
    fi
else
    log_info "SKIP_GIT_PUSH=1, 跳过 git push"
fi

# -------- 2. rsync --------
log_step "2/5 rsync 同步代码到 ${PI_INSTALL_DIR}"

RSYNC_EXCLUDES=(
    --exclude='.venv'
    --exclude='node_modules'
    --exclude='__pycache__'
    --exclude='*.pyc'
    --exclude='storage'
    --exclude='logs'
    --exclude='web/dist'
    --exclude='.pytest_cache'
    --exclude='.git'
    --exclude='.idea'
    --exclude='*.log'
)

# 在 Pi 上准备好目录
pi_sudo "mkdir -p '${PI_INSTALL_DIR}' && chown -R ${PI_USER}:${PI_USER} '${PI_INSTALL_DIR}'" 2>&1 | tail -3

if command -v rsync >/dev/null 2>&1; then
    log_info "rsync 推送项目 (排除 .venv / node_modules / storage)..."

    # rsync 的远程 shell 需要能传密码
    if [[ -n "${PI_PASSWORD}" ]] && command -v sshpass >/dev/null 2>&1; then
        rsync -az --delete "${RSYNC_EXCLUDES[@]}" \
            -e "sshpass -p ${PI_PASSWORD} ssh ${SSH_OPTS[*]}" \
            "${SCRIPT_DIR}/../" \
            "${PI_USER}@${PI_HOST}:${PI_INSTALL_DIR}/" 2>&1 | tail -10
    else
        # expect 包 ssh (rsync 会调 ssh)
        # 简化: 走 tar+ssh 一次性
        log_info "rsync + 密码认证不便, 改用 tar | ssh 流式传输"
        tar -czf - -C "${SCRIPT_DIR}/.." \
            --exclude='.venv' --exclude='node_modules' \
            --exclude='__pycache__' --exclude='*.pyc' \
            --exclude='storage' --exclude='logs' \
            --exclude='web/dist' --exclude='.pytest_cache' \
            --exclude='.git' --exclude='.idea' --exclude='*.log' \
            . | pi_run "tar -xzf - -C '${PI_INSTALL_DIR}'"
    fi
else
    log_info "本地无 rsync, 用 tar | ssh 传输"
    tar -czf - -C "${SCRIPT_DIR}/.." \
        --exclude='.venv' --exclude='node_modules' \
        --exclude='__pycache__' --exclude='*.pyc' \
        --exclude='storage' --exclude='logs' \
        --exclude='web/dist' --exclude='.pytest_cache' \
        --exclude='.git' --exclude='.idea' --exclude='*.log' \
        . | pi_run "tar -xzf - -C '${PI_INSTALL_DIR}'"
fi

log_ok "代码已同步"

# -------- 3. 装系统依赖 (若需要) --------
log_step "3/5 Pi 上准备系统包"

log_info "检查/装 python3-venv + build-essential + libatlas + libxml2"
# Pi 上 OpenCV/chroma 用的基础库
pi_sudo "apt-get update -qq && apt-get install -y -qq \
    python3-venv python3-dev build-essential \
    libatlas-base-dev libxml2-dev libxslt1-dev \
    2>&1 | tail -5" 2>&1 | tail -5

# -------- 4. Pi 上跑 install.sh --------
log_step "4/5 Pi 上 install.sh"

pi_run "cd '${PI_INSTALL_DIR}' && \
    INSTALL_DIR='${PI_INSTALL_DIR}' \
    YOUFU_PORT='${PI_PORT_HTTP}' \
    YOUFU_USER='${PI_USER}' \
    YOUFU_REPO=local \
    bash scripts/install.sh" 2>&1 | tail -40

log_ok "Pi 端 install 完成"

# -------- 5. 启动 + 状态 --------
log_step "5/5 启动 + 状态"

pi_run "cd '${PI_INSTALL_DIR}' && \
    INSTALL_DIR='${PI_INSTALL_DIR}' \
    YOUFU_PORT='${PI_PORT_HTTP}' \
    YOUFU_USER='${PI_USER}' \
    bash scripts/start.sh" 2>&1 | tail -15

echo
hr "-" 60
log_info "Pi 端状态:"
pi_run "cd '${PI_INSTALL_DIR}' && \
    INSTALL_DIR='${PI_INSTALL_DIR}' \
    YOUFU_PORT='${PI_PORT_HTTP}' \
    bash scripts/status.sh" 2>&1

hr "-" 60
log_ok "部署完成!"
echo
log_info "Pi 端访问: http://${PI_HOST}:${PI_PORT_HTTP}/"
log_info "本机访问: http://${PI_HOST}:${PI_PORT_HTTP}/ (同网段即可)"
log_info "Pi 上日志: ssh ${PI_USER}@${PI_HOST} 'tail -f ${PI_INSTALL_DIR}/logs/access.log'"
echo
log_warn "安全提醒: 你刚刚在对话中明文传了 SSH 密码, 建议立即在 Pi 上改密码:"
log_warn "    ssh youfu@${PI_HOST} 'passwd'"
log_warn "或改用 SSH key: ssh-copy-id ${PI_USER}@${PI_HOST}"