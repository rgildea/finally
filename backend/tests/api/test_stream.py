"""Test the SSE price stream generator emits well-formed price events.

Driven directly (not via TestClient) so it is deterministic and cannot hang on
the infinite stream loop. A fake request disconnects after the first cycle.
"""

import json

from app.api.stream import _price_events
from app.market.cache import price_cache
from app.market.interface import PriceUpdate


class FakeRequest:
    """Reports connected for the first check, disconnected thereafter."""

    def __init__(self) -> None:
        self._checks = 0

    async def is_disconnected(self) -> bool:
        self._checks += 1
        return self._checks > 1


async def test_price_events_emits_watched_tickers(monkeypatch):
    import app.api.stream as stream

    price_cache._data.clear()
    price_cache._data["AAPL"] = PriceUpdate(
        ticker="AAPL", price=110.0, prev_price=100.0, timestamp="2026-05-28T00:00:00Z"
    )
    monkeypatch.setattr(stream, "get_watched_tickers", lambda: ["AAPL"])

    events = []
    async for event in _price_events(FakeRequest()):
        events.append(event)

    price_cache._data.clear()

    assert len(events) == 1
    assert events[0]["event"] == "price"
    payload = json.loads(events[0]["data"])
    assert payload == {
        "ticker": "AAPL",
        "price": 110.0,
        "prev_price": 100.0,
        "change_pct": 10.0,
        "timestamp": "2026-05-28T00:00:00Z",
    }


async def test_price_events_stops_when_disconnected(monkeypatch):
    import app.api.stream as stream

    price_cache._data.clear()
    monkeypatch.setattr(stream, "get_watched_tickers", lambda: [])

    request = FakeRequest()
    request._checks = 1  # already past the first check -> disconnected immediately
    events = [event async for event in _price_events(request)]

    assert events == []
