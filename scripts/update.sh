#!/usr/bin/env bash
# scripts/update.sh
# 升级 youfu-known: 拉最新代码 + 重装依赖 + 重启服务
#
# 行为:
#   1. git fetch + reset 到 origin/${YOUFU_BRANCH}
#   2. requirements.txt 变了就重装
#   3. 前端 package.json 变了就重 npm install + build
#   4. 重启服务

set -o pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"
trap_error

# 智能感知必须在 ensure_dirs 之前
if [[ "${INSTALL_DIR}" == "/opt/youfu-known" \
    && -f "./main.py" && -d "./app" ]]; then
    INSTALL_DIR="$(pwd)"
    YOUFU_DATA_DIR="${YOUFU_DATA_DIR:-${INSTALL_DIR}/storage}"
    YOUFU_LOG_DIR="${YOUFU_LOG_DIR:-${INSTALL_DIR}/logs}"
fi

ensure_dirs
ensure_installed || exit 1

log_step "升级 youfu-known"
hr "-" 60

# 记录当前 HEAD
OLD_HEAD="$(git -C "${INSTALL_DIR}" rev-parse --short HEAD 2>/dev/null || echo 'unknown')"
log_info "当前 HEAD: ${OLD_HEAD}"

# 1. 拉代码
log_info "git fetch origin"
run git -C "${INSTALL_DIR}" fetch --all --prune
log_info "git reset --hard origin/${YOUFU_BRANCH}"
run git -C "${INSTALL_DIR}" reset --hard "origin/${YOUFU_BRANCH}"
NEW_HEAD="$(git -C "${INSTALL_DIR}" rev-parse --short HEAD)"
log_ok "新 HEAD:   ${NEW_HEAD}"

if [[ "${OLD_HEAD}" == "${NEW_HEAD}" ]]; then
    log_info "已是最新, 无需继续"
    exit 0
fi

# 2. Python 依赖 (总是重装, 简单可靠)
log_info "升级 Python 依赖"
run_as_user "${YOUFU_USER}" "${INSTALL_DIR}/.venv/bin/pip" install --quiet --upgrade -r "${INSTALL_DIR}/requirements.txt"

# 3. 前端依赖
log_info "升级前端依赖 + build"
run_as_user "${YOUFU_USER}" npm --prefix "${INSTALL_DIR}/web" install --no-audit --no-fund --silent
run_as_user "${YOUFU_USER}" npm --prefix "${INSTALL_DIR}/web" run build
log_ok "前端构建完成"

# 4. 重启
log_info "重启服务"
bash "${SCRIPT_DIR}/restart.sh"

log_ok "升级完成 (${OLD_HEAD} -> ${NEW_HEAD})"