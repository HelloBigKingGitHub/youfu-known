#!/usr/bin/env bash
# scripts/status.sh
# 查看 youfu-known 状态: 进程 / 端口 / 健康 / 资源占用
#
# 用法:
#   bash scripts/status.sh                  # 用默认 8000
#   YOUFU_PORT=18775 bash scripts/status.sh # 指定端口
#
# 自动从 PID 文件解析真实监听端口 (优先)

set -o pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"

# 智能感知必须在 ensure_dirs 之前
if [[ "${INSTALL_DIR}" == "/opt/youfu-known" \
    && -f "./main.py" && -d "./app" ]]; then
    INSTALL_DIR="$(pwd)"
    YOUFU_DATA_DIR="${YOUFU_DATA_DIR:-${INSTALL_DIR}/storage}"
    YOUFU_LOG_DIR="${YOUFU_LOG_DIR:-${INSTALL_DIR}/logs}"
fi

ensure_dirs

# 从 PID 文件解析真实端口 (覆盖默认 8000)
_detect_port_from_pid() {
    if [[ -f "${PID_FILE}" ]]; then
        local pid; pid="$(cat "${PID_FILE}" 2>/dev/null || true)"
        if [[ -n "${pid}" ]] && kill -0 "${pid}" 2>/dev/null; then
            local port; port=$(ps -p "${pid}" -o args= 2>/dev/null \
                | grep -oE -- '--port[[:space:]]+[0-9]+' \
                | grep -oE '[0-9]+' | head -1)
            if [[ -n "${port}" ]]; then
                echo "${port}"
                return 0
            fi
        fi
    fi
    return 1
}

if detected_port=$(_detect_port_from_pid); then
    YOUFU_PORT="${detected_port}"
fi

log_step "youfu-known 状态"
hr "-" 60

INIT="$(detect_init)"
log_info "init 系统:  ${INIT}"
log_info "安装目录:  ${INSTALL_DIR}"
log_info "端口:      ${YOUFU_PORT}"

# 进程状态
case "${INIT}" in
    systemd)
        if systemctl is-active --quiet "${YOUFU_SERVICE_NAME}" 2>/dev/null; then
            log_ok "systemd 状态: active"
            systemctl status "${YOUFU_SERVICE_NAME}" --no-pager -l 2>&1 | sed 's/^/    /' | head -20
        else
            log_warn "systemd 状态: inactive"
        fi
        ;;
    nohup)
        if is_running; then
            PID="$(get_pid)"
            log_ok "进程运行中 (pid=${PID})"

            # 资源占用
            if command -v ps >/dev/null 2>&1; then
                ps -o pid,user,%cpu,%mem,rss,etime,cmd -p "${PID}" 2>/dev/null | sed 's/^/    /' || true
            fi

            # 端口监听
            if command -v ss >/dev/null 2>&1; then
                LISTEN="$(ss -tlnp 2>/dev/null | grep -E ":${YOUFU_PORT}\b" || true)"
                if [[ -n "${LISTEN}" ]]; then
                    log_ok "端口 ${YOUFU_PORT} 监听中:"
                    echo "${LISTEN}" | sed 's/^/    /'
                else
                    log_warn "端口 ${YOUFU_PORT} 未在监听"
                fi
            fi
        else
            log_warn "进程未运行"
            [[ -f "${PID_FILE}" ]] && log_info "残留 PID 文件: ${PID_FILE}"
        fi
        ;;
esac

# HTTP 健康检查
hr "-" 60
log_info "HTTP 健康检查:"
if curl -fsS -o /dev/null --max-time 3 "http://127.0.0.1:${YOUFU_PORT}/api/health" 2>/dev/null; then
    HEALTH="$(curl -fsS --max-time 3 "http://127.0.0.1:${YOUFU_PORT}/api/health" 2>/dev/null)"
    log_ok "健康: ${HEALTH}"
else
    log_warn "健康检查失败 (HTTP 不可达)"
fi

# 数据目录统计
hr "-" 60
if [[ -d "${YOUFU_DATA_DIR}" ]]; then
    log_info "数据目录: ${YOUFU_DATA_DIR}"
    if command -v du >/dev/null 2>&1; then
        du -sh "${YOUFU_DATA_DIR}"/* 2>/dev/null | sed 's/^/    /' || true
    fi
fi

# 日志
if [[ -d "${YOUFU_LOG_DIR}" ]]; then
    log_info "日志目录: ${YOUFU_LOG_DIR}"
    ls -lh "${YOUFU_LOG_DIR}"/*.log 2>/dev/null | tail -5 | sed 's/^/    /' || true
fi