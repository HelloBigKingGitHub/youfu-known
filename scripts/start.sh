#!/usr/bin/env bash
# scripts/start.sh
# 启动 youfu-known
#
# 行为:
#   - 已安装才允许启动 (否则提示先 install)
#   - 优先用 systemd (systemctl start)
#   - 无 systemd unit 时 fallback 到 nohup 后台进程, 写 PID 文件

set -o pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"
trap_error

# 智能感知必须在 ensure_dirs 之前 (否则 ensure_dirs 把 YOUFU_LOG_DIR 固定在错误路径)
if [[ "${INSTALL_DIR}" == "/opt/youfu-known" \
    && -f "./main.py" && -d "./app" && -d "./web" ]]; then
    INSTALL_DIR="$(pwd)"
    YOUFU_DATA_DIR="${YOUFU_DATA_DIR:-${INSTALL_DIR}/storage}"
    YOUFU_LOG_DIR="${YOUFU_LOG_DIR:-${INSTALL_DIR}/logs}"
fi

ensure_dirs
ensure_installed || exit 1

# 已在跑就提示
if is_running; then
    log_warn "服务已在运行 (pid=$(get_pid))"
    log_info "如需重启: bash ${SCRIPT_DIR}/restart.sh"
    exit 0
fi

INIT="$(detect_init)"
log_step "启动 youfu-known (${INIT} 模式)"
log_info "安装目录: ${INSTALL_DIR}"
log_info "端口:     ${YOUFU_PORT}"
log_info "用户:     ${YOUFU_USER}"

# -------- systemd 启动 --------
start_systemd() {
    if ! systemctl list-unit-files "${YOUFU_SERVICE_NAME}.service" 2>/dev/null \
        | grep -q "${YOUFU_SERVICE_NAME}.service"; then
        return 1
    fi
    if ! systemctl is-active --quiet "${YOUFU_SERVICE_NAME}"; then
        run systemctl start "${YOUFU_SERVICE_NAME}"
    fi
    if run systemctl is-active --quiet "${YOUFU_SERVICE_NAME}"; then
        log_ok "systemd 启动成功"
        return 0
    fi
    log_error "systemd 启动失败, 查看: journalctl -u ${YOUFU_SERVICE_NAME} -n 50"
    exit 1
}

# -------- nohup 启动 --------
start_nohup() {
    mkdir -p "${YOUFU_LOG_DIR}"

    # 端口占用检查
    if command -v ss >/dev/null 2>&1 && ss -tlnp 2>/dev/null | grep -q ":${YOUFU_PORT} "; then
        log_error "端口 ${YOUFU_PORT} 已被占用:"
        ss -tlnp 2>/dev/null | grep ":${YOUFU_PORT} " | sed 's/^/    /'
        return 1
    fi

    ENV_FILE="${INSTALL_DIR}/.env"
    [[ ! -f "${ENV_FILE}" ]] && { log_error "缺 ${ENV_FILE}"; return 1; }

    CMD=( "${INSTALL_DIR}/.venv/bin/uvicorn" main:app
          --host "${YOUFU_HOST}" --port "${YOUFU_PORT}"
          --workers 1 --no-access-log )

    log_info "执行: ${CMD[*]}"
    # 启动策略: 在当前 shell exec uvicorn, 这样 PID 就是 uvicorn 进程本身
    # 用 nohup + setsid 防止父进程退出导致 SIGHUP
    setsid nohup "${CMD[@]}" \
        >"${YOUFU_LOG_DIR}/access.log" 2>"${YOUFU_LOG_DIR}/error.log" < /dev/null &
    local server_pid=$!
    echo "${server_pid}" > "${PID_FILE}"

    log_info "等待 HTTP 就绪 (http://127.0.0.1:${YOUFU_PORT}/api/health)"
    if wait_for_http "http://127.0.0.1:${YOUFU_PORT}/api/health" 30; then
        # 验证 PID 文件的进程真的存活 (而不是 orphan shell wrapper)
        if kill -0 "${server_pid}" 2>/dev/null; then
            log_ok "服务已启动 (pid=${server_pid})"
        else
            log_warn "PID ${server_pid} 已退出, 但服务可访问 (uvicorn 子进程仍在)"
            # 找出真实 uvicorn PID 更新
            local real_pid; real_pid=$(pgrep -f "${CMD[0]}.*--port ${YOUFU_PORT}" | head -1)
            if [[ -n "${real_pid}" ]]; then
                echo "${real_pid}" > "${PID_FILE}"
                log_info "更新 PID_FILE -> ${real_pid}"
            fi
        fi
        log_info "日志: tail -f ${YOUFU_LOG_DIR}/access.log"
        return 0
    fi

    log_error "服务启动超时, 查看日志: ${YOUFU_LOG_DIR}/error.log"
    log_error "最近 20 行:"
    tail -n 20 "${YOUFU_LOG_DIR}/error.log" | sed 's/^/    /'
    return 1
}

# -------- 主流程 --------
case "${INIT}" in
    systemd)
        if ! start_systemd; then
            log_warn "systemd 不可用, fallback 到 nohup 模式"
            start_nohup || exit 1
        fi
        ;;
    nohup)
        start_nohup || exit 1
        ;;
esac

echo
log_info "访问: http://localhost:${YOUFU_PORT}/"
log_info "停止: bash ${SCRIPT_DIR}/stop.sh"