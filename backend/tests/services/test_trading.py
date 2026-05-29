"""Tests for the trading service: validation, fills, and position math."""

import pytest

from app.services.trading import TradeError, execute_trade


async def test_buy_creates_position_and_debits_cash(fake_db, price):
    await price("AAPL", 100.0)

    result = await execute_trade("aapl", "buy", 10)

    assert result["ticker"] == "AAPL"
    assert result["side"] == "buy"
    assert result["price"] == 100.0
    assert result["cash_balance"] == 9000.0
    assert result["position"] == {"ticker": "AAPL", "quantity": 10, "avg_cost": 100.0}
    assert fake_db.cash == 9000.0
    assert len(fake_db.trades) == 1


async def test_buy_averages_cost(fake_db, price):
    await price("AAPL", 100.0)
    await execute_trade("AAPL", "buy", 10)
    await price("AAPL", 200.0)

    result = await execute_trade("AAPL", "buy", 10)

    assert result["position"]["quantity"] == 20
    assert result["position"]["avg_cost"] == 150.0


async def test_buy_insufficient_cash_raises(fake_db, price):
    await price("AAPL", 100.0)

    with pytest.raises(TradeError, match="Insufficient cash"):
        await execute_trade("AAPL", "buy", 1000)
    assert fake_db.cash == 10000.0
    assert fake_db.trades == []


async def test_sell_reduces_position_and_credits_cash(fake_db, price):
    await price("AAPL", 100.0)
    await execute_trade("AAPL", "buy", 10)

    result = await execute_trade("AAPL", "sell", 4)

    assert result["cash_balance"] == 9400.0
    assert result["position"]["quantity"] == 6
    assert result["position"]["avg_cost"] == 100.0


async def test_sell_entire_position_closes_it(fake_db, price):
    await price("AAPL", 100.0)
    await execute_trade("AAPL", "buy", 10)

    result = await execute_trade("AAPL", "sell", 10)

    assert result["position"] is None
    assert "AAPL" not in fake_db.positions


async def test_sell_more_than_held_raises(fake_db, price):
    await price("AAPL", 100.0)
    await execute_trade("AAPL", "buy", 5)

    with pytest.raises(TradeError, match="Insufficient shares"):
        await execute_trade("AAPL", "sell", 10)


async def test_no_cached_price_raises(fake_db, price):
    with pytest.raises(TradeError, match="No price available for ZZZZ"):
        await execute_trade("ZZZZ", "buy", 1)


async def test_invalid_side_raises(fake_db, price):
    await price("AAPL", 100.0)
    with pytest.raises(TradeError, match="Side must be"):
        await execute_trade("AAPL", "hold", 1)


async def test_non_positive_quantity_raises(fake_db, price):
    await price("AAPL", 100.0)
    with pytest.raises(TradeError, match="Quantity must be positive"):
        await execute_trade("AAPL", "buy", 0)
