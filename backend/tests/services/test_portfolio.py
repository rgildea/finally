"""Tests for the portfolio service: summary shape, P&L math, snapshots."""

from app.services.portfolio import get_portfolio, record_snapshot


async def test_empty_portfolio(fake_db, price):
    result = await get_portfolio()

    assert result["cash_balance"] == 10000.0
    assert result["positions_value"] == 0.0
    assert result["total_value"] == 10000.0
    assert result["total_pl"] == 0.0
    assert result["total_pl_pct"] == 0.0
    assert result["positions"] == []


async def test_portfolio_with_gain(fake_db, price):
    fake_db.positions["AAPL"] = {"ticker": "AAPL", "quantity": 10, "avg_cost": 100.0}
    fake_db.cash = 9000.0
    await price("AAPL", 110.0)

    result = await get_portfolio()

    pos = result["positions"][0]
    assert pos["current_price"] == 110.0
    assert pos["market_value"] == 1100.0
    assert pos["unrealized_pl"] == 100.0
    assert round(pos["unrealized_pl_pct"], 2) == 10.0
    assert result["positions_value"] == 1100.0
    assert result["total_value"] == 10100.0
    assert result["total_pl"] == 100.0
    assert round(result["total_pl_pct"], 2) == 10.0


async def test_position_without_cached_price_uses_avg_cost(fake_db, price):
    fake_db.positions["AAPL"] = {"ticker": "AAPL", "quantity": 10, "avg_cost": 100.0}

    result = await get_portfolio()

    pos = result["positions"][0]
    assert pos["current_price"] == 100.0
    assert pos["unrealized_pl"] == 0.0


async def test_record_snapshot(fake_db, price):
    fake_db.positions["AAPL"] = {"ticker": "AAPL", "quantity": 10, "avg_cost": 100.0}
    fake_db.cash = 9000.0
    await price("AAPL", 110.0)

    await record_snapshot()

    assert fake_db.snapshots == [{"total_value": 10100.0}]
