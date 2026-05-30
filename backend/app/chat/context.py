"""Portfolio context builder and chat history loader for LLM prompt construction."""
from app.db.database import get_connection
from app.market.cache import price_cache


async def build_portfolio_context() -> str:
    """Build a prompt string with cash balance, positions+P&L, and watchlist+prices."""
    raise NotImplementedError


def load_recent_history(limit: int = 10) -> list[dict]:
    """Return the last `limit` chat messages as role/content dicts, oldest first."""
    raise NotImplementedError
