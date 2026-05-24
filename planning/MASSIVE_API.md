# Massive API Reference

Massive (formerly Polygon.io, rebranded October 2025) provides financial market data via REST and WebSocket APIs. This document covers the REST endpoints used by FinAlly for fetching stock prices.

- **New base URL:** `https://api.massive.com`
- **Legacy base URL:** `https://api.polygon.io` (backward compatible, will continue to work)
- **Docs:** https://massive.com/docs/stocks
- **Python SDK:** `pip install massive`

---

## Authentication

Pass the API key as a query parameter on every request:

```
GET https://api.massive.com/v2/snapshot/locale/us/markets/stocks/tickers?tickers=AAPL&apiKey=YOUR_KEY
```

The API key is obtained from the Massive dashboard. Set it as the `MASSIVE_API_KEY` environment variable in FinAlly.

---

## Rate Limits

| Plan | Requests/Minute | Data Recency |
|------|-----------------|--------------|
| Basic (free) | 5 | End-of-day only |
| Starter | Unlimited | 15-minute delayed |
| Developer | Unlimited | 15-minute delayed |
| Advanced | Unlimited | Real-time |
| Business | Unlimited | Real-time |

**Implications for FinAlly polling:**

- **Free tier (5 req/min):** Poll every 15 seconds. The snapshot endpoint fetches all tickers in one call, so one call per poll cycle is sufficient.
- **Paid tiers (unlimited):** Poll every 1–2 seconds for near-real-time updates.

When the rate limit is exceeded, the API returns HTTP `429 Too Many Requests`.

---

## Endpoint 1: Bulk Stock Snapshot (Primary)

Returns the latest snapshot for multiple tickers in a single call. This is the primary endpoint used by FinAlly for live price polling.

```
GET /v2/snapshot/locale/us/markets/stocks/tickers
```

**Query parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `tickers` | string | No | Comma-separated ticker symbols (e.g. `AAPL,MSFT,TSLA`). Omit to get all tickers. |
| `include_otc` | boolean | No | Include OTC securities. Default: `false`. |
| `apiKey` | string | Yes | Your API key. |

**Plan access:** Starter and above. Not available on Basic (free).

**Data recency:** 15-minute delayed on Starter/Developer; real-time on Advanced/Business.

**Example request:**

```python
import httpx

async def fetch_snapshots(
    tickers: list[str],
    api_key: str,
    base_url: str = "https://api.massive.com",
) -> dict:
    params = {
        "tickers": ",".join(tickers),
        "apiKey": api_key,
    }
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{base_url}/v2/snapshot/locale/us/markets/stocks/tickers",
            params=params,
            timeout=10.0,
        )
        response.raise_for_status()
        return response.json()
```

**Response schema:**

```json
{
  "status": "OK",
  "count": 2,
  "tickers": [
    {
      "ticker": "AAPL",
      "todaysChange": 2.35,
      "todaysChangePerc": 1.24,
      "updated": 1703001234567,
      "day": {
        "o": 188.50,
        "h": 191.20,
        "l": 187.80,
        "c": 190.85,
        "v": 52341000,
        "vw": 189.94
      },
      "prevDay": {
        "o": 186.00,
        "h": 189.10,
        "l": 185.50,
        "c": 188.50,
        "v": 48920000,
        "vw": 187.62
      },
      "min": {
        "o": 190.60,
        "h": 191.00,
        "l": 190.40,
        "c": 190.85,
        "v": 125000,
        "vw": 190.72,
        "t": 1703001180000
      },
      "lastTrade": {
        "p": 190.85,
        "s": 100,
        "t": 1703001234000,
        "x": 4,
        "i": ["00MGON8101BD5o"],
        "c": [14, 41],
        "ds": ""
      },
      "lastQuote": {
        "P": 190.86,
        "p": 190.84,
        "S": 2,
        "s": 1,
        "t": 1703001234500
      }
    }
  ]
}
```

**Key fields:**

| Field | Description |
|-------|-------------|
| `ticker` | Ticker symbol |
| `todaysChange` | Price change from previous close |
| `todaysChangePerc` | Percentage change from previous close |
| `updated` | Unix millisecond timestamp of last update |
| `day.c` | Current day's latest close/price |
| `day.o` / `day.h` / `day.l` | Open, high, low for today |
| `day.v` | Today's volume |
| `day.vw` | Today's volume-weighted average price |
| `prevDay.c` | Previous day's closing price |
| `lastTrade.p` | Price of the most recent trade |
| `lastTrade.s` | Size (shares) of the most recent trade |
| `lastTrade.t` | Unix millisecond timestamp of last trade |
| `lastQuote.P` | Ask price |
| `lastQuote.p` | Bid price |

**Notes:**
- `lastTrade.p` is the most current price available. Use this as the live price.
- `prevDay.c` is the reference price for computing daily change if `todaysChange` is stale.
- Snapshot data is cleared at 3:30 AM EST daily and repopulates as exchanges open (~4:00 AM EST).
- `fmv` (fair market value) is only available on Business plans.

---

## Endpoint 2: Previous Day OHLC

Returns the previous trading day's open, high, low, close, and volume for a single ticker.

```
GET /v2/aggs/ticker/{stocksTicker}/prev
```

**Path parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `stocksTicker` | string | Yes | Case-sensitive ticker symbol (e.g. `AAPL`). |

**Query parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `adjusted` | boolean | No | Apply split/dividend adjustments. Default: `true`. |
| `apiKey` | string | Yes | Your API key. |

**Plan access:** All plans including Basic (free).

**Example request:**

```python
import httpx

async def fetch_previous_close(
    ticker: str,
    api_key: str,
    base_url: str = "https://api.massive.com",
) -> dict:
    params = {"adjusted": "true", "apiKey": api_key}
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{base_url}/v2/aggs/ticker/{ticker}/prev",
            params=params,
            timeout=10.0,
        )
        response.raise_for_status()
        return response.json()
```

**Response schema:**

```json
{
  "ticker": "AAPL",
  "adjusted": true,
  "queryCount": 1,
  "resultsCount": 1,
  "status": "OK",
  "request_id": "abc123",
  "results": [
    {
      "o": 186.00,
      "h": 189.10,
      "l": 185.50,
      "c": 188.50,
      "v": 48920000,
      "vw": 187.62,
      "n": 621438,
      "t": 1702944000000
    }
  ]
}
```

**Key fields in `results[0]`:**

| Field | Description |
|-------|-------------|
| `c` | Closing price |
| `o` | Opening price |
| `h` | High |
| `l` | Low |
| `v` | Volume |
| `vw` | Volume-weighted average price |
| `n` | Number of transactions |
| `t` | Unix millisecond timestamp (start of the day) |

---

## Python SDK Usage

The official SDK handles authentication, pagination, and retry automatically.

```python
from massive import RESTClient

client = RESTClient(api_key="YOUR_KEY")

# Get snapshots for multiple tickers
snapshots = client.get_snapshot_all_tickers(
    locale="us",
    market_type="stocks",
    tickers=["AAPL", "MSFT", "TSLA"],
)

# Get previous day close for one ticker
prev = client.get_aggs(ticker="AAPL", multiplier=1, timespan="day", from_="2024-01-01", to="2024-01-01")
```

FinAlly uses raw `httpx` async calls rather than the SDK to keep dependencies minimal and maintain full control over error handling and polling cadence.

---

## Error Handling

| HTTP Status | Meaning |
|-------------|---------|
| `200 OK` | Success |
| `400 Bad Request` | Invalid parameters |
| `401 Unauthorized` | Missing or invalid API key |
| `403 Forbidden` | Plan does not include this endpoint |
| `429 Too Many Requests` | Rate limit exceeded |
| `500 Internal Server Error` | Massive server error |

On `429`, back off and retry after 60 seconds (or wait until the next minute boundary).

---

## Polling Strategy for FinAlly

FinAlly polls the snapshot endpoint once per cycle for all watchlist tickers:

```python
# One call fetches prices for all tickers — do not call per-ticker
params = {"tickers": "AAPL,MSFT,TSLA,NVDA,...", "apiKey": api_key}
```

Recommended polling intervals:
- **Free tier:** 15 seconds (5 calls/min budget, leaving room for other requests)
- **Starter/Developer:** 5–10 seconds
- **Advanced/Business:** 1–2 seconds
