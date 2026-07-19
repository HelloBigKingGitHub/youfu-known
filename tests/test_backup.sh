#!/usr/bin/env bash
# tests/test_backup.sh
# Smoke tests for scripts/backup.sh + scripts/restore.sh.
#
# Run as: bash tests/test_backup.sh
# Exits non-zero on the first failing assertion.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
BACKUP_SH="${PROJECT_ROOT}/scripts/backup.sh"
RESTORE_SH="${PROJECT_ROOT}/scripts/restore.sh"

# -------- Harness helpers --------
PASS=0
FAIL=0
fail() { echo "[FAIL] $*"; FAIL=$((FAIL+1)); }
pass() { echo "[PASS] $*"; PASS=$((PASS+1)); }
expect_eq() {
    if [[ "$1" == "$2" ]]; then
        pass "$3"
    else
        fail "$3 (expected '$2', got '$1')"
    fi
}

# -------- Sandbox --------
TMP="$(mktemp -d)"
trap 'rm -rf "${TMP}"' EXIT

# Fake INSTALL_DIR layout: contains a storage/ subdir with a fake SQLite
# file + an uploads/ folder, plus a marker file at root for round-trip
# checks.
INSTALL="${TMP}/install"
mkdir -p "${INSTALL}/storage/uploads/kb-1"
mkdir -p "${INSTALL}/storage/chroma"
echo "fake-sqlite" > "${INSTALL}/storage/knowledge_base.sqlite3"
echo "fake-doc-bytes" > "${INSTALL}/storage/uploads/kb-1/doc-1.txt"
echo "fake-vector"   > "${INSTALL}/storage/chroma/index.bin"
echo "marker"        > "${INSTALL}/MARKER"
mkdir -p "${INSTALL}/logs"

# Make the script's helpers resolvable: backup.sh sources
# scripts/lib/common.sh.  The sandbox uses ${PROJECT_ROOT}/scripts so
# no copy needed.

# -------- Case 1: backup produces a tar.gz containing storage/ --------
export YOUFU_INSTALL_DIR="${INSTALL}"
export YOUFU_BACKUP_DIR="${INSTALL}/backups"

bash "${BACKUP_SH}" >/dev/null
GLOB=$(ls "${YOUFU_BACKUP_DIR}"/backup-*.tar.gz 2>/dev/null || true)
if [[ -n "${GLOB}" ]]; then
    pass "backup script produced a tar.gz"
else
    fail "no backup file produced under ${YOUFU_BACKUP_DIR}"
    exit 1
fi
BACKUP_FILE="${GLOB}"

# -------- Case 2: tar.gz contains the storage/ subdir + correct files --------
TAR_CONTENTS=$(tar -tzf "${BACKUP_FILE}")
if echo "${TAR_CONTENTS}" | grep -q "^storage/knowledge_base.sqlite3$"; then
    pass "tar contains storage/knowledge_base.sqlite3"
else
    fail "tar missing storage/knowledge_base.sqlite3"
fi
if echo "${TAR_CONTENTS}" | grep -q "^storage/uploads/kb-1/doc-1.txt$"; then
    pass "tar contains uploads/"
else
    fail "tar missing uploads/"
fi
if echo "${TAR_CONTENTS}" | grep -q "^storage/chroma/index.bin$"; then
    pass "tar contains chroma/"
else
    fail "tar missing chroma/"
fi

# -------- Case 3: chroma-tmp is excluded --------
mkdir -p "${INSTALL}/storage/chroma-tmp"
echo "tmp" > "${INSTALL}/storage/chroma-tmp/junk"
bash "${BACKUP_SH}" >/dev/null
LATEST=$(ls -t "${YOUFU_BACKUP_DIR}"/backup-*.tar.gz | head -1)
if tar -tzf "${LATEST}" | grep -q "^storage/chroma-tmp/"; then
    fail "chroma-tmp should be excluded from the archive"
else
    pass "chroma-tmp is excluded"
fi

# -------- Case 4: retention keeps at most KEEP_DAILY recent backups --------
export YOUFU_KEEP_DAILY=3
export YOUFU_KEEP_WEEKLY=2
# Drop any prior backups and start fresh
rm -f "${YOUFU_BACKUP_DIR}"/backup-*.tar.gz
for i in 1 2 3 4 5; do
    sleep 1   # ensure distinct mtime
    bash "${BACKUP_SH}" >/dev/null
done
COUNT=$(ls "${YOUFU_BACKUP_DIR}"/backup-*.tar.gz | wc -l)
expect_eq "${COUNT}" "3" "retention caps at KEEP_DAILY=3"

# -------- Case 5: restore round-trip --------
# Wipe storage and run restore --latest.
rm -rf "${INSTALL}/storage"
if bash "${RESTORE_SH}" --latest >/dev/null 2>&1; then
    pass "restore --latest exited 0"
else
    fail "restore --latest exited non-zero"
fi
if [[ -f "${INSTALL}/storage/knowledge_base.sqlite3" ]]; then
    pass "restore re-created knowledge_base.sqlite3"
else
    fail "restore did not recreate storage/knowledge_base.sqlite3"
fi
if [[ "$(cat "${INSTALL}/storage/uploads/kb-1/doc-1.txt")" == "fake-doc-bytes" ]]; then
    pass "restore preserved uploads/"
else
    fail "restore corrupted uploads/"
fi

# -------- Case 6: restore rejects missing backup --------
if bash "${RESTORE_SH}" /nonexistent/file.tar.gz >/dev/null 2>&1; then
    fail "restore should fail on nonexistent file"
else
    pass "restore fails on nonexistent file"
fi

# -------- Summary --------
echo
echo "backup test summary: ${PASS} passed, ${FAIL} failed"
if (( FAIL > 0 )); then
    exit 1
fi
exit 0