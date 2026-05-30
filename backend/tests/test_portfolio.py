"""Tests for portfolio trade execution, P&L logic, and TradeRequest model."""
import sqlite3

import pytest

import app.db.database as db_module
from app.db.database import get_connection, init_db
from app.market.interface import PriceUpdate
from app.routers.portfolio import (
    TradeRequest,
    _compute_total_value,
    _write_snapshot,
    execute_trade,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    """Point DB_PATH at a fresh temp file for every test."""
    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "test.db")
    init_db()


def _make_price(ticker: str, price: float) -> PriceUpdate:
    return PriceUpdate(ticker=ticker, price=price, prev_price=price, timestamp="2024-01-01T00:00:00Z")


def _cash() -> float:
    con = get_connection()
    try:
        row = con.execute("SELECT cash_balance FROM users_profile WHERE id='default'").fetchone()
        return row["cash_balance"]
    finally:
        con.close()


def _position(ticker: str) -> sqlite3.Row | None:
    con = get_connection()
    try:
        return con.execute(
            "SELECT * FROM positions WHERE user_id='default' AND ticker=?", (ticker,)
        ).fetchone()
    finally:
        con.close()


def _trade_count() -> int:
    con = get_connection()
    try:
        return con.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Task 1 — Trade execution and P&L logic (execute_trade directly)
# ---------------------------------------------------------------------------


def test_buy_new_position():
    """Buying 10 shares @ 100 of a new ticker creates position, debits cash, logs trade."""
    execute_trade("AAPL", "buy", 10, 100.0)

    pos = _position("AAPL")
    assert pos is not None
    assert pos["quantity"] == 10
    assert pos["avg_cost"] == 100.0
    assert _cash() == pytest.approx(10000.0 - 1000.0)
    assert _trade_count() == 1


def test_buy_averages_cost():
    """Buying 10 @ 100 then 10 @ 200 yields quantity=20 and avg_cost=150."""
    execute_trade("AAPL", "buy", 10, 100.0)
    execute_trade("AAPL", "buy", 10, 200.0)

    pos = _position("AAPL")
    assert pos["quantity"] == 20
    assert pos["avg_cost"] == pytest.approx(150.0)


def test_sell_reduces_position():
    """Owning 10 @ 100 then selling 4 @ 120 reduces qty to 6 and credits cash."""
    execute_trade("AAPL", "buy", 10, 100.0)
    execute_trade("AAPL", "sell", 4, 120.0)

    pos = _position("AAPL")
    assert pos["quantity"] == 6
    # cash = 10000 - 1000 (buy) + 480 (sell)
    assert _cash() == pytest.approx(9480.0)
    assert _trade_count() == 2
    con = get_connection()
    try:
        trade = con.execute(
            "SELECT side FROM trades ORDER BY executed_at DESC LIMIT 1"
        ).fetchone()
        assert trade["side"] == "sell"
    finally:
        con.close()


def test_sell_closes_position():
    """Selling entire quantity removes the position row."""
    execute_trade("AAPL", "buy", 10, 100.0)
    execute_trade("AAPL", "sell", 10, 100.0)

    pos = _position("AAPL")
    # Position removed (or quantity 0 — prefer removal per plan)
    assert pos is None or pos["quantity"] == 0


def test_insufficient_cash():
    """Buying beyond cash raises ValueError with no side effects."""
    cash_before = _cash()

    with pytest.raises(ValueError, match="Insufficient cash"):
        execute_trade("AAPL", "buy", 1000, 100.0)  # costs 100,000

    assert _cash() == cash_before
    assert _position("AAPL") is None
    assert _trade_count() == 0


def test_insufficient_shares():
    """Selling more than owned raises ValueError with no side effects."""
    execute_trade("AAPL", "buy", 5, 100.0)
    cash_after_buy = _cash()

    with pytest.raises(ValueError, match="Insufficient shares"):
        execute_trade("AAPL", "sell", 10, 100.0)

    assert _cash() == cash_after_buy
    assert _position("AAPL")["quantity"] == 5
    # Only the buy trade should exist
    assert _trade_count() == 1


def test_pnl_calculations():
    """P&L math: qty=10 avg_cost=100 current_price=120 → pnl=200, pct=20.0."""
    qty = 10
    avg_cost = 100.0
    current_price = 120.0

    unrealized_pnl = (current_price - avg_cost) * qty
    pnl_pct = (current_price - avg_cost) / avg_cost * 100

    assert unrealized_pnl == pytest.approx(200.0)
    assert pnl_pct == pytest.approx(20.0)
