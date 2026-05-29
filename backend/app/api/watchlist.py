"""Watchlist REST endpoints: list, add, remove (each returns priced watchlist)."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.market.cache import price_cache
from app.services.watchlist import add_ticker, get_watched_tickers, remove_ticker

router = APIRouter()


class WatchlistRequest(BaseModel):
    ticker: str


async def _priced_watchlist() -> list[dict]:
    """Build the watchlist response: each ticker with its latest cached price.

    Tickers with no cached price yet report null price/prev_price and 0 change.
    """
    result: list[dict] = []
    for ticker in get_watched_tickers():
        update = await price_cache.get(ticker)
        if update is None:
            result.append(
                {
                    "ticker": ticker,
                    "price": None,
                    "prev_price": None,
                    "change_pct": 0.0,
                    "timestamp": None,
                }
            )
        else:
            result.append(
                {
                    "ticker": ticker,
                    "price": update.price,
                    "prev_price": update.prev_price,
                    "change_pct": update.change_pct,
                    "timestamp": update.timestamp,
                }
            )
    return result


@router.get("/api/watchlist")
async def list_watchlist() -> list[dict]:
    """Return the current watchlist with latest prices."""
    return await _priced_watchlist()


@router.post("/api/watchlist")
async def add(req: WatchlistRequest) -> list[dict]:
    """Add a ticker and return the updated priced watchlist."""
    try:
        await add_ticker(req.ticker)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return await _priced_watchlist()


@router.delete("/api/watchlist/{ticker}")
async def remove(ticker: str) -> list[dict]:
    """Remove a ticker and return the updated priced watchlist."""
    await remove_ticker(ticker)
    return await _priced_watchlist()
