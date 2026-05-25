import os

from .cache import PriceCache, price_cache
from .interface import MarketDataSource, PriceUpdate
from .massive import MassiveAPIClient
from .simulator import MarketSimulator

__all__ = [
    "MarketDataSource",
    "PriceUpdate",
    "PriceCache",
    "price_cache",
    "MarketSimulator",
    "MassiveAPIClient",
    "create_market_data_source",
]


def create_market_data_source() -> MarketDataSource:
    """
    Return the appropriate MarketDataSource based on environment variables.

    - MASSIVE_API_KEY set and non-empty → MassiveAPIClient
    - Otherwise → MarketSimulator

    Note: The Massive snapshot endpoint requires a Starter plan or above.
    It is not available on the Basic (free) tier.
    """
    api_key = os.getenv("MASSIVE_API_KEY", "").strip()
    if api_key:
        return MassiveAPIClient(api_key=api_key)
    return MarketSimulator()
