#!/usr/bin/env bash
# scripts/restore.sh
# 从 backup-*.tar.gz 恢复 storage/ 目录
#
# 用法:
#   bash scripts/restore.sh <backup_file>
#   bash scripts/restore.sh --latest
#
# 行为:
#   - 确认当前 storage/ 会被覆盖 (interactive prompt)
#   - 解包到 INSTALL_DIR
#   - 不重启服务 (operator 自行决定时机)
#
# 环境变量 (可选):
#   YOUFU_INSTALL_DIR - 安装根目录 (默认 /home/youfu/youfu-known)

set -o pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"

INSTALL_DIR="${YOUFU_INSTALL_DIR:-/home/youfu/youfu-known}"
BACKUP_DIR="${YOUFU_BACKUP_DIR:-${INSTALL_DIR}/backups}"

usage() {
    cat <<EOF
Usage:
  bash scripts/restore.sh <backup_file>
  bash scripts/restore.sh --latest

Environment:
  YOUFU_INSTALL_DIR  install root (default: ${INSTALL_DIR})
  YOUFU_BACKUP_DIR   backup directory (default: ${BACKUP_DIR})
EOF
}

# -------- 参数解析 --------
if [[ $# -lt 1 ]]; then
    usage
    exit 1
fi

if [[ "$1" == "--latest" ]]; then
    BACKUP_FILE=$(find "${BACKUP_DIR}" -name 'backup-*.tar.gz' -type f -printf '%T@\t%p\n' \
        | sort -n | tail -1 | cut -f2-)
    if [[ -z "${BACKUP_FILE}" ]]; then
        log_error "未找到任何备份文件 (${BACKUP_DIR})"
        exit 1
    fi
elif [[ "$1" == "-h" || "$1" == "--help" ]]; then
    usage
    exit 0
else
    BACKUP_FILE="$1"
fi

if [[ ! -f "${BACKUP_FILE}" ]]; then
    log_error "备份文件不存在: ${BACKUP_FILE}"
    exit 1
fi

# -------- 确认 --------
log_step "恢复操作"
log_warn "将覆盖 INSTALL_DIR/storage/ : ${INSTALL_DIR}/storage"
log_warn "备份文件: ${BACKUP_FILE}"
if [[ -t 0 ]]; then
    read -r -p "确认继续? [y/N] " ans
    case "${ans}" in
        y|Y|yes|YES) ;;
        *) log_info "已取消"; exit 0 ;;
    esac
fi

# -------- 解包 --------
if [[ ! -d "${INSTALL_DIR}" ]]; then
    log_error "INSTALL_DIR 不存在: ${INSTALL_DIR}"
    exit 1
fi

# 解包前给 storage/ 拍快照, 万一出问题可以回滚
STAMP="$(date +%Y%m%d-%H%M%S)"
SNAPSHOT_DIR="/tmp/youfu-known-storage.${STAMP}"
if [[ -d "${INSTALL_DIR}/storage" ]]; then
    log_info "快照当前 storage/ 到 ${SNAPSHOT_DIR}"
    cp -a "${INSTALL_DIR}/storage" "${SNAPSHOT_DIR}"
fi

log_info "解包 ${BACKUP_FILE} 到 ${INSTALL_DIR}/"
if ! tar -xzf "${BACKUP_FILE}" -C "${INSTALL_DIR}" 2>/tmp/youfu-restore.err; then
    log_error "解包失败:"
    sed 's/^/    /' /tmp/youfu-restore.err >&2
    rm -f /tmp/youfu-restore.err
    if [[ -d "${SNAPSHOT_DIR}" ]]; then
        log_warn "回滚到快照 ${SNAPSHOT_DIR}"
        rm -rf "${INSTALL_DIR}/storage"
        mv "${SNAPSHOT_DIR}" "${INSTALL_DIR}/storage"
    fi
    exit 1
fi
rm -f /tmp/youfu-restore.err

log_ok "恢复完成: ${BACKUP_FILE}"
if [[ -d "${SNAPSHOT_DIR}" ]]; then
    log_info "旧 storage/ 快照保留在 ${SNAPSHOT_DIR} (operator 可手动删除)"
fi
log_info "如需重启服务: bash ${SCRIPT_DIR}/restart.sh"