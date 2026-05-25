from abc import ABC, abstractmethod

from pydantic import BaseModel, computed_field


class PriceUpdate(BaseModel):
    ticker: str
    price: float
    prev_price: float
    timestamp: str  # ISO 8601 UTC, e.g. "2024-01-15T14:30:00.000Z"

    @computed_field
    @property
    def change_pct(self) -> float:
        """Percentage change from prev_price to price."""
        if self.prev_price == 0:
            return 0.0
        return (self.price - self.prev_price) / self.prev_price * 100


class MarketDataSource(ABC):
    @abstractmethod
    async def start(self) -> None:
        """
        Start the data source. Called once at application startup.
        For the simulator: launches the background GBM loop.
        For Massive: initialises the httpx client.
        Must be idempotent — safe to call even if already started.
        """

    @abstractmethod
    async def stop(self) -> None:
        """
        Stop the data source. Called at application shutdown.
        Must be safe to call even if start() was never called.
        """

    @abstractmethod
    async def get_prices(self, tickers: list[str]) -> dict[str, PriceUpdate]:
        """
        Return the latest price for each requested ticker.

        Args:
            tickers: List of uppercase ticker symbols, e.g. ["AAPL", "MSFT"].

        Returns:
            Dict mapping ticker → PriceUpdate. Tickers with no data are
            omitted rather than raised as errors.

        Raises:
            httpx.HTTPStatusError: On Massive API non-2xx responses.
            asyncio.TimeoutError: If the request exceeds the configured timeout.
        """
