"""Watchlist router: GET/POST/DELETE endpoints for watched tickers."""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator

from app.db.database import get_connection
from app.market.cache import price_cache

router = APIRouter(prefix="/api", tags=["watchlist"])


class WatchlistRequest(BaseModel):
    ticker: str

    @field_validator("ticker")
    @classmethod
    def normalize_ticker(cls, v: str) -> str:
        v = v.upper().strip()
        if not v or len(v) > 10:
            raise ValueError("Invalid ticker")
        return v


@router.get("/watchlist")
async def get_watchlist() -> list:
    """Return all watched tickers with latest cached prices."""
    con = get_connection()
    try:
        rows = con.execute(
            "SELECT ticker FROM watchlist WHERE user_id='default' ORDER BY added_at"
        ).fetchall()
        tickers = [row["ticker"] for row in rows]
    finally:
        con.close()

    prices = await price_cache.get_many(tickers)
    return [
        {"ticker": t, "price": round(prices[t].price, 4) if t in prices else None}
        for t in tickers
    ]


@router.post("/watchlist")
def add_ticker(req: WatchlistRequest) -> dict:
    """Add a ticker to the watchlist. Idempotent via INSERT OR IGNORE."""
    now = datetime.now(timezone.utc).isoformat()
    con = get_connection()
    try:
        with con:
            con.execute(
                "INSERT OR IGNORE INTO watchlist (id, user_id, ticker, added_at) "
                "VALUES (?, 'default', ?, ?)",
                (str(uuid.uuid4()), req.ticker, now),
            )
    finally:
        con.close()
    return {"status": "ok", "ticker": req.ticker}


@router.delete("/watchlist/{ticker}")
async def remove_ticker(ticker: str) -> dict:
    """Remove a ticker from the watchlist and clear it from the price cache."""
    ticker = ticker.upper().strip()
    if not ticker or len(ticker) > 10:
        raise HTTPException(status_code=422, detail="Invalid ticker")
    con = get_connection()
    try:
        with con:
            con.execute(
                "DELETE FROM watchlist WHERE user_id='default' AND ticker=?",
                (ticker,),
            )
    finally:
        con.close()
    await price_cache.remove(ticker)
    return {"status": "ok", "ticker": ticker}
