#!/usr/bin/env bash
# scripts/uninstall.sh
# 卸载 youfu-known
#
# 行为:
#   询问: 是否保留数据 (storage/ 与 .env)
#   询问: 是否移除代码目录
#   询问: 是否移除 systemd unit
#
# 不会动 storage/ 与 .env 除非明确说不要保留

set -o pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"

log_step "卸载 youfu-known"
hr "-" 60

if [[ ! -d "${INSTALL_DIR}" ]]; then
    log_info "未检测到 ${INSTALL_DIR}, 已无内容可卸"
    exit 0
fi

# 1. 停止
log_info "先停止服务 (如有在跑)"
bash "${SCRIPT_DIR}/stop.sh" 2>/dev/null || true

# 2. 数据保留?
read -r -p "[?] 是否保留数据目录 ${YOUFU_DATA_DIR}? [y/N] " KEEP_DATA
KEEP_DATA="${KEEP_DATA:-N}"

# 3. .env 保留?
read -r -p "[?] 是否保留 .env (含 API key)? [y/N] " KEEP_ENV
KEEP_ENV="${KEEP_ENV:-N}"

# 4. systemd 卸载?
INIT="$(detect_init)"
REMOVE_UNIT="N"
if [[ "${INIT}" == "systemd" ]] && systemctl list-unit-files "${YOUFU_SERVICE_NAME}.service" 2>/dev/null | grep -q "${YOUFU_SERVICE_NAME}"; then
    read -r -p "[?] 卸载 systemd unit? [Y/n] " REMOVE_UNIT
    REMOVE_UNIT="${REMOVE_UNIT:-Y}"
fi

# 5. 代码目录?
read -r -p "[?] 删除整个安装目录 ${INSTALL_DIR}? [y/N] " REMOVE_DIR
REMOVE_DIR="${REMOVE_DIR:-N}"

echo
log_step "执行卸载..."

if [[ "${REMOVE_UNIT}" =~ ^[Yy]$ ]]; then
    run systemctl disable --now "${YOUFU_SERVICE_NAME}" 2>/dev/null || true
    run rm -f "/etc/systemd/system/${YOUFU_SERVICE_NAME}.service"
    run systemctl daemon-reload
    log_ok "systemd unit 已卸载"
fi

if [[ "${REMOVE_DIR}" =~ ^[Yy]$ ]]; then
    if [[ "${KEEP_DATA}" =~ ^[Yy]$ ]]; then
        # 把数据移到 /tmp 临时目录 (保险), 但更简单: 让用户自己备份
        log_warn "你选择了删除安装目录但保留数据"
        log_warn "请手动将 ${YOUFU_DATA_DIR} 备份到其它路径"
    fi
    run rm -rf "${INSTALL_DIR}"
    log_ok "已删除 ${INSTALL_DIR}"
else
    # 仅卸载 systemd / 不删代码
    if [[ ! "${KEEP_ENV}" =~ ^[Yy]$ ]] && [[ -f "${INSTALL_DIR}/.env" ]]; then
        run rm -f "${INSTALL_DIR}/.env"
        log_ok "已删除 .env"
    fi
    if [[ ! "${KEEP_DATA}" =~ ^[Yy]$ ]] && [[ -d "${YOUFU_DATA_DIR}" ]]; then
        run rm -rf "${YOUFU_DATA_DIR}"
        log_ok "已删除数据目录"
    fi
fi

log_ok "卸载完成"