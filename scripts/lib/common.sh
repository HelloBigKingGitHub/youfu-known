# shellcheck shell=bash
# scripts/lib/common.sh
# 通用辅助函数 - 被所有 *.sh 脚本 source 使用
#
# 提供的核心能力:
#   * 颜色/日志 (log_info / log_warn / log_error / log_ok)
#   * 路径与默认值 (INSTALL_DIR / YOUFU_PORT 等)
#   * sudo 包装 (run / sudo_run)
#   * PID 锁 (acquire_lock / release_lock)
#   * 服务管理探测 (detect_init)
#   * 进程生命周期 (is_running / wait_for_http)
#   * 错误陷阱 (on_error)

# -------- 严格模式 --------
set -o pipefail

# -------- 颜色 (只在 stdout 是 tty 时启用) --------
if [[ -t 1 ]]; then
    _C_RED=$'\e[31m'
    _C_GREEN=$'\e[32m'
    _C_YELLOW=$'\e[33m'
    _C_BLUE=$'\e[34m'
    _C_CYAN=$'\e[36m'
    _C_BOLD=$'\e[1m'
    _C_DIM=$'\e[2m'
    _C_RESET=$'\e[0m'
else
    _C_RED='' _C_GREEN='' _C_YELLOW='' _C_BLUE='' _C_CYAN='' _C_BOLD='' _C_DIM='' _C_RESET=''
fi

# -------- 日志函数 --------
log_info()  { printf '%s[*]%s %s\n' "${_C_BLUE}"   "${_C_RESET}" "$*"; }
log_ok()    { printf '%s[+]%s %s\n' "${_C_GREEN}"  "${_C_RESET}" "$*"; }
log_warn()  { printf '%s[!]%s %s\n' "${_C_YELLOW}" "${_C_RESET}" "$*" >&2; }
log_error() { printf '%s[-]%s %s\n' "${_C_RED}"    "${_C_RESET}" "$*" >&2; }
log_step()  { printf '%s%s── %s%s\n' "${_C_BOLD}${_C_CYAN}" "" "$*" "${_C_RESET}"; }

# -------- 默认值 (可被环境变量覆盖) --------
# 注意: 写法是 ${VAR:-default} 而非 VAR=default, 后者会无条件覆盖 export 进来的值
YOUFU_REPO="${YOUFU_REPO:-https://github.com/youfu/youfu-known.git}"
YOUFU_BRANCH="${YOUFU_BRANCH:-main}"
INSTALL_DIR="${INSTALL_DIR:-/opt/youfu-known}"
YOUFU_USER="${YOUFU_USER:-youfu}"
YOUFU_PORT="${YOUFU_PORT:-8000}"
YOUFU_HOST="${YOUFU_HOST:-0.0.0.0}"
YOUFU_DATA_DIR="${YOUFU_DATA_DIR:-${INSTALL_DIR}/storage}"
YOUFU_LOG_DIR="${YOUFU_LOG_DIR:-}"

# systemd unit 名 / pid 文件 / lock 文件
YOUFU_SERVICE_NAME="youfu-known"
PID_FILE=""
LOCK_FILE=""

# -------- 路径辅助 --------
ensure_dirs() {
    [[ -z "${YOUFU_LOG_DIR}" ]] && YOUFU_LOG_DIR="${INSTALL_DIR}/logs"
    if [[ ! -d "${YOUFU_LOG_DIR}" ]]; then
        if mkdir -p "${YOUFU_LOG_DIR}" 2>/dev/null; then
            :
        else
            # fallback 到 /tmp (无写权限时)
            YOUFU_LOG_DIR="/tmp/youfu-known-logs"
            mkdir -p "${YOUFU_LOG_DIR}"
        fi
    fi
    PID_FILE="${YOUFU_LOG_DIR}/youfu-known.pid"
    LOCK_FILE="${YOUFU_LOG_DIR}/youfu-known.lock"
}

# -------- sudo 包装: 若当前已是 root, 直接执行; 否则加 sudo --------
is_root() { [[ "$(id -u)" -eq 0 ]]; }

run() {
    if is_root; then
        "$@"
    else
        sudo "$@"
    fi
}

# 用指定用户执行命令 (用于非 root 系统上的服务以非特权用户跑)
run_as_user() {
    local user="$1"; shift
    if is_root; then
        sudo -u "${user}" -H "$@"
    elif [[ "$(id -un)" == "${user}" ]]; then
        "$@"
    else
        log_warn "需要 root 权限才能切换到用户 ${user}, 当前命令直接执行"
        "$@"
    fi
}

# -------- 锁 (防止多实例 + 脚本并发) --------
acquire_lock() {
    exec 9>"${LOCK_FILE}" || { log_error "无法创建锁文件 ${LOCK_FILE}"; return 1; }
    if ! flock -n 9; then
        log_error "已有另一实例在运行 (锁被占用): ${LOCK_FILE}"
        return 1
    fi
    echo $$ > "${LOCK_FILE}.pid"
    return 0
}

release_lock() {
    if [[ -n "${LOCK_FILE}" && -e "${LOCK_FILE}.pid" ]]; then
        local pid; pid="$(cat "${LOCK_FILE}.pid" 2>/dev/null || true)"
        if [[ -n "${pid}" && "${pid}" == "$$" ]]; then
            rm -f "${LOCK_FILE}.pid"
        fi
    fi
    exec 9>&- 2>/dev/null || true
}

# -------- 进程状态 --------
is_running() {
    if [[ -f "${PID_FILE}" ]]; then
        local pid; pid="$(cat "${PID_FILE}" 2>/dev/null || true)"
        if [[ -n "${pid}" ]] && kill -0 "${pid}" 2>/dev/null; then
            return 0
        fi
    fi
    return 1
}

get_pid() {
    if [[ -f "${PID_FILE}" ]]; then
        cat "${PID_FILE}" 2>/dev/null || true
    fi
}

# -------- init 系统探测 --------
detect_init() {
    if [[ -d /run/systemd/system ]] && command -v systemctl >/dev/null 2>&1; then
        echo "systemd"
    else
        echo "nohup"
    fi
}

# -------- HTTP 健康检查 --------
wait_for_http() {
    local url="$1" timeout="${2:-30}" elapsed=0
    while (( elapsed < timeout )); do
        if curl -fsS -o /dev/null --max-time 2 "${url}" 2>/dev/null; then
            return 0
        fi
        sleep 1
        elapsed=$(( elapsed + 1 ))
    done
    return 1
}

# -------- 错误陷阱 --------
on_error() {
    local exit_code=$?
    local line_no=${1:-unknown}
    log_error "脚本在第 ${line_no} 行失败, 退出码 ${exit_code}"
    release_lock 2>/dev/null || true
    exit "${exit_code}"
}

trap_error() {
    trap 'on_error ${LINENO}' ERR
}

# -------- 用户友好的分隔线 --------
hr() {
    local char="${1:--}" width="${2:-60}"
    printf '%*s\n' "${width}" '' | tr ' ' "${char}"
}

# -------- 检测包管理器 --------
detect_pkg_manager() {
    if   command -v apt-get >/dev/null 2>&1; then echo "apt"
    elif command -v dnf     >/dev/null 2>&1; then echo "dnf"
    elif command -v yum     >/dev/null 2>&1; then echo "yum"
    elif command -v pacman  >/dev/null 2>&1; then echo "pacman"
    elif command -v apk     >/dev/null 2>&1; then echo "apk"
    elif command -v brew    >/dev/null 2>&1; then echo "brew"
    else                                            echo "unknown"
    fi
}

# -------- 必需命令检查 --------
require_cmd() {
    local cmd="$1"
    if ! command -v "${cmd}" >/dev/null 2>&1; then
        log_error "缺少必需命令: ${cmd}"
        return 1
    fi
}

# -------- 比较版本号 (semver 风格, 数字段比较) --------
version_gte() {
    # usage: version_gte "1.2.3" "1.2.0" -> 0 (true, 1.2.3 >= 1.2.0)
    # sort -V: 输入升序返回 0 (已排序), 降序返回 1
    # 所以 v1 在前 v2 在后输入, 若 sort -V 认 "已排序" = v1 <= v2
    # 想看 v1 >= v2: 把 v2 v1 顺序, 若 sort -V 认 "已排序" = v2 <= v1 → v1 >= v2
    local v1="$1" v2="$2"
    if printf '%s\n%s\n' "${v2}" "${v1}" | sort -V -C 2>/dev/null; then
        return 0
    else
        return 1
    fi
}

# -------- 通用校验 --------
ensure_installed() {
    if [[ ! -d "${INSTALL_DIR}" ]]; then
        log_error "未检测到安装目录: ${INSTALL_DIR}"
        log_error "请先运行 install.sh"
        return 1
    fi
    if [[ ! -f "${INSTALL_DIR}/main.py" ]]; then
        log_error "${INSTALL_DIR} 不是 youfu-known 项目目录 (缺 main.py)"
        return 1
    fi
}