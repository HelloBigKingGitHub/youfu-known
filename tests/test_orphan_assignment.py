"""Tests for the orphan-row migration helpers.

KBs and chat_turns created before the auth module shipped end up with
``owner_id IS NULL`` / ``user_id IS NULL``. The lifespan runs the
assignment helpers on every boot so the per-user visibility filter
can resolve those rows. These tests pin the contract:

* Rows with NULL owner are stamped to the supplied admin.
* Rows with a non-NULL owner are left alone.
* Running the helper twice is a no-op the second time.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.kb.models import ChatTurn
from app.kb.storage import (
    SQLiteStorage,
    assign_orphan_chats_to_admin,
    assign_orphan_kbs_to_admin,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _make_kb(storage: SQLiteStorage, name: str) -> str:
    return storage.create_kb(name=name).id


def _get_kb_owner(storage: SQLiteStorage, kb_id: str) -> str | None:
    """Read ``owner_id`` straight from SQLite (the model doesn't
    expose it on purpose; the KB layer carries ownership via raw SQL)."""
    with storage._connect() as conn:  # type: ignore[attr-defined]
        row = conn.execute(
            "SELECT owner_id FROM knowledge_bases WHERE id = ?", (kb_id,)
        ).fetchone()
    return row["owner_id"] if row else None


def _get_chat_user(storage: SQLiteStorage, turn_id: str) -> str | None:
    with storage._connect() as conn:  # type: ignore[attr-defined]
        row = conn.execute(
            "SELECT user_id FROM chat_turns WHERE id = ?", (turn_id,)
        ).fetchone()
    return row["user_id"] if row else None


def _stamp_kb_owner(storage: SQLiteStorage, kb_id: str, owner: str) -> None:
    with storage._connect() as conn:  # type: ignore[attr-defined]
        conn.execute(
            "UPDATE knowledge_bases SET owner_id = ? WHERE id = ?",
            (owner, kb_id),
        )
        conn.commit()


def test_assigns_orphan_kb_to_admin(sqlite_storage: SQLiteStorage) -> None:
    """A KB with NULL owner is restamped to the admin user id."""
    kb_id = _make_kb(sqlite_storage, "orphan")
    assert _get_kb_owner(sqlite_storage, kb_id) is None

    fixed = assign_orphan_kbs_to_admin(sqlite_storage, "admin-1")
    assert fixed == 1

    assert _get_kb_owner(sqlite_storage, kb_id) == "admin-1"


def test_leaves_owned_kbs_alone(sqlite_storage: SQLiteStorage) -> None:
    """A KB whose owner is already set is not overwritten."""
    kb_id = _make_kb(sqlite_storage, "owned")
    _stamp_kb_owner(sqlite_storage, kb_id, "alice")

    fixed = assign_orphan_kbs_to_admin(sqlite_storage, "admin-1")
    assert fixed == 0
    assert _get_kb_owner(sqlite_storage, kb_id) == "alice"


def test_assigns_only_orphans_in_mixed_set(
    sqlite_storage: SQLiteStorage,
) -> None:
    """When some KBs are owned and others aren't, only the orphans move."""
    owned = _make_kb(sqlite_storage, "owned-mix")
    orphan_a = _make_kb(sqlite_storage, "orphan-a")
    orphan_b = _make_kb(sqlite_storage, "orphan-b")
    _stamp_kb_owner(sqlite_storage, owned, "alice")

    fixed = assign_orphan_kbs_to_admin(sqlite_storage, "admin-1")
    assert fixed == 2

    assert _get_kb_owner(sqlite_storage, owned) == "alice"
    assert _get_kb_owner(sqlite_storage, orphan_a) == "admin-1"
    assert _get_kb_owner(sqlite_storage, orphan_b) == "admin-1"


def test_orphan_kb_assignment_is_idempotent(
    sqlite_storage: SQLiteStorage,
) -> None:
    """Running the helper twice is a no-op the second time."""
    kb_id = _make_kb(sqlite_storage, "twice")
    assert assign_orphan_kbs_to_admin(sqlite_storage, "admin-1") == 1
    assert assign_orphan_kbs_to_admin(sqlite_storage, "admin-1") == 0
    assert _get_kb_owner(sqlite_storage, kb_id) == "admin-1"


def test_assigns_orphan_chat_to_admin(sqlite_storage: SQLiteStorage) -> None:
    """A chat_turn with NULL user is restamped to the admin user id."""
    kb_id = _make_kb(sqlite_storage, "chat-host")
    turn = ChatTurn(
        id="turn-orphan-1",
        kb_id=kb_id,
        question="hi",
        answer="hello",
        status="ready",
        user_id="placeholder",  # required at construction; cleared by SQL below
        created_at=_utcnow(),
    )
    sqlite_storage.save_chat_turn(turn)
    # Force the user_id to NULL so the migration actually has work to do.
    with sqlite_storage._connect() as conn:  # type: ignore[attr-defined]
        conn.execute(
            "UPDATE chat_turns SET user_id = NULL WHERE id = ?", (turn.id,)
        )
        conn.commit()

    fixed = assign_orphan_chats_to_admin(sqlite_storage, "admin-1")
    assert fixed == 1

    assert _get_chat_user(sqlite_storage, turn.id) == "admin-1"


def test_leaves_owned_chats_alone(sqlite_storage: SQLiteStorage) -> None:
    """A chat_turn with a non-NULL user_id is not overwritten."""
    kb_id = _make_kb(sqlite_storage, "owned-chat-host")
    turn = ChatTurn(
        id="turn-owned-1",
        kb_id=kb_id,
        question="hi",
        answer="hello",
        status="ready",
        user_id="alice",  # pre-stamped so the migration leaves it alone
        created_at=_utcnow(),
    )
    sqlite_storage.save_chat_turn(turn)

    fixed = assign_orphan_chats_to_admin(sqlite_storage, "admin-1")
    assert fixed == 0
    assert _get_chat_user(sqlite_storage, turn.id) == "alice"


def test_orphan_chat_assignment_is_idempotent(
    sqlite_storage: SQLiteStorage,
) -> None:
    """Running the helper twice is a no-op the second time."""
    kb_id = _make_kb(sqlite_storage, "twice-chat-host")
    turn = ChatTurn(
        id="turn-twice-1",
        kb_id=kb_id,
        question="hi",
        answer="hello",
        status="ready",
        user_id="placeholder",
        created_at=_utcnow(),
    )
    sqlite_storage.save_chat_turn(turn)
    with sqlite_storage._connect() as conn:  # type: ignore[attr-defined]
        conn.execute(
            "UPDATE chat_turns SET user_id = NULL WHERE id = ?", (turn.id,)
        )
        conn.commit()

    assert assign_orphan_chats_to_admin(sqlite_storage, "admin-1") == 1
    assert assign_orphan_chats_to_admin(sqlite_storage, "admin-1") == 0


def test_assigns_both_kb_and_chat_in_one_pass(
    sqlite_storage: SQLiteStorage,
) -> None:
    """A typical pre-auth DB has orphans in both tables; both are fixed."""
    kb_id = _make_kb(sqlite_storage, "combined")
    turn = ChatTurn(
        id="turn-combined-1",
        kb_id=kb_id,
        question="hi",
        answer="hello",
        status="ready",
        user_id="placeholder",
        created_at=_utcnow(),
    )
    sqlite_storage.save_chat_turn(turn)
    with sqlite_storage._connect() as conn:  # type: ignore[attr-defined]
        conn.execute(
            "UPDATE chat_turns SET user_id = NULL WHERE id = ?", (turn.id,)
        )
        conn.commit()

    assert assign_orphan_kbs_to_admin(sqlite_storage, "admin-1") == 1
    assert assign_orphan_chats_to_admin(sqlite_storage, "admin-1") == 1

    assert _get_kb_owner(sqlite_storage, kb_id) == "admin-1"
    assert _get_chat_user(sqlite_storage, turn.id) == "admin-1"
