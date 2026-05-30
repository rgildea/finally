import os
import sqlite3
from pathlib import Path

from app.db.schema import CREATE_TABLES
from app.db.seed import seed

DB_PATH = Path(os.getenv("DB_PATH", "db/finally.db"))


def get_connection() -> sqlite3.Connection:
    """Return a SQLite connection with WAL mode and foreign keys enabled."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA busy_timeout=5000")
    return con


def get_watchlist_tickers() -> list[str]:
    """Return current watchlist tickers for the default user, re-queried each call."""
    con = get_connection()
    try:
        rows = con.execute(
            "SELECT ticker FROM watchlist WHERE user_id = 'default' ORDER BY added_at"
        ).fetchall()
        return [row["ticker"] for row in rows]
    finally:
        con.close()


def init_db() -> None:
    """Create tables and seed default data if not already present."""
    con = get_connection()
    try:
        with con:
            for ddl in CREATE_TABLES:
                con.execute(ddl)
            seed(con)
    finally:
        con.close()
