"""Async query functions returning plain dicts. Contract CONTRACT.md section 2.

All queries operate on the single hardcoded ``"default"`` user.
"""

import json
from uuid import uuid4

from .connection import _now, get_db
from .schema import DEFAULT_USER_ID

_USER = DEFAULT_USER_ID


# --- profile -------------------------------------------------------------


async def get_profile() -> dict:
    """Return the user's profile as ``{"cash_balance": float}``."""
    db = await get_db()
    async with db.execute(
        "SELECT cash_balance FROM users_profile WHERE id = ?", (_USER,)
    ) as cursor:
        row = await cursor.fetchone()
    return {"cash_balance": row["cash_balance"]}


async def set_cash_balance(balance: float) -> None:
    """Set the user's cash balance."""
    db = await get_db()
    await db.execute(
        "UPDATE users_profile SET cash_balance = ? WHERE id = ?",
        (balance, _USER),
    )
    await db.commit()


# --- watchlist -----------------------------------------------------------


async def list_watchlist() -> list[str]:
    """Return watchlist tickers ordered by when they were added."""
    db = await get_db()
    async with db.execute(
        "SELECT ticker FROM watchlist WHERE user_id = ? ORDER BY added_at, rowid",
        (_USER,),
    ) as cursor:
        rows = await cursor.fetchall()
    return [row["ticker"] for row in rows]


async def add_watchlist(ticker: str) -> None:
    """Add a ticker to the watchlist, ignoring if it already exists."""
    db = await get_db()
    await db.execute(
        "INSERT OR IGNORE INTO watchlist (id, user_id, ticker, added_at) "
        "VALUES (?, ?, ?, ?)",
        (str(uuid4()), _USER, ticker, _now()),
    )
    await db.commit()


async def remove_watchlist(ticker: str) -> None:
    """Remove a ticker from the watchlist."""
    db = await get_db()
    await db.execute(
        "DELETE FROM watchlist WHERE user_id = ? AND ticker = ?",
        (_USER, ticker),
    )
    await db.commit()


# --- positions -----------------------------------------------------------


async def list_positions() -> list[dict]:
    """Return all positions as ``[{ticker, quantity, avg_cost}]``."""
    db = await get_db()
    async with db.execute(
        "SELECT ticker, quantity, avg_cost FROM positions WHERE user_id = ? "
        "ORDER BY ticker",
        (_USER,),
    ) as cursor:
        rows = await cursor.fetchall()
    return [dict(row) for row in rows]


async def get_position(ticker: str) -> dict | None:
    """Return a single position or ``None`` if not held."""
    db = await get_db()
    async with db.execute(
        "SELECT ticker, quantity, avg_cost FROM positions "
        "WHERE user_id = ? AND ticker = ?",
        (_USER, ticker),
    ) as cursor:
        row = await cursor.fetchone()
    return dict(row) if row else None


async def upsert_position(ticker: str, quantity: float, avg_cost: float) -> None:
    """Insert or update a position keyed by ticker."""
    db = await get_db()
    await db.execute(
        "INSERT INTO positions (id, user_id, ticker, quantity, avg_cost, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT (user_id, ticker) DO UPDATE SET "
        "quantity = excluded.quantity, avg_cost = excluded.avg_cost, "
        "updated_at = excluded.updated_at",
        (str(uuid4()), _USER, ticker, quantity, avg_cost, _now()),
    )
    await db.commit()


async def delete_position(ticker: str) -> None:
    """Remove a position (e.g. fully sold)."""
    db = await get_db()
    await db.execute(
        "DELETE FROM positions WHERE user_id = ? AND ticker = ?",
        (_USER, ticker),
    )
    await db.commit()


# --- trades --------------------------------------------------------------


async def insert_trade(
    ticker: str, side: str, quantity: float, price: float
) -> dict:
    """Append a trade to the log and return the inserted row."""
    db = await get_db()
    trade_id = str(uuid4())
    executed_at = _now()
    await db.execute(
        "INSERT INTO trades (id, user_id, ticker, side, quantity, price, executed_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (trade_id, _USER, ticker, side, quantity, price, executed_at),
    )
    await db.commit()
    return {
        "id": trade_id,
        "user_id": _USER,
        "ticker": ticker,
        "side": side,
        "quantity": quantity,
        "price": price,
        "executed_at": executed_at,
    }


async def list_trades(limit: int = 100) -> list[dict]:
    """Return the most recent trades, newest first."""
    db = await get_db()
    async with db.execute(
        "SELECT id, ticker, side, quantity, price, executed_at FROM trades "
        "WHERE user_id = ? ORDER BY executed_at DESC, rowid DESC LIMIT ?",
        (_USER, limit),
    ) as cursor:
        rows = await cursor.fetchall()
    return [dict(row) for row in rows]


# --- snapshots -----------------------------------------------------------


async def insert_snapshot(total_value: float) -> None:
    """Record a portfolio value snapshot."""
    db = await get_db()
    await db.execute(
        "INSERT INTO portfolio_snapshots (id, user_id, total_value, recorded_at) "
        "VALUES (?, ?, ?, ?)",
        (str(uuid4()), _USER, total_value, _now()),
    )
    await db.commit()


async def list_snapshots(limit: int = 500) -> list[dict]:
    """Return recent snapshots as ``[{recorded_at, total_value}]``, oldest first."""
    db = await get_db()
    async with db.execute(
        "SELECT recorded_at, total_value FROM ("
        "  SELECT recorded_at, total_value, rowid AS rid FROM portfolio_snapshots "
        "  WHERE user_id = ? ORDER BY recorded_at DESC, rid DESC LIMIT ?"
        ") ORDER BY recorded_at ASC, rid ASC",
        (_USER, limit),
    ) as cursor:
        rows = await cursor.fetchall()
    return [dict(row) for row in rows]


# --- chat ----------------------------------------------------------------


async def insert_chat_message(
    role: str, content: str, actions: dict | None
) -> dict:
    """Persist a chat message and return the inserted row.

    ``actions`` is JSON-encoded for storage and returned as the original dict.
    """
    db = await get_db()
    message_id = str(uuid4())
    created_at = _now()
    actions_json = json.dumps(actions) if actions is not None else None
    await db.execute(
        "INSERT INTO chat_messages (id, user_id, role, content, actions, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (message_id, _USER, role, content, actions_json, created_at),
    )
    await db.commit()
    return {
        "id": message_id,
        "user_id": _USER,
        "role": role,
        "content": content,
        "actions": actions,
        "created_at": created_at,
    }


async def list_chat_messages(limit: int = 20) -> list[dict]:
    """Return the most recent chat messages, oldest first.

    ``actions`` is decoded from JSON back into a dict (or ``None``).
    """
    db = await get_db()
    async with db.execute(
        "SELECT id, role, content, actions, created_at FROM ("
        "  SELECT id, role, content, actions, created_at, rowid AS rid "
        "  FROM chat_messages "
        "  WHERE user_id = ? ORDER BY created_at DESC, rid DESC LIMIT ?"
        ") ORDER BY created_at ASC, rid ASC",
        (_USER, limit),
    ) as cursor:
        rows = await cursor.fetchall()
    messages = []
    for row in rows:
        message = dict(row)
        message["actions"] = (
            json.loads(message["actions"]) if message["actions"] else None
        )
        messages.append(message)
    return messages
