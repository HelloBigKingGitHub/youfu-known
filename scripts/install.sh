#!/usr/bin/env bash
# scripts/install.sh
# 一键安装 youfu-known
#
# 用法:
#   ./scripts/install.sh                    # 默认路径 /opt/youfu-known
#   INSTALL_DIR=$HOME/youfu-known ./scripts/install.sh   # 自定义路径, 无需 root
#   YOUFU_PORT=9000 ./scripts/install.sh   # 自定义端口
#
# 行为:
#   1. 检查系统依赖 (git / python3 / node / npm)
#   2. 创建运行用户 (root 时) + 安装目录
#   3. 克隆或拉取代码
#   4. 创建 venv + 装 Python 依赖
#   5. npm install + 前端 build
#   6. 生成 .env (若不存在, 复制 .env.example)
#   7. 初始化 SQLite + Chroma 目录
#   8. 注册 systemd 服务 (若可用) 或提示用 start.sh 启动

set -o pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"
trap_error

log_step "youfu-known 安装脚本"
hr "=" 60
log_info "安装路径:    ${INSTALL_DIR}"
log_info "运行用户:    ${YOUFU_USER}"
log_info "服务端口:    ${YOUFU_PORT}"
log_info "Git 源:      ${YOUFU_REPO}"
log_info "Git 分支:    ${YOUFU_BRANCH}"
log_info "包管理器:    $(detect_pkg_manager)"
hr "=" 60

# ---------- 1. 依赖检查 ----------
log_step "1/7 检查系统依赖"
require_cmd git
require_cmd python3 || { log_error "需要 python3 >= 3.10"; exit 1; }
require_cmd node   || { log_error "需要 node >= 18"; exit 1; }
require_cmd npm    || { log_error "需要 npm"; exit 1; }

# python 版本校验
PY_VERSION="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
if ! version_gte "${PY_VERSION}.0" "3.10.0"; then
    log_error "python 版本 ${PY_VERSION} 过低, 需要 >= 3.10"
    exit 1
fi
log_ok "python3 ${PY_VERSION}"

# node 版本校验
NODE_VERSION="$(node -e 'console.log(process.versions.node.split(".")[0])')"
if (( NODE_VERSION < 18 )); then
    log_error "node 版本 ${NODE_VERSION} 过低, 需要 >= 18"
    exit 1
fi
log_ok "node v${NODE_VERSION}, npm $(npm --version)"

# ---------- 2. 用户与目录 ----------
log_step "2/7 创建运行用户与安装目录"

if id "${YOUFU_USER}" >/dev/null 2>&1; then
    log_info "用户 ${YOUFU_USER} 已存在, 跳过创建"
else
    if is_root; then
        if command -v useradd >/dev/null 2>&1; then
            useradd --system --create-home --shell /bin/bash "${YOUFU_USER}"
            log_ok "创建系统用户 ${YOUFU_USER}"
        elif command -v adduser >/dev/null 2>&1; then
            adduser --system --home "/home/${YOUFU_USER}" "${YOUFU_USER}"
            log_ok "创建用户 ${YOUFU_USER} (adduser)"
        else
            log_warn "既无 useradd 也无 adduser, 跳过用户创建 (后续操作可能需 sudo)"
        fi
    else
        log_info "当前非 root, 跳过创建系统用户 (使用当前用户 $(id -un) 启动)"
        YOUFU_USER="$(id -un)"
    fi
fi

# 创建安装目录
if [[ ! -d "${INSTALL_DIR}" ]]; then
    run mkdir -p "${INSTALL_DIR}" || { log_error "创建 ${INSTALL_DIR} 失败"; exit 1; }
    log_ok "创建 ${INSTALL_DIR}"
fi

# ---------- 3. 克隆代码 ----------
log_step "3/7 拉取代码"
if [[ -d "${INSTALL_DIR}/.git" ]]; then
    # 有 git 仓库, 看有没有 origin 远端
    if run git -C "${INSTALL_DIR}" remote get-url origin >/dev/null 2>&1; then
        log_info "已存在 git 仓库 + origin 远端, 执行 fetch + reset"
        run git -C "${INSTALL_DIR}" fetch --all --prune
        run git -C "${INSTALL_DIR}" reset --hard "origin/${YOUFU_BRANCH}"
    else
        log_info "本地 git 仓库无 origin 远端, 跳过 (使用当前代码)"
    fi
else
    # 如果是空目录, 直接 clone
    if [[ -z "$(ls -A "${INSTALL_DIR}" 2>/dev/null)" ]]; then
        run git clone --branch "${YOUFU_BRANCH}" --depth 1 "${YOUFU_REPO}" "${INSTALL_DIR}"
    else
        log_error "${INSTALL_DIR} 非空且不是 git 仓库, 请手动清理后重试"
        exit 1
    fi
fi
log_ok "代码就绪 ($(git -C "${INSTALL_DIR}" rev-parse --short HEAD 2>/dev/null || echo 'no-commit'))"

# ---------- 4. Python venv + 依赖 ----------
log_step "4/7 Python 虚拟环境 + 依赖"
VENV_DIR="${INSTALL_DIR}/.venv"
if [[ ! -d "${VENV_DIR}" ]]; then
    log_info "创建 venv: ${VENV_DIR}"
    run_as_user "${YOUFU_USER}" python3 -m venv "${VENV_DIR}"
fi

log_info "升级 pip + 安装 requirements.txt"
run_as_user "${YOUFU_USER}" "${VENV_DIR}/bin/pip" install --quiet --upgrade pip wheel setuptools
run_as_user "${YOUFU_USER}" "${VENV_DIR}/bin/pip" install --quiet -r "${INSTALL_DIR}/requirements.txt"
log_ok "Python 依赖安装完成"

# ---------- 5. 前端 ----------
log_step "5/7 前端依赖 + 构建"
WEB_DIR="${INSTALL_DIR}/web"
if [[ ! -d "${WEB_DIR}" ]]; then
    log_error "找不到前端目录: ${WEB_DIR}"
    exit 1
fi

log_info "npm install"
run_as_user "${YOUFU_USER}" npm --prefix "${WEB_DIR}" install --no-audit --no-fund --silent
log_ok "前端依赖就绪"

log_info "npm run build"
run_as_user "${YOUFU_USER}" npm --prefix "${WEB_DIR}" run build
if [[ ! -f "${WEB_DIR}/dist/index.html" ]]; then
    log_error "前端构建失败, 缺 dist/index.html"
    exit 1
fi
log_ok "前端构建产物: ${WEB_DIR}/dist"

# ---------- 6. 配置 ----------
log_step "6/7 生成配置文件"
ENV_FILE="${INSTALL_DIR}/.env"
ENV_EXAMPLE="${INSTALL_DIR}/.env.example"
if [[ ! -f "${ENV_EXAMPLE}" ]]; then
    log_error "缺模板 ${ENV_EXAMPLE}"
    exit 1
fi
if [[ ! -f "${ENV_FILE}" ]]; then
    run cp "${ENV_EXAMPLE}" "${ENV_FILE}"
    run chmod 600 "${ENV_FILE}"
    run chown "${YOUFU_USER}:${YOUFU_USER}" "${ENV_FILE}" 2>/dev/null || true
    log_ok "已生成 .env (请编辑填入 MINIMAX_API_KEY 与 DASHSCOPE_API_KEY)"
else
    log_info ".env 已存在, 跳过 (内容保持不变)"
fi

# ---------- 7. 数据目录 + systemd ----------
log_step "7/7 数据目录 + 服务注册"

# 数据目录
run mkdir -p "${YOUFU_DATA_DIR}"/{uploads,chroma}
log_ok "数据目录: ${YOUFU_DATA_DIR}"

# 写配置文件端口 (若 config.yaml 仍是默认 8000)
CONFIG_FILE="${INSTALL_DIR}/config.yaml"
if [[ -f "${CONFIG_FILE}" ]] && grep -q "port: 8000" "${CONFIG_FILE}"; then
    log_info "config.yaml 端口已是 8000, 与 YOUFU_PORT 一致"
fi

# systemd?
INIT="$(detect_init)"
case "${INIT}" in
    systemd)
        UNIT_SRC="${SCRIPT_DIR}/youfu-known.service"
        UNIT_DST="/etc/systemd/system/${YOUFU_SERVICE_NAME}.service"
        if [[ -f "${UNIT_SRC}" ]]; then
            log_info "注册 systemd unit: ${UNIT_DST}"
            # 替换占位符
            TMP_UNIT="$(mktemp)"
            sed -e "s|@INSTALL_DIR@|${INSTALL_DIR}|g" \
                -e "s|@USER@|${YOUFU_USER}|g" \
                -e "s|@GROUP@|${YOUFU_USER}|g" \
                -e "s|@PORT@|${YOUFU_PORT}|g" \
                -e "s|@HOST@|${YOUFU_HOST}|g" \
                "${UNIT_SRC}" > "${TMP_UNIT}"
            run install -m 644 "${TMP_UNIT}" "${UNIT_DST}"
            rm -f "${TMP_UNIT}"
            run systemctl daemon-reload
            log_ok "systemd unit 已注册, 启动方式: sudo systemctl start ${YOUFU_SERVICE_NAME}"
            log_ok "或: bash ${SCRIPT_DIR}/start.sh (自动用 systemd)"
        else
            log_warn "缺 ${UNIT_SRC}, 跳过 systemd 注册, 用 start.sh 直接拉起"
        fi
        ;;
    *)
        log_info "未检测到 systemd, 安装完成后用 start.sh / stop.sh 管理"
        ;;
esac

hr "=" 60
log_ok "安装完成!"
echo
log_info "下一步:"
echo "    1. 编辑 ${ENV_FILE} 填入 MINIMAX_API_KEY / DASHSCOPE_API_KEY"
echo "    2. 启动服务: bash ${SCRIPT_DIR}/start.sh"
echo "    3. 浏览器访问: http://localhost:${YOUFU_PORT}/"
echo "    4. 查看状态: bash ${SCRIPT_DIR}/status.sh"
echo
log_info "升级: bash ${SCRIPT_DIR}/update.sh"
log_info "卸载: bash ${SCRIPT_DIR}/uninstall.sh"