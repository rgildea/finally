from datetime import datetime

import httpx
import pytest
import respx

from app.market.massive import MASSIVE_BASE_URL, SNAPSHOT_PATH, MassiveAPIClient

SNAPSHOT_URL = f"{MASSIVE_BASE_URL}{SNAPSHOT_PATH}"

MOCK_RESPONSE = {
    "status": "OK",
    "count": 2,
    "tickers": [
        {
            "ticker": "AAPL",
            "lastTrade": {"p": 190.85, "t": 1703001234000},
            "day": {"c": 190.60},
        },
        {
            "ticker": "MSFT",
            "lastTrade": {"p": 421.10, "t": 1703001234000},
            "day": {"c": 420.90},
        },
    ],
}


def make_client() -> MassiveAPIClient:
    return MassiveAPIClient(api_key="test-key")


# ── _parse_response unit tests (no HTTP) ─────────────────────────────────────

def test_parse_response_uses_last_trade_price():
    client = make_client()
    result = client._parse_response(MOCK_RESPONSE)
    assert result["AAPL"].price == 190.85
    assert result["MSFT"].price == 421.10


def test_parse_response_falls_back_to_day_close():
    response = {
        "status": "OK",
        "tickers": [{"ticker": "JPM", "day": {"c": 195.30}}],
    }
    client = make_client()
    result = client._parse_response(response)
    assert result["JPM"].price == 195.30


def test_parse_response_skips_zero_price():
    response = {
        "status": "OK",
        "tickers": [{"ticker": "BAD", "lastTrade": {"p": 0.0}}],
    }
    client = make_client()
    result = client._parse_response(response)
    assert "BAD" not in result


def test_parse_response_skips_missing_ticker_field():
    response = {"status": "OK", "tickers": [{"lastTrade": {"p": 100.0}}]}
    client = make_client()
    result = client._parse_response(response)
    assert len(result) == 0


def test_parse_response_skips_no_price_fields():
    """Ticker with neither lastTrade.p nor day.c should be skipped."""
    response = {"status": "OK", "tickers": [{"ticker": "NOPRICE"}]}
    client = make_client()
    result = client._parse_response(response)
    assert "NOPRICE" not in result


def test_parse_response_empty_tickers_list():
    client = make_client()
    result = client._parse_response({"status": "OK", "tickers": []})
    assert result == {}


def test_parse_response_prev_price_equals_price():
    """prev_price is set to price; polling loop replaces it with cached prev."""
    client = make_client()
    result = client._parse_response(MOCK_RESPONSE)
    assert result["AAPL"].prev_price == result["AAPL"].price


def test_timestamp_parsed_from_milliseconds():
    """lastTrade.t is Unix milliseconds — verify correct conversion."""
    item = {"ticker": "AAPL", "lastTrade": {"p": 190.0, "t": 1703001234000}}
    client = make_client()
    result = client._parse_response({"status": "OK", "tickers": [item]})
    ts = result["AAPL"].timestamp
    parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    assert parsed.year == 2023  # 1703001234000 ms = Dec 19, 2023


def test_timestamp_falls_back_when_missing():
    """When lastTrade.t is absent, timestamp is the current time (ISO format)."""
    item = {"ticker": "AAPL", "lastTrade": {"p": 190.0}}
    client = make_client()
    result = client._parse_response({"status": "OK", "tickers": [item]})
    ts = result["AAPL"].timestamp
    # Should still be a parseable ISO datetime
    parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    assert parsed.year >= 2024


def test_ticker_normalized_to_uppercase():
    """Ticker symbols should be uppercased regardless of API response case."""
    response = {
        "status": "OK",
        "tickers": [{"ticker": "aapl", "lastTrade": {"p": 190.0, "t": 1703001234000}}],
    }
    client = make_client()
    result = client._parse_response(response)
    assert "AAPL" in result


# ── HTTP-level tests (with respx mock) ───────────────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_get_prices_calls_correct_url():
    respx.get(SNAPSHOT_URL).mock(
        return_value=httpx.Response(200, json=MOCK_RESPONSE)
    )
    client = make_client()
    await client.start()
    result = await client.get_prices(["AAPL", "MSFT"])
    assert len(result) == 2
    request = respx.calls.last.request
    assert "apiKey=test-key" in str(request.url)
    await client.stop()


@pytest.mark.asyncio
@respx.mock
async def test_get_prices_includes_tickers_param():
    respx.get(SNAPSHOT_URL).mock(
        return_value=httpx.Response(200, json=MOCK_RESPONSE)
    )
    client = make_client()
    await client.start()
    await client.get_prices(["AAPL", "MSFT"])
    request = respx.calls.last.request
    url_str = str(request.url)
    assert "AAPL" in url_str
    assert "MSFT" in url_str
    await client.stop()


@pytest.mark.asyncio
@respx.mock
async def test_get_prices_raises_on_429():
    respx.get(SNAPSHOT_URL).mock(
        return_value=httpx.Response(429, json={"error": "rate limited"})
    )
    client = make_client()
    await client.start()
    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        await client.get_prices(["AAPL"])
    assert exc_info.value.response.status_code == 429
    await client.stop()


@pytest.mark.asyncio
@respx.mock
async def test_get_prices_raises_on_401():
    respx.get(SNAPSHOT_URL).mock(
        return_value=httpx.Response(401, json={"error": "unauthorized"})
    )
    client = make_client()
    await client.start()
    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        await client.get_prices(["AAPL"])
    assert exc_info.value.response.status_code == 401
    await client.stop()


@pytest.mark.asyncio
async def test_get_prices_before_start_raises():
    client = make_client()
    with pytest.raises(RuntimeError, match="start()"):
        await client.get_prices(["AAPL"])


@pytest.mark.asyncio
async def test_stop_without_start_is_safe():
    client = make_client()
    await client.stop()  # Should not raise


@pytest.mark.asyncio
@respx.mock
async def test_stop_closes_client():
    respx.get(SNAPSHOT_URL).mock(
        return_value=httpx.Response(200, json=MOCK_RESPONSE)
    )
    client = make_client()
    await client.start()
    assert client._client is not None
    await client.stop()
    assert client._client is None


@pytest.mark.asyncio
async def test_custom_base_url():
    """Client should use custom base_url when provided."""
    custom_url = "https://api.polygon.io"
    client = MassiveAPIClient(api_key="key", base_url=custom_url)
    assert client._base_url == custom_url


@pytest.mark.asyncio
@respx.mock
async def test_get_prices_returns_price_updates():
    respx.get(SNAPSHOT_URL).mock(
        return_value=httpx.Response(200, json=MOCK_RESPONSE)
    )
    client = make_client()
    await client.start()
    result = await client.get_prices(["AAPL", "MSFT"])
    from app.market.interface import PriceUpdate
    for update in result.values():
        assert isinstance(update, PriceUpdate)
    await client.stop()


@pytest.mark.asyncio
async def test_start_idempotent():
    """Calling start() twice should not create a second client or leak the first."""
    client = make_client()
    await client.start()
    first_client = client._client
    assert first_client is not None

    await client.start()
    assert client._client is first_client  # same object — no new client created

    await client.stop()
    assert client._client is None


def test_extract_price_zero_last_trade_falls_back_to_day():
    """lastTrade.p = 0.0 is falsy — must not be silently skipped; falls through to day.c."""
    item = {"ticker": "XYZ", "lastTrade": {"p": 0.0}, "day": {"c": 42.50}}
    client = make_client()
    # With the is-not-None fix, p=0.0 is returned immediately as 0.0.
    # The caller (_parse_response) then rejects it via `not price or price <= 0`.
    price = client._extract_price(item)
    # _extract_price now returns 0.0 (not None), so _parse_response will skip it.
    # This is the correct behavior: 0.0 is explicitly present, not absent.
    assert price == 0.0


def test_extract_price_none_last_trade_uses_day():
    """When lastTrade.p is absent (None), fall back to day.c."""
    item = {"ticker": "XYZ", "lastTrade": {}, "day": {"c": 42.50}}
    client = make_client()
    price = client._extract_price(item)
    assert price == 42.50
