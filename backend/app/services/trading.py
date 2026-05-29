"""Trading service.

Executes market orders against the current cached price. Shared by the REST
trade endpoint and the LLM auto-executor, so all trade validation lives here.
"""

from app.db import queries
from app.market.cache import price_cache


class TradeError(Exception):
    """Raised on trade validation failure. The message is user-safe."""


async def execute_trade(ticker: str, side: str, quantity: float) -> dict:
    """Execute a market order, filling at the latest cached price.

    Validates quantity, side, price availability, and sufficient cash (buy) or
    shares (sell). Updates the position and cash balance and records the trade.

    Returns a dict with the fill details, resulting cash balance, and the
    updated position (or None if the position was fully closed).

    Raises:
        TradeError: on any validation failure.
    """
    ticker = ticker.strip().upper()
    side = side.strip().lower()

    if side not in {"buy", "sell"}:
        raise TradeError("Side must be 'buy' or 'sell'")
    if quantity <= 0:
        raise TradeError("Quantity must be positive")

    update = await price_cache.get(ticker)
    if update is None:
        raise TradeError(f"No price available for {ticker}")
    price = update.price

    profile = await queries.get_profile()
    cash = profile["cash_balance"]
    position = await queries.get_position(ticker)

    if side == "buy":
        cash, new_position = _apply_buy(ticker, quantity, price, cash, position)
    else:
        cash, new_position = _apply_sell(ticker, quantity, price, cash, position)

    await queries.set_cash_balance(cash)
    if new_position is None:
        await queries.delete_position(ticker)
    else:
        await queries.upsert_position(
            ticker, new_position["quantity"], new_position["avg_cost"]
        )
    await queries.insert_trade(ticker, side, quantity, price)

    return {
        "ticker": ticker,
        "side": side,
        "quantity": quantity,
        "price": price,
        "cash_balance": cash,
        "position": new_position,
    }


def _apply_buy(
    ticker: str,
    quantity: float,
    price: float,
    cash: float,
    position: dict | None,
) -> tuple[float, dict]:
    """Return (new_cash, new_position) for a buy, or raise TradeError."""
    cost = quantity * price
    if cost > cash:
        raise TradeError(
            f"Insufficient cash: need ${cost:.2f}, have ${cash:.2f}"
        )
    prev_qty = position["quantity"] if position else 0.0
    prev_cost = position["avg_cost"] if position else 0.0
    new_qty = prev_qty + quantity
    new_avg = (prev_qty * prev_cost + quantity * price) / new_qty
    return cash - cost, {"ticker": ticker, "quantity": new_qty, "avg_cost": new_avg}


def _apply_sell(
    ticker: str,
    quantity: float,
    price: float,
    cash: float,
    position: dict | None,
) -> tuple[float, dict | None]:
    """Return (new_cash, new_position|None) for a sell, or raise TradeError."""
    held = position["quantity"] if position else 0.0
    if quantity > held:
        raise TradeError(
            f"Insufficient shares: trying to sell {quantity}, hold {held}"
        )
    new_qty = held - quantity
    new_cash = cash + quantity * price
    if new_qty == 0:
        return new_cash, None
    return new_cash, {
        "ticker": ticker,
        "quantity": new_qty,
        "avg_cost": position["avg_cost"],
    }
