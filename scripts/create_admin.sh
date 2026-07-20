#!/usr/bin/env bash
# =============================================================================
# create_admin.sh -- bootstrap an initial admin account via the API.
# =============================================================================
# Usage:
#   scripts/create_admin.sh                          # uses YOUFU_ADMIN_USERNAME / PASSWORD
#   scripts/create_admin.sh --reset-password         # always rotate
#
# Requires:
#   - .env at project root with YOUFU_ADMIN_USERNAME / YOUFU_ADMIN_PASSWORD
#   - service running on $BASE_URL (defaults to http://127.0.0.1:8000)
#
# Idempotent: if an admin already exists with the configured username,
# only --reset-password actually mutates the row.
# =============================================================================

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

if [[ -f .env ]]; then
    # shellcheck disable=SC1091
    set -a; source .env; set +a
fi

BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
USERNAME="${YOUFU_ADMIN_USERNAME:-admin}"
PASSWORD="${YOUFU_ADMIN_PASSWORD:?YOUFU_ADMIN_PASSWORD is required (set it in .env)}"

if [[ ! -x .venv/bin/python ]]; then
    echo "error: .venv not found at $PROJECT_ROOT/.venv" >&2
    exit 1
fi

.venv/bin/python - <<PY
"""Programmatic admin bootstrap.

Idempotent: if an admin already exists with the configured username,
nothing happens unless ``--reset-password`` was passed.
"""
import os
import sys
from pathlib import Path

# Make ``app`` importable.
sys.path.insert(0, str(Path("$PROJECT_ROOT").resolve()))

from app.auth.service import AuthService
from app.auth.storage import UserStore
from app.config import load_settings
from app.auth.security import hash_password

reset = "$1" == "--reset-password"

settings = load_settings()
store = UserStore(settings)
svc = AuthService(store=store, settings=settings)

existing = store.get_by_username("$USERNAME")
if existing is not None and not reset:
    print(f"admin '$USERNAME' already exists (id={existing.id}); pass --reset-password to rotate")
    sys.exit(0)

if existing is None:
    settings.auth.admin_username = "$USERNAME"
    settings.auth.admin_password = "$PASSWORD"
    user = svc.bootstrap_admin_if_empty() or store.create_user(
        username="$USERNAME",
        password_hash=hash_password("$PASSWORD", rounds=settings.auth.bcrypt_rounds),
        role="admin",
        is_active=True,
        is_approved=True,
    )
    print(f"created admin '{user.username}' (id={user.id})")
else:
    store.update_user(
        existing.id,
        password_hash=hash_password("$PASSWORD", rounds=settings.auth.bcrypt_rounds),
        is_active=True,
        is_approved=True,
        role="admin",
    )
    print(f"reset password for admin '{existing.username}' (id={existing.id})")
PY
