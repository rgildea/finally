from app.market.interface import PriceUpdate


def test_change_pct_uptick():
    u = PriceUpdate(ticker="AAPL", price=191.0, prev_price=190.0, timestamp="t")
    assert abs(u.change_pct - (1.0 / 190.0 * 100)) < 0.001


def test_change_pct_downtick():
    u = PriceUpdate(ticker="AAPL", price=188.0, prev_price=190.0, timestamp="t")
    assert u.change_pct < 0


def test_change_pct_flat():
    u = PriceUpdate(ticker="AAPL", price=190.0, prev_price=190.0, timestamp="t")
    assert u.change_pct == 0.0


def test_change_pct_zero_prev_price():
    """Guard against division by zero on first tick."""
    u = PriceUpdate(ticker="AAPL", price=190.0, prev_price=0.0, timestamp="t")
    assert u.change_pct == 0.0


def test_change_pct_large_move():
    u = PriceUpdate(ticker="TSLA", price=262.5, prev_price=250.0, timestamp="t")
    assert abs(u.change_pct - 5.0) < 0.001


def test_price_update_fields():
    u = PriceUpdate(ticker="MSFT", price=420.0, prev_price=419.5, timestamp="2024-01-15T14:30:00Z")
    assert u.ticker == "MSFT"
    assert u.price == 420.0
    assert u.prev_price == 419.5
    assert u.timestamp == "2024-01-15T14:30:00Z"


def test_change_pct_is_computed_not_stored():
    """change_pct is a computed field — not passed in constructor."""
    u = PriceUpdate(ticker="AAPL", price=200.0, prev_price=100.0, timestamp="t")
    assert u.change_pct == 100.0
