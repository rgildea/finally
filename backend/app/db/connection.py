"""Shared aiosqlite connection with lazy initialization and seeding."""

import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import aiosqlite

from .schema import (
    DEFAULT_CASH_BALANCE,
    DEFAULT_USER_ID,
    DEFAULT_WATCHLIST,
    SCHEMA_SQL,
)

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
DB_PATH = os.getenv("FINALLY_DB_PATH", str(_PROJECT_ROOT / "db" / "finally.db"))

_connection: aiosqlite.Connection | None = None


def _now() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


async def get_db() -> aiosqlite.Connection:
    """Return the shared connection, opening and initializing it on first use."""
    global _connection
    if _connection is None:
        await init_db()
    assert _connection is not None
    return _connection


async def init_db() -> None:
    """Open the connection, create tables, and seed defaults if empty.

    Idempotent: safe to call repeatedly. Tables use ``IF NOT EXISTS`` and
    seeding is skipped when a profile already exists.
    """
    global _connection
    if _connection is None:
        Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
        _connection = await aiosqlite.connect(DB_PATH)
        _connection.row_factory = aiosqlite.Row
        await _connection.execute("PRAGMA foreign_keys = ON")
    await _connection.executescript(SCHEMA_SQL)
    await _connection.commit()
    await _seed_if_empty(_connection)


async def _seed_if_empty(db: aiosqlite.Connection) -> None:
    """Insert the default profile and watchlist when the profile is absent."""
    async with db.execute(
        "SELECT 1 FROM users_profile WHERE id = ?", (DEFAULT_USER_ID,)
    ) as cursor:
        if await cursor.fetchone() is not None:
            return

    now = _now()
    await db.execute(
        "INSERT INTO users_profile (id, cash_balance, created_at) VALUES (?, ?, ?)",
        (DEFAULT_USER_ID, DEFAULT_CASH_BALANCE, now),
    )
    await db.executemany(
        "INSERT INTO watchlist (id, user_id, ticker, added_at) VALUES (?, ?, ?, ?)",
        [
            (str(uuid4()), DEFAULT_USER_ID, ticker, now)
            for ticker in DEFAULT_WATCHLIST
        ],
    )
    await db.commit()


async def close_db() -> None:
    """Close the shared connection if open."""
    global _connection
    if _connection is not None:
        await _connection.close()
        _connection = None
