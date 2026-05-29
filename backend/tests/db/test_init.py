"""Tests for lazy init, seeding, and idempotency."""


from app.db import connection, queries
from app.db.schema import DEFAULT_CASH_BALANCE, DEFAULT_WATCHLIST


async def test_init_seeds_profile_and_watchlist(db):
    profile = await queries.get_profile()
    assert profile["cash_balance"] == DEFAULT_CASH_BALANCE

    watchlist = await queries.list_watchlist()
    assert watchlist == DEFAULT_WATCHLIST


async def test_init_is_idempotent(db):
    await connection.init_db()
    await connection.init_db()

    watchlist = await queries.list_watchlist()
    assert watchlist == DEFAULT_WATCHLIST
    assert len(watchlist) == len(set(watchlist))


async def test_seed_skipped_when_data_modified(db):
    await queries.set_cash_balance(5000.0)
    await queries.remove_watchlist("AAPL")

    await connection.init_db()

    profile = await queries.get_profile()
    assert profile["cash_balance"] == 5000.0
    assert "AAPL" not in await queries.list_watchlist()


async def test_get_db_lazily_initializes(tmp_path, monkeypatch):
    db_file = tmp_path / "lazy.db"
    monkeypatch.setattr(connection, "DB_PATH", str(db_file))
    monkeypatch.setattr(connection, "_connection", None)

    conn = await connection.get_db()
    assert conn is not None
    profile = await queries.get_profile()
    assert profile["cash_balance"] == DEFAULT_CASH_BALANCE

    await connection.close_db()


async def test_close_db_resets_connection(db):
    await connection.close_db()
    assert connection._connection is None
