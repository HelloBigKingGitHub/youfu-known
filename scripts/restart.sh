#!/usr/bin/env bash
# scripts/restart.sh
# 重启 youfu-known

set -o pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"

# 智能感知必须在 stop / start 调用之前
if [[ "${INSTALL_DIR}" == "/opt/youfu-known" \
    && -f "./main.py" && -d "./app" ]]; then
    INSTALL_DIR="$(pwd)"
    YOUFU_DATA_DIR="${YOUFU_DATA_DIR:-${INSTALL_DIR}/storage}"
    YOUFU_LOG_DIR="${YOUFU_LOG_DIR:-${INSTALL_DIR}/logs}"
    export INSTALL_DIR YOUFU_DATA_DIR YOUFU_LOG_DIR
fi

bash "${SCRIPT_DIR}/stop.sh" || { log_error "停止失败, 不再启动"; exit 1; }
sleep 1
bash "${SCRIPT_DIR}/start.sh"