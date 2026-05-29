"""Tests for the portfolio endpoints: summary, trade, history."""


def test_portfolio_starts_empty(client):
    resp = client.get("/api/portfolio")
    assert resp.status_code == 200
    body = resp.json()
    assert body["cash_balance"] == 10000.0
    assert body["positions"] == []
    assert body["total_value"] == 10000.0


def test_trade_buy_then_portfolio_reflects_position(client, seed_price):
    seed_price("AAPL", 100.0)

    resp = client.post(
        "/api/portfolio/trade",
        json={"ticker": "AAPL", "quantity": 5, "side": "buy"},
    )
    assert resp.status_code == 200
    result = resp.json()
    assert result["cash_balance"] == 9500.0
    assert result["position"]["quantity"] == 5

    portfolio = client.get("/api/portfolio").json()
    assert portfolio["cash_balance"] == 9500.0
    assert portfolio["positions"][0]["ticker"] == "AAPL"


def test_trade_insufficient_cash_returns_400(client, seed_price):
    seed_price("AAPL", 100.0)
    resp = client.post(
        "/api/portfolio/trade",
        json={"ticker": "AAPL", "quantity": 1000, "side": "buy"},
    )
    assert resp.status_code == 400
    assert "Insufficient cash" in resp.json()["detail"]


def test_trade_no_price_returns_400(client):
    resp = client.post(
        "/api/portfolio/trade",
        json={"ticker": "ZZZZ", "quantity": 1, "side": "buy"},
    )
    assert resp.status_code == 400
    assert "No price available" in resp.json()["detail"]


def test_history_returns_snapshots_shape(client):
    resp = client.get("/api/portfolio/history")
    assert resp.status_code == 200
    assert "snapshots" in resp.json()
    assert isinstance(resp.json()["snapshots"], list)
