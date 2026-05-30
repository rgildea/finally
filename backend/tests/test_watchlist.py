"""Tests for watchlist GET/POST/DELETE endpoints and WatchlistRequest model."""
from unittest.mock import AsyncMock

import httpx
import pytest

import app.db.database as db_module
from app.db.database import get_connection, get_watchlist_tickers, init_db
from app.main import app
from app.market.cache import price_cache
from app.market.interface import PriceUpdate


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    """Point DB_PATH at a fresh temp file for every test and seed defaults."""
    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "test.db")
    init_db()


def _make_price(ticker: str, price: float) -> PriceUpdate:
    return PriceUpdate(
        ticker=ticker, price=price, prev_price=price, timestamp="2024-01-01T00:00:00Z"
    )


def _watchlist_tickers() -> list[str]:
    con = get_connection()
    try:
        rows = con.execute(
            "SELECT ticker FROM watchlist WHERE user_id='default' ORDER BY added_at"
        ).fetchall()
        return [row["ticker"] for row in rows]
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Test 1: GET /api/watchlist returns 10 entries with ticker and price fields
# ---------------------------------------------------------------------------


async def test_get_watchlist():
    """Fresh seeded DB: GET /api/watchlist returns 200 with 10 entries; each has ticker and price."""
    with __import__("unittest.mock", fromlist=["AsyncMock"]).AsyncMock() as _:
        pass  # just ensure imports work

    # Patch cache so price may be null (empty cache)
    import app.market.cache as cache_mod
    monkeypatch_cache = AsyncMock(return_value={})

    with __import__("unittest.mock", fromlist=["patch"]).patch.object(
        price_cache, "get_many", AsyncMock(return_value={})
    ):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/api/watchlist")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 10
    for entry in data:
        assert "ticker" in entry
        assert "price" in entry


# ---------------------------------------------------------------------------
# Test 2: GET /api/watchlist returns cached prices when available
# ---------------------------------------------------------------------------


async def test_get_watchlist_with_prices():
    """With mocked cache, returned entries carry the cached price for tickers present."""
    aapl_update = _make_price("AAPL", 195.50)
    mock_prices = {"AAPL": aapl_update}

    with __import__("unittest.mock", fromlist=["patch"]).patch.object(
        price_cache, "get_many", AsyncMock(return_value=mock_prices)
    ):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/api/watchlist")

    assert response.status_code == 200
    data = response.json()
    aapl_entry = next((e for e in data if e["ticker"] == "AAPL"), None)
    assert aapl_entry is not None
    assert aapl_entry["price"] == pytest.approx(195.5)

    # Tickers not in cache should have price=None
    non_aapl = [e for e in data if e["ticker"] != "AAPL"]
    for entry in non_aapl:
        assert entry["price"] is None


# ---------------------------------------------------------------------------
# Test 3: POST /api/watchlist adds ticker
# ---------------------------------------------------------------------------


async def test_add_ticker():
    """POST {ticker:'PYPL'} returns 200 and subsequent get_watchlist_tickers() includes PYPL."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/api/watchlist", json={"ticker": "PYPL"})

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["ticker"] == "PYPL"

    tickers = _watchlist_tickers()
    assert "PYPL" in tickers


# ---------------------------------------------------------------------------
# Test 4: POST /api/watchlist normalizes lowercase ticker to uppercase
# ---------------------------------------------------------------------------


async def test_add_ticker_lowercase_normalized():
    """POST {ticker:'pypl'} stores 'PYPL' (uppercased)."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/api/watchlist", json={"ticker": "pypl"})

    assert response.status_code == 200
    data = response.json()
    assert data["ticker"] == "PYPL"

    tickers = _watchlist_tickers()
    assert "PYPL" in tickers
    assert "pypl" not in tickers


# ---------------------------------------------------------------------------
# Test 5: POST /api/watchlist is idempotent (duplicate raises no error)
# ---------------------------------------------------------------------------


async def test_add_duplicate_idempotent():
    """POST an already-watched ticker does not create a duplicate row."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp1 = await client.post("/api/watchlist", json={"ticker": "AAPL"})
        resp2 = await client.post("/api/watchlist", json={"ticker": "AAPL"})

    assert resp1.status_code == 200
    assert resp2.status_code == 200

    con = get_connection()
    try:
        count = con.execute(
            "SELECT COUNT(*) FROM watchlist WHERE user_id='default' AND ticker='AAPL'"
        ).fetchone()[0]
    finally:
        con.close()

    assert count == 1


# ---------------------------------------------------------------------------
# Test 6: DELETE /api/watchlist/{ticker} removes ticker and clears cache
# ---------------------------------------------------------------------------


async def test_remove_ticker():
    """DELETE /api/watchlist/AAPL returns 200; ticker removed from DB and price_cache.remove called."""
    mock_remove = AsyncMock()

    with __import__("unittest.mock", fromlist=["patch"]).patch.object(
        price_cache, "remove", mock_remove
    ):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.delete("/api/watchlist/AAPL")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["ticker"] == "AAPL"

    tickers = _watchlist_tickers()
    assert "AAPL" not in tickers

    mock_remove.assert_awaited_once_with("AAPL")


# ---------------------------------------------------------------------------
# Test 7 (Task 2): Router is registered on the app
# ---------------------------------------------------------------------------


async def test_watchlist_routes_registered():
    """GET /api/watchlist via ASGITransport returns 200, confirming router is mounted."""
    with __import__("unittest.mock", fromlist=["patch"]).patch.object(
        price_cache, "get_many", AsyncMock(return_value={})
    ):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/api/watchlist")

    assert response.status_code == 200
