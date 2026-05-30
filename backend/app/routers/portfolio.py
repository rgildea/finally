"""Portfolio router: positions, trade execution, history, and snapshot recorder."""
import asyncio
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator

from app.db.database import get_connection
from app.market.cache import price_cache

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["portfolio"])


# ---------------------------------------------------------------------------
# Request model
# ---------------------------------------------------------------------------


class TradeRequest(BaseModel):
    ticker: str
    side: str
    quantity: float

    @field_validator("ticker")
    @classmethod
    def normalize_ticker(cls, v: str) -> str:
        v = v.upper().strip()
        if not v or len(v) > 10:
            raise ValueError("Invalid ticker")
        return v

    @field_validator("side")
    @classmethod
    def validate_side(cls, v: str) -> str:
        if v not in ("buy", "sell"):
            raise ValueError("side must be 'buy' or 'sell'")
        return v

    @field_validator("quantity")
    @classmethod
    def validate_quantity(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("quantity must be positive")
        return v


# ---------------------------------------------------------------------------
# Trade execution helper (synchronous — price already resolved by caller)
# ---------------------------------------------------------------------------


def execute_trade(ticker: str, side: str, quantity: float, price: float) -> dict:
    """Execute a buy or sell atomically. Raises ValueError on validation failure."""
    cost = quantity * price
    now = datetime.now(timezone.utc).isoformat()
    con = get_connection()
    try:
        with con:
            profile = con.execute(
                "SELECT cash_balance FROM users_profile WHERE id='default'"
            ).fetchone()

            if side == "buy":
                if profile["cash_balance"] < cost:
                    raise ValueError("Insufficient cash")
                existing = con.execute(
                    "SELECT id, quantity, avg_cost FROM positions WHERE user_id='default' AND ticker=?",
                    (ticker,),
                ).fetchone()
                if existing:
                    new_qty = existing["quantity"] + quantity
                    new_avg = (existing["quantity"] * existing["avg_cost"] + quantity * price) / new_qty
                    con.execute(
                        "UPDATE positions SET quantity=?, avg_cost=?, updated_at=? WHERE id=?",
                        (new_qty, new_avg, now, existing["id"]),
                    )
                else:
                    con.execute(
                        "INSERT INTO positions (id, user_id, ticker, quantity, avg_cost, updated_at) "
                        "VALUES (?, 'default', ?, ?, ?, ?)",
                        (str(uuid.uuid4()), ticker, quantity, price, now),
                    )
                con.execute(
                    "UPDATE users_profile SET cash_balance = cash_balance - ? WHERE id='default'",
                    (cost,),
                )

            elif side == "sell":
                existing = con.execute(
                    "SELECT id, quantity FROM positions WHERE user_id='default' AND ticker=?",
                    (ticker,),
                ).fetchone()
                if not existing or existing["quantity"] < quantity:
                    raise ValueError("Insufficient shares")
                remaining = existing["quantity"] - quantity
                if remaining == 0:
                    con.execute("DELETE FROM positions WHERE id=?", (existing["id"],))
                else:
                    con.execute(
                        "UPDATE positions SET quantity=?, updated_at=? WHERE id=?",
                        (remaining, now, existing["id"]),
                    )
                con.execute(
                    "UPDATE users_profile SET cash_balance = cash_balance + ? WHERE id='default'",
                    (cost,),
                )

            con.execute(
                "INSERT INTO trades (id, user_id, ticker, side, quantity, price, executed_at) "
                "VALUES (?, 'default', ?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), ticker, side, quantity, price, now),
            )
    finally:
        con.close()

    return {"status": "ok", "ticker": ticker, "side": side, "quantity": quantity, "price": price}


# ---------------------------------------------------------------------------
# Shared portfolio math helpers
# ---------------------------------------------------------------------------


async def _compute_total_value() -> float:
    """Compute current total portfolio value (cash + market value of positions)."""
    con = get_connection()
    try:
        profile = con.execute(
            "SELECT cash_balance FROM users_profile WHERE id='default'"
        ).fetchone()
        rows = con.execute(
            "SELECT ticker, quantity, avg_cost FROM positions WHERE user_id='default'"
        ).fetchall()
    finally:
        con.close()

    tickers = [r["ticker"] for r in rows]
    prices = await price_cache.get_many(tickers) if tickers else {}

    total_market_value = 0.0
    for row in rows:
        ticker = row["ticker"]
        qty = row["quantity"]
        avg_cost = row["avg_cost"]
        current_price = prices[ticker].price if ticker in prices else avg_cost
        total_market_value += qty * current_price

    return round(profile["cash_balance"] + total_market_value, 2)


def _write_snapshot(total_value: float) -> None:
    """Insert one portfolio_snapshots row."""
    now = datetime.now(timezone.utc).isoformat()
    con = get_connection()
    try:
        with con:
            con.execute(
                "INSERT INTO portfolio_snapshots (id, user_id, total_value, recorded_at) "
                "VALUES (?, 'default', ?, ?)",
                (str(uuid.uuid4()), total_value, now),
            )
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Background snapshot task
# ---------------------------------------------------------------------------


async def snapshot_recorder() -> None:
    """Record portfolio total value to portfolio_snapshots every 30 seconds."""
    while True:
        await asyncio.sleep(30)
        try:
            total = await _compute_total_value()
            _write_snapshot(total)
        except Exception:
            logger.exception("Error recording portfolio snapshot — will retry")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/portfolio")
async def get_portfolio() -> dict:
    """Return cash balance, total value, and all positions with live P&L."""
    con = get_connection()
    try:
        profile = con.execute(
            "SELECT cash_balance FROM users_profile WHERE id='default'"
        ).fetchone()
        rows = con.execute(
            "SELECT ticker, quantity, avg_cost FROM positions WHERE user_id='default'"
        ).fetchall()
    finally:
        con.close()

    tickers = [r["ticker"] for r in rows]
    prices = await price_cache.get_many(tickers) if tickers else {}

    positions = []
    total_market_value = 0.0
    for row in rows:
        ticker = row["ticker"]
        qty = row["quantity"]
        avg_cost = row["avg_cost"]
        current_price = prices[ticker].price if ticker in prices else avg_cost
        market_value = qty * current_price
        unrealized_pnl = (current_price - avg_cost) * qty
        pnl_pct = (current_price - avg_cost) / avg_cost * 100 if avg_cost else 0.0
        total_market_value += market_value
        positions.append({
            "ticker": ticker,
            "quantity": qty,
            "avg_cost": round(avg_cost, 4),
            "current_price": round(current_price, 4),
            "market_value": round(market_value, 2),
            "unrealized_pnl": round(unrealized_pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
        })

    total_value = round(profile["cash_balance"] + total_market_value, 2)
    return {
        "cash_balance": round(profile["cash_balance"], 2),
        "total_value": total_value,
        "positions": positions,
    }


@router.post("/portfolio/trade")
async def trade(req: TradeRequest) -> dict:
    """Execute a trade at the current cached price."""
    update = await price_cache.get(req.ticker)
    if update is None:
        raise HTTPException(status_code=503, detail="Price not available for ticker")
    try:
        result = execute_trade(req.ticker, req.side, req.quantity, update.price)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Record a portfolio snapshot after each trade
    try:
        total = await _compute_total_value()
        _write_snapshot(total)
    except Exception:
        logger.exception("Failed to record snapshot after trade — non-fatal")

    return result


@router.get("/portfolio/history")
def portfolio_history() -> list:
    """Return portfolio value snapshots in chronological order."""
    con = get_connection()
    try:
        rows = con.execute(
            "SELECT id, total_value, recorded_at FROM portfolio_snapshots "
            "WHERE user_id='default' ORDER BY recorded_at"
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        con.close()
