import asyncio
import logging
from datetime import datetime, timezone

import httpx

from .interface import MarketDataSource, PriceUpdate

logger = logging.getLogger(__name__)

MASSIVE_BASE_URL = "https://api.massive.com"
SNAPSHOT_PATH = "/v2/snapshot/locale/us/markets/stocks/tickers"


class MassiveAPIClient(MarketDataSource):
    """
    Fetches real stock prices from the Massive REST API.
    Uses the /v2/snapshot endpoint for bulk multi-ticker fetching.

    Notes:
    - The snapshot endpoint requires a Starter plan or above.
      It is NOT available on the Basic (free) tier.
    - On 429 Too Many Requests, the client raises httpx.HTTPStatusError.
      The polling loop should back off 60 seconds before retrying.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = MASSIVE_BASE_URL,
        timeout: float = 10.0,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def start(self) -> None:
        if self._client is not None:
            return
        self._client = httpx.AsyncClient(timeout=self._timeout)
        logger.info("Massive API client started (base_url=%s)", self._base_url)

    async def stop(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
        logger.info("Massive API client stopped")

    async def get_prices(self, tickers: list[str]) -> dict[str, PriceUpdate]:
        """
        Fetch the latest snapshot for all requested tickers in one API call.

        Raises:
            RuntimeError: If start() has not been called.
            httpx.HTTPStatusError: On non-2xx responses (including 429).
            asyncio.TimeoutError: If the request exceeds self._timeout.
        """
        if not self._client:
            raise RuntimeError(
                "MassiveAPIClient.start() must be called before get_prices()"
            )

        response = await self._client.get(
            f"{self._base_url}{SNAPSHOT_PATH}",
            params={
                "tickers": ",".join(tickers),
                "apiKey": self._api_key,
            },
        )
        response.raise_for_status()
        return self._parse_response(response.json())

    def _parse_response(self, data: dict) -> dict[str, PriceUpdate]:
        """
        Parse the Massive snapshot response into PriceUpdate objects.

        Price field priority (from MASSIVE_API.md):
          1. lastTrade.p — most recent trade price (primary)
          2. day.c       — current day's close/price (fallback)

        Timestamps in lastTrade.t are Unix milliseconds.
        """
        result: dict[str, PriceUpdate] = {}
        now_iso = datetime.now(timezone.utc).isoformat()

        for item in data.get("tickers", []):
            ticker = item.get("ticker", "").upper()
            if not ticker:
                continue

            price = self._extract_price(item)
            if not price or price <= 0:
                logger.debug("Skipping %s — no valid price in snapshot", ticker)
                continue

            timestamp = self._extract_timestamp(item, now_iso)

            # prev_price is set to price here; the polling loop's _merge_with_prev()
            # replaces it with the actual cached prev before writing to PriceCache.
            result[ticker] = PriceUpdate(
                ticker=ticker,
                price=price,
                prev_price=price,
                timestamp=timestamp,
            )

        return result

    @staticmethod
    def _extract_price(item: dict) -> float | None:
        """Extract the best available price from a snapshot item."""
        last_trade = item.get("lastTrade") or {}
        if (p := last_trade.get("p")) is not None:
            return float(p)
        day = item.get("day") or {}
        if (c := day.get("c")) is not None:
            return float(c)
        return None

    @staticmethod
    def _extract_timestamp(item: dict, fallback: str) -> str:
        """
        Convert lastTrade.t (Unix milliseconds) to ISO 8601 UTC string.
        Falls back to current time if the field is missing or unparseable.
        """
        try:
            last_trade = item.get("lastTrade") or {}
            t_ms = last_trade.get("t")
            if t_ms is not None:
                ts = datetime.fromtimestamp(int(t_ms) / 1000, tz=timezone.utc)
                return ts.isoformat()
        except (TypeError, ValueError, OSError):
            pass
        return fallback
