#!/usr/bin/env bash
# scripts/backup.sh
# 备份 storage/ 到 backups/, 保留 7 天 + 4 个周日
#
# 用法:
#   bash scripts/backup.sh
#
# 环境变量 (可选):
#   YOUFU_INSTALL_DIR  - 安装根目录 (默认 /home/youfu/youfu-known)
#   YOUFU_BACKUP_DIR   - 备份输出目录 (默认 <install>/backups)
#   YOUFU_KEEP_DAILY   - 保留最近天数 (默认 7)
#   YOUFU_KEEP_WEEKLY  - 保留周日备份数 (默认 4)
#
# 输出: <backup>/backup-YYYYMMDD-HHMMSS.tar.gz

set -o pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"

# -------- 配置 --------
INSTALL_DIR="${YOUFU_INSTALL_DIR:-/home/youfu/youfu-known}"
BACKUP_DIR="${YOUFU_BACKUP_DIR:-${INSTALL_DIR}/backups}"
KEEP_DAILY="${YOUFU_KEEP_DAILY:-7}"
KEEP_WEEKLY="${YOUFU_KEEP_WEEKLY:-4}"

# -------- 校验 --------
if [[ ! -d "${INSTALL_DIR}" ]]; then
    log_error "INSTALL_DIR 不存在: ${INSTALL_DIR}"
    exit 1
fi
if [[ ! -d "${INSTALL_DIR}/storage" ]]; then
    log_error "storage/ 不存在: ${INSTALL_DIR}/storage"
    exit 1
fi
require_cmd tar || exit 1
require_cmd find || exit 1

mkdir -p "${BACKUP_DIR}"

TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_FILE="${BACKUP_DIR}/backup-${TIMESTAMP}.tar.gz"

log_step "开始备份"
log_info "来源: ${INSTALL_DIR}/storage"
log_info "目标: ${BACKUP_FILE}"

# -------- 打包 --------
# 排除 chroma-tmp (Chroma 临时文件, 损坏也能重新生成)
if ! tar -czf "${BACKUP_FILE}" \
        -C "${INSTALL_DIR}" \
        --exclude='storage/chroma-tmp' \
        storage/ 2>/tmp/youfu-backup.err; then
    log_error "tar 失败:"
    sed 's/^/    /' /tmp/youfu-backup.err >&2
    rm -f /tmp/youfu-backup.err
    exit 1
fi
rm -f /tmp/youfu-backup.err

BACKUP_SIZE=$(du -h "${BACKUP_FILE}" | cut -f1)
log_ok "备份完成: ${BACKUP_FILE} (${BACKUP_SIZE})"

# -------- 清理旧备份 --------
# 规则:
#   - 保留最近 KEEP_DAILY 个文件 (按修改时间)
#   - 周日备份额外保留 (按内容时间戳判断), 最多 KEEP_WEEKLY 个
log_info "清理策略: 保留最近 ${KEEP_DAILY} 天 + ${KEEP_WEEKLY} 个周日备份"

# 把所有备份按修改时间排序 (旧 -> 新), 然后丢掉除最近 KEEP_DAILY 个之外的全部
ALL_BACKUPS=$(find "${BACKUP_DIR}" -name 'backup-*.tar.gz' -type f -printf '%T@\t%p\n' | sort -n | cut -f2-)
COUNT=$(echo "${ALL_BACKUPS}" | grep -c . || true)

if (( COUNT > KEEP_DAILY )); then
    DROP_COUNT=$((COUNT - KEEP_DAILY))
    DROP_LIST=$(echo "${ALL_BACKUPS}" | head -n "${DROP_COUNT}")
    while IFS= read -r f; do
        [[ -z "${f}" ]] && continue
        # 周日备份额外保留: 从文件名解析日期, 检查 weekday
        is_sunday="false"
        if [[ "${f}" =~ backup-([0-9]{4})([0-9]{2})([0-9]{2})-([0-9]{2})([0-9]{2})([0-9]{2})\.tar\.gz$ ]]; then
            date_str="${BASH_REMATCH[1]}-${BASH_REMATCH[2]}-${BASH_REMATCH[3]}"
            weekday=$(date -d "${date_str}" +%u 2>/dev/null || echo 8)
            if [[ "${weekday}" -eq 7 ]]; then
                # 计算比这个周日更新的周日备份数
                newer_count=$(find "${BACKUP_DIR}" -name 'backup-*.tar.gz' -type f \
                    -newermt "${date_str}" -printf '%T@\t%p\n' | sort -n | cut -f2- \
                    | while IFS= read -r nf; do
                        if [[ "${nf}" =~ backup-([0-9]{4})([0-9]{2})([0-9]{2})-([0-9]{2})([0-9]{2})([0-9]{2})\.tar\.gz$ ]]; then
                            ndate="${BASH_REMATCH[1]}-${BASH_REMATCH[2]}-${BASH_REMATCH[3]}"
                            nweekday=$(date -d "${ndate}" +%u 2>/dev/null || echo 8)
                            if [[ "${nweekday}" -eq 7 ]]; then
                                echo "${nf}"
                            fi
                        fi
                    done | wc -l)
                if (( newer_count < KEEP_WEEKLY )); then
                    is_sunday="true"
                fi
            fi
        fi
        if [[ "${is_sunday}" == "true" ]]; then
            log_info "保留周日备份: $(basename "${f}")"
        else
            log_info "删除旧备份: $(basename "${f}")"
            rm -f "${f}"
        fi
    done <<< "${DROP_LIST}"
fi

REMAINING=$(find "${BACKUP_DIR}" -name 'backup-*.tar.gz' -type f | wc -l)
log_ok "清理完成, 当前保留 ${REMAINING} 个备份"