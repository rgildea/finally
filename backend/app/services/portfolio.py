"""Portfolio service.

Computes the portfolio summary (cash, positions with unrealized P&L, totals)
from the database plus the live price cache, and records value snapshots that
feed the P&L chart.
"""

from app.db import queries
from app.market.cache import price_cache


async def get_portfolio() -> dict:
    """Return the portfolio summary in the shape defined in CONTRACT §4.

    Positions are priced from the live cache. A position whose ticker has no
    cached price falls back to its average cost so totals remain coherent.
    """
    profile = await queries.get_profile()
    cash = profile["cash_balance"]
    raw_positions = await queries.list_positions()

    positions: list[dict] = []
    positions_value = 0.0
    total_cost = 0.0

    for pos in raw_positions:
        ticker = pos["ticker"]
        quantity = pos["quantity"]
        avg_cost = pos["avg_cost"]
        update = await price_cache.get(ticker)
        current_price = update.price if update else avg_cost
        market_value = quantity * current_price
        cost_basis = quantity * avg_cost
        unrealized_pl = market_value - cost_basis
        unrealized_pl_pct = (unrealized_pl / cost_basis * 100) if cost_basis else 0.0

        positions_value += market_value
        total_cost += cost_basis
        positions.append(
            {
                "ticker": ticker,
                "quantity": quantity,
                "avg_cost": avg_cost,
                "current_price": current_price,
                "market_value": market_value,
                "unrealized_pl": unrealized_pl,
                "unrealized_pl_pct": unrealized_pl_pct,
            }
        )

    total_value = cash + positions_value
    total_pl = positions_value - total_cost
    total_pl_pct = (total_pl / total_cost * 100) if total_cost else 0.0

    return {
        "cash_balance": cash,
        "positions_value": positions_value,
        "total_value": total_value,
        "total_pl": total_pl,
        "total_pl_pct": total_pl_pct,
        "positions": positions,
    }


async def record_snapshot() -> None:
    """Compute the current total portfolio value and persist a snapshot."""
    portfolio = await get_portfolio()
    await queries.insert_snapshot(portfolio["total_value"])
