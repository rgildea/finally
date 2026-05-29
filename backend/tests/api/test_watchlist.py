"""Tests for the watchlist endpoints: list, add, remove, and pricing shape."""

DEFAULT_TICKERS = {"AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "NVDA", "META", "JPM", "V", "NFLX"}


def test_watchlist_lists_seeded_tickers(client):
    resp = client.get("/api/watchlist")
    assert resp.status_code == 200
    tickers = {row["ticker"] for row in resp.json()}
    assert tickers == DEFAULT_TICKERS


async def test_unpriced_ticker_reports_nulls(monkeypatch):
    """The priced-watchlist builder reports nulls for tickers without a price.

    Tested at the helper level because the live simulator prices watched
    tickers within one poll cycle, so the API path is never deterministically
    unpriced.
    """
    import app.api.watchlist as wl
    from app.market.cache import price_cache

    price_cache._data.clear()
    monkeypatch.setattr(wl, "get_watched_tickers", lambda: ["AAPL"])
    rows = await wl._priced_watchlist()

    aapl = rows[0]
    assert aapl["ticker"] == "AAPL"
    assert aapl["price"] is None
    assert aapl["prev_price"] is None
    assert aapl["change_pct"] == 0.0


def test_priced_ticker_reports_change(client, seed_price):
    seed_price("AAPL", 110.0, prev=100.0)
    rows = client.get("/api/watchlist").json()
    aapl = next(r for r in rows if r["ticker"] == "AAPL")
    assert aapl["price"] == 110.0
    assert aapl["prev_price"] == 100.0
    assert round(aapl["change_pct"], 2) == 10.0


def test_add_ticker(client):
    resp = client.post("/api/watchlist", json={"ticker": "pypl"})
    assert resp.status_code == 200
    tickers = {row["ticker"] for row in resp.json()}
    assert "PYPL" in tickers


def test_remove_ticker(client):
    resp = client.delete("/api/watchlist/AAPL")
    assert resp.status_code == 200
    tickers = {row["ticker"] for row in resp.json()}
    assert "AAPL" not in tickers
