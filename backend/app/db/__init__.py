"""Database layer: connection lifecycle and async query functions."""

from .connection import DB_PATH, close_db, get_db, init_db
from .queries import (
    add_watchlist,
    delete_position,
    get_position,
    get_profile,
    insert_chat_message,
    insert_snapshot,
    insert_trade,
    list_chat_messages,
    list_positions,
    list_snapshots,
    list_trades,
    list_watchlist,
    remove_watchlist,
    set_cash_balance,
    upsert_position,
)

__all__ = [
    "DB_PATH",
    "init_db",
    "get_db",
    "close_db",
    "get_profile",
    "set_cash_balance",
    "list_watchlist",
    "add_watchlist",
    "remove_watchlist",
    "list_positions",
    "get_position",
    "upsert_position",
    "delete_position",
    "insert_trade",
    "list_trades",
    "insert_snapshot",
    "list_snapshots",
    "insert_chat_message",
    "list_chat_messages",
]
