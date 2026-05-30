"""Portfolio context builder and chat history loader for LLM prompt construction."""
from app.db.database import get_connection
from app.market.cache import price_cache


async def build_portfolio_context() -> str:
    """Build a prompt string with cash balance, positions+P&L, and watchlist+prices."""
    con = get_connection()
    try:
        profile = con.execute(
            "SELECT cash_balance FROM users_profile WHERE id='default'"
        ).fetchone()
        positions = con.execute(
            "SELECT ticker, quantity, avg_cost FROM positions WHERE user_id='default'"
        ).fetchall()
        watchlist = con.execute(
            "SELECT ticker FROM watchlist WHERE user_id='default' ORDER BY added_at"
        ).fetchall()
    finally:
        con.close()

    cash = profile["cash_balance"] if profile else 0.0
    position_tickers = [r["ticker"] for r in positions]
    watchlist_tickers = [r["ticker"] for r in watchlist]
    all_tickers = list(set(position_tickers + watchlist_tickers))

    prices = await price_cache.get_many(all_tickers) if all_tickers else {}

    lines = [f"Cash balance: ${cash:,.2f}"]

    lines.append("\nPositions:")
    if positions:
        for row in positions:
            ticker = row["ticker"]
            qty = row["quantity"]
            avg_cost = row["avg_cost"]
            current_price = prices[ticker].price if ticker in prices else avg_cost
            unrealized_pnl = (current_price - avg_cost) * qty
            lines.append(
                f"  {ticker}: qty={qty}, avg_cost=${avg_cost:.2f}, "
                f"current=${current_price:.2f}, unrealized_pnl=${unrealized_pnl:.2f}"
            )
    else:
        lines.append("  (no positions)")

    lines.append("\nWatchlist:")
    if watchlist_tickers:
        for ticker in watchlist_tickers:
            price = prices[ticker].price if ticker in prices else None
            price_str = f"${price:.2f}" if price is not None else "N/A"
            lines.append(f"  {ticker}: {price_str}")
    else:
        lines.append("  (empty)")

    return "\n".join(lines)


def load_recent_history(limit: int = 10) -> list[dict]:
    """Return the last `limit` chat messages as role/content dicts, oldest first."""
    con = get_connection()
    try:
        rows = con.execute(
            "SELECT role, content FROM chat_messages WHERE user_id='default' "
            "ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]
    finally:
        con.close()
