#!/usr/bin/env bash
# scripts/stop.sh
# 停止 youfu-known
#
# 行为:
#   - systemd 模式: systemctl stop
#   - nohup 模式:   kill PID (SIGTERM, 15s 超时后 SIGKILL)

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

INIT="$(detect_init)"
log_step "停止 youfu-known (${INIT} 模式)"

# -------- systemd 停止 --------
stop_systemd() {
    if systemctl list-unit-files "${YOUFU_SERVICE_NAME}.service" 2>/dev/null \
        | grep -q "${YOUFU_SERVICE_NAME}.service" \
        && systemctl is-active --quiet "${YOUFU_SERVICE_NAME}"; then
        run systemctl stop "${YOUFU_SERVICE_NAME}"
        log_ok "systemd 停止成功"
        return 0
    fi
    return 1
}

# -------- nohup 停止 --------
stop_nohup() {
    if ! is_running; then
        log_info "nohup 进程未在运行"
        rm -f "${PID_FILE}"
        return 0
    fi

    local pid; pid="$(get_pid)"
    log_info "终止进程 pid=${pid} (SIGTERM, 15s 超时)"

    if ! kill -TERM "${pid}" 2>/dev/null; then
        log_warn "kill 失败 (pid=${pid} 可能已退出)"
        rm -f "${PID_FILE}"
        return 0
    fi

    local elapsed=0
    while (( elapsed < 15 )); do
        if ! kill -0 "${pid}" 2>/dev/null; then
            log_ok "已停止"
            rm -f "${PID_FILE}"
            return 0
        fi
        sleep 1
        elapsed=$(( elapsed + 1 ))
    done

    log_warn "进程未响应 SIGTERM, 升级到 SIGKILL"
    kill -KILL "${pid}" 2>/dev/null || true
    sleep 1

    if kill -0 "${pid}" 2>/dev/null; then
        log_error "无法终止进程 pid=${pid}"
        return 1
    fi
    log_ok "SIGKILL 成功"
    rm -f "${PID_FILE}"
    return 0
}

# -------- 主流程 --------
case "${INIT}" in
    systemd)
        if ! stop_systemd; then
            log_info "systemd 未管理此实例, 检查 nohup 进程"
            stop_nohup || exit 1
        fi
        ;;
    nohup)
        stop_nohup || exit 1
        ;;
esac