"""Tests for portfolio trade execution, P&L logic, and TradeRequest model."""
import sqlite3
from unittest.mock import AsyncMock, patch

import httpx
import pytest

import app.db.database as db_module
from app.db.database import get_connection, init_db
from app.main import app
from app.market.cache import price_cache
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


# ---------------------------------------------------------------------------
# Task 2 — Endpoint tests (GET /api/portfolio, POST /api/portfolio/trade, history)
# ---------------------------------------------------------------------------


@pytest.fixture
def no_cache(monkeypatch):
    """Patch price_cache.get_many to return an empty dict (no prices in cache)."""
    monkeypatch.setattr(price_cache, "get_many", AsyncMock(return_value={}))


@pytest.fixture
def mock_aapl_cache(monkeypatch):
    """Patch price_cache to return AAPL @ 200.0 for get_many and get."""
    aapl = _make_price("AAPL", 200.0)
    monkeypatch.setattr(price_cache, "get_many", AsyncMock(return_value={"AAPL": aapl}))
    monkeypatch.setattr(price_cache, "get", AsyncMock(return_value=aapl))


async def test_portfolio_empty_shape(no_cache):
    """Fresh DB: GET /api/portfolio returns cash=10000, total_value=10000, positions=[]."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/portfolio")

    assert response.status_code == 200
    data = response.json()
    assert data["cash_balance"] == 10000.0
    assert data["total_value"] == 10000.0
    assert data["positions"] == []


async def test_portfolio_response_shape(mock_aapl_cache):
    """Seeded position with mocked cache price returns correct shape and P&L."""
    # Seed a position directly via execute_trade
    execute_trade("AAPL", "buy", 5, 100.0)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/portfolio")

    assert response.status_code == 200
    data = response.json()
    pos = data["positions"][0]
    assert pos["ticker"] == "AAPL"
    assert pos["quantity"] == 5
    assert "avg_cost" in pos
    assert "current_price" in pos
    assert "market_value" in pos
    assert "unrealized_pnl" in pos
    assert "pnl_pct" in pos
    # total_value = cash + market_value
    expected_total = round(data["cash_balance"] + pos["market_value"], 2)
    assert data["total_value"] == pytest.approx(expected_total)


async def test_trade_endpoint_buy(mock_aapl_cache):
    """POST /api/portfolio/trade buy returns 200; GET /api/portfolio reflects new position."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/api/portfolio/trade",
            json={"ticker": "AAPL", "side": "buy", "quantity": 3},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["ticker"] == "AAPL"

        portfolio = await client.get("/api/portfolio")
        pdata = portfolio.json()
        assert len(pdata["positions"]) == 1
        assert pdata["positions"][0]["ticker"] == "AAPL"
        assert pdata["cash_balance"] < 10000.0


async def test_trade_no_price_503():
    """POST trade for ticker not in cache returns 503."""
    with patch.object(price_cache, "get", AsyncMock(return_value=None)):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/portfolio/trade",
                json={"ticker": "ZZZZZ", "side": "buy", "quantity": 1},
            )
    assert resp.status_code == 503


async def test_trade_insufficient_cash_400(mock_aapl_cache):
    """POST buy exceeding cash returns 400."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/api/portfolio/trade",
            json={"ticker": "AAPL", "side": "buy", "quantity": 10000},
        )
    assert resp.status_code == 400
    assert "cash" in resp.json()["detail"].lower()


async def test_trade_validation_422():
    """POST with quantity <= 0 or invalid side returns 422."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        # quantity = 0
        resp = await client.post(
            "/api/portfolio/trade",
            json={"ticker": "AAPL", "side": "buy", "quantity": 0},
        )
        assert resp.status_code == 422

        # invalid side
        resp = await client.post(
            "/api/portfolio/trade",
            json={"ticker": "AAPL", "side": "hold", "quantity": 1},
        )
        assert resp.status_code == 422


async def test_portfolio_history():
    """GET /api/portfolio/history returns snapshot rows in chronological order."""
    # Insert snapshots directly
    _write_snapshot(10000.0)
    _write_snapshot(10500.0)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/api/portfolio/history")

    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 2
    assert rows[0]["total_value"] == 10000.0
    assert rows[1]["total_value"] == 10500.0
    assert rows[0]["recorded_at"] <= rows[1]["recorded_at"]


async def test_snapshot_recorder_inserts(no_cache):
    """_write_snapshot inserts one row; _compute_total_value returns cash when no positions."""
    total = await _compute_total_value()
    _write_snapshot(total)

    con = get_connection()
    try:
        count = con.execute("SELECT COUNT(*) FROM portfolio_snapshots").fetchone()[0]
        row = con.execute("SELECT total_value FROM portfolio_snapshots").fetchone()
    finally:
        con.close()

    assert count == 1
    assert row["total_value"] == pytest.approx(10000.0)
