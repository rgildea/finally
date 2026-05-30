import pytest

from app.db import database as db_module
from app.db.database import get_connection, get_watchlist_tickers, init_db


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "test.db")


def test_init_creates_tables():
    init_db()
    con = get_connection()
    rows = con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    con.close()
    names = {row["name"] for row in rows}
    for table in ["users_profile", "watchlist", "positions", "trades", "portfolio_snapshots", "chat_messages"]:
        assert table in names, f"Missing table: {table}"


def test_init_idempotent():
    init_db()
    init_db()  # should not raise


def test_seed_data():
    init_db()
    con = get_connection()
    profile = con.execute("SELECT * FROM users_profile WHERE id='default'").fetchone()
    assert profile is not None
    assert profile["cash_balance"] == 10000.0
    count = con.execute("SELECT COUNT(*) FROM watchlist WHERE user_id='default'").fetchone()[0]
    assert count == 10
    con.close()


def test_seed_idempotent():
    init_db()
    init_db()
    con = get_connection()
    count = con.execute("SELECT COUNT(*) FROM watchlist WHERE user_id='default'").fetchone()[0]
    assert count == 10
    con.close()


def test_cash_balance_preserved():
    init_db()
    con = get_connection()
    con.execute("UPDATE users_profile SET cash_balance=5000.0 WHERE id='default'")
    con.commit()
    con.close()
    init_db()
    con = get_connection()
    profile = con.execute("SELECT cash_balance FROM users_profile WHERE id='default'").fetchone()
    assert profile["cash_balance"] == 5000.0
    con.close()


def test_get_watchlist_tickers():
    init_db()
    tickers = get_watchlist_tickers()
    assert isinstance(tickers, list)
    assert len(tickers) == 10
    assert "AAPL" in tickers


def test_busy_timeout_set():
    con = get_connection()
    try:
        result = con.execute("PRAGMA busy_timeout").fetchone()[0]
        assert result == 5000
    finally:
        con.close()
