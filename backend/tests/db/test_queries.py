"""Tests for each query function and upsert/trade edge cases."""


from app.db import queries


# --- profile -------------------------------------------------------------


async def test_set_and_get_cash_balance(db):
    await queries.set_cash_balance(1234.56)
    assert (await queries.get_profile())["cash_balance"] == 1234.56


# --- watchlist -----------------------------------------------------------


async def test_add_watchlist_appends_to_end(db):
    await queries.add_watchlist("PYPL")
    assert (await queries.list_watchlist())[-1] == "PYPL"


async def test_add_watchlist_ignores_duplicate(db):
    before = await queries.list_watchlist()
    await queries.add_watchlist("AAPL")
    assert await queries.list_watchlist() == before


async def test_remove_watchlist(db):
    await queries.remove_watchlist("AAPL")
    assert "AAPL" not in await queries.list_watchlist()


async def test_remove_watchlist_missing_is_noop(db):
    before = await queries.list_watchlist()
    await queries.remove_watchlist("ZZZZ")
    assert await queries.list_watchlist() == before


# --- positions -----------------------------------------------------------


async def test_get_position_none_when_absent(db):
    assert await queries.get_position("AAPL") is None


async def test_upsert_inserts_then_updates(db):
    await queries.upsert_position("AAPL", 10.0, 190.0)
    pos = await queries.get_position("AAPL")
    assert pos == {"ticker": "AAPL", "quantity": 10.0, "avg_cost": 190.0}

    await queries.upsert_position("AAPL", 15.0, 191.5)
    pos = await queries.get_position("AAPL")
    assert pos == {"ticker": "AAPL", "quantity": 15.0, "avg_cost": 191.5}

    positions = await queries.list_positions()
    assert len([p for p in positions if p["ticker"] == "AAPL"]) == 1


async def test_list_positions_sorted_by_ticker(db):
    await queries.upsert_position("TSLA", 1.0, 200.0)
    await queries.upsert_position("AAPL", 1.0, 190.0)
    tickers = [p["ticker"] for p in await queries.list_positions()]
    assert tickers == ["AAPL", "TSLA"]


async def test_delete_position(db):
    await queries.upsert_position("AAPL", 10.0, 190.0)
    await queries.delete_position("AAPL")
    assert await queries.get_position("AAPL") is None


# --- trades --------------------------------------------------------------


async def test_insert_trade_returns_row(db):
    trade = await queries.insert_trade("AAPL", "buy", 10.0, 190.0)
    assert trade["ticker"] == "AAPL"
    assert trade["side"] == "buy"
    assert trade["quantity"] == 10.0
    assert trade["price"] == 190.0
    assert trade["id"]
    assert trade["executed_at"]


async def test_list_trades_newest_first_and_limit(db):
    for i in range(5):
        await queries.insert_trade("AAPL", "buy", float(i + 1), 100.0)
    trades = await queries.list_trades(limit=3)
    assert len(trades) == 3
    quantities = [t["quantity"] for t in trades]
    assert quantities == [5.0, 4.0, 3.0]


# --- snapshots -----------------------------------------------------------


async def test_snapshots_oldest_first_and_limit(db):
    for v in [100.0, 200.0, 300.0]:
        await queries.insert_snapshot(v)
    snapshots = await queries.list_snapshots(limit=2)
    assert len(snapshots) == 2
    values = [s["total_value"] for s in snapshots]
    assert values == [200.0, 300.0]
    assert set(snapshots[0].keys()) == {"recorded_at", "total_value"}


# --- chat ----------------------------------------------------------------


async def test_chat_roundtrip_with_actions(db):
    actions = {"trades": [{"ticker": "AAPL", "side": "buy", "quantity": 10}]}
    row = await queries.insert_chat_message("assistant", "Bought.", actions)
    assert row["actions"] == actions

    messages = await queries.list_chat_messages()
    assert messages[-1]["content"] == "Bought."
    assert messages[-1]["actions"] == actions


async def test_chat_null_actions(db):
    await queries.insert_chat_message("user", "Hi", None)
    messages = await queries.list_chat_messages()
    assert messages[-1]["actions"] is None


async def test_chat_oldest_first_and_limit(db):
    for i in range(5):
        await queries.insert_chat_message("user", f"msg{i}", None)
    messages = await queries.list_chat_messages(limit=3)
    contents = [m["content"] for m in messages]
    assert contents == ["msg2", "msg3", "msg4"]
