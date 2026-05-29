"""Portfolio REST endpoints: summary, trade execution, value history."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.db import queries
from app.services.portfolio import get_portfolio
from app.services.trading import TradeError, execute_trade

router = APIRouter()


class TradeRequest(BaseModel):
    ticker: str
    quantity: float
    side: str


@router.get("/api/portfolio")
async def portfolio() -> dict:
    """Return cash, positions with unrealized P&L, and portfolio totals."""
    return await get_portfolio()


@router.post("/api/portfolio/trade")
async def trade(req: TradeRequest) -> dict:
    """Execute a market order. Returns the fill result, or 400 on rejection."""
    try:
        return await execute_trade(req.ticker, req.side, req.quantity)
    except TradeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/api/portfolio/history")
async def history() -> dict:
    """Return portfolio value snapshots over time for the P&L chart."""
    snapshots = await queries.list_snapshots()
    return {"snapshots": snapshots}
