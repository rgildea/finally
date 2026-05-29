import sqlite3
import uuid
from datetime import datetime, timezone

SEED_TICKERS = ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "NVDA", "META", "JPM", "V", "NFLX"]


def seed(con: sqlite3.Connection) -> None:
    """Insert default user profile and watchlist tickers using INSERT OR IGNORE."""
    now = datetime.now(timezone.utc).isoformat()
    con.execute(
        "INSERT OR IGNORE INTO users_profile (id, cash_balance, created_at) VALUES (?, ?, ?)",
        ("default", 10000.0, now),
    )
    for ticker in SEED_TICKERS:
        con.execute(
            "INSERT OR IGNORE INTO watchlist (id, user_id, ticker, added_at) VALUES (?, ?, ?, ?)",
            (str(uuid.uuid4()), "default", ticker, now),
        )
