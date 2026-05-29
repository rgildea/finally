"""Chat orchestration: load context, call the LLM, auto-execute actions, persist
messages, and expose a token-by-token async stream for the SSE endpoint.

The endpoint consumes :func:`run_chat`, which yields protocol events:
``("token", {...})`` repeated, then ``("action", {...})``, then
``("done", {...})`` — or ``("error", {...})`` on failure.
"""

from collections.abc import AsyncIterator

from app import db
from app.config import LLM_MOCK
from app.market.cache import price_cache
from app.services import portfolio as portfolio_service
from app.services import trading, watchlist

from .client import complete_chat
from .mock import mock_chat
from .prompt import build_messages
from .schema import ChatResponse, TradeAction, WatchlistChange

# Token chunk size when slicing the reply for streaming.
_CHUNK_SIZE = 12


async def run_chat(user_message: str) -> AsyncIterator[tuple[str, dict]]:
    """Drive one chat turn, yielding (event_name, data) protocol tuples.

    On any failure an ``("error", {"detail": ...})`` event is yielded and the
    stream ends.
    """
    try:
        response = await _generate_response(user_message)
    except Exception as exc:  # noqa: BLE001 — surface a user-safe error event
        yield "error", {"detail": f"Chat failed: {exc}"}
        return

    executed = await _execute_actions(response)

    await db.insert_chat_message(role="user", content=user_message, actions=None)
    assistant_row = await db.insert_chat_message(
        role="assistant", content=response.message, actions=executed
    )

    for chunk in _chunk_text(response.message):
        yield "token", {"text": chunk}
    yield "action", executed
    yield "done", {"message_id": assistant_row["id"]}


async def _generate_response(user_message: str) -> ChatResponse:
    """Call the mock or the live LLM with full context, returning a ChatResponse."""
    portfolio = await portfolio_service.get_portfolio()
    watch = await _watchlist_with_prices()
    history = await db.list_chat_messages(limit=20)
    messages = build_messages(user_message, portfolio, watch, history)
    if LLM_MOCK:
        return mock_chat(messages)
    return await complete_chat(messages)


async def _watchlist_with_prices() -> list[dict]:
    """Watchlist tickers paired with their latest cached prices."""
    tickers = await db.list_watchlist()
    result: list[dict] = []
    for ticker in tickers:
        update = await price_cache.get(ticker)
        if update is None:
            result.append({"ticker": ticker, "price": None, "change_pct": 0.0})
        else:
            result.append(
                {
                    "ticker": ticker,
                    "price": update.price,
                    "change_pct": update.change_pct,
                }
            )
    return result


async def _execute_actions(response: ChatResponse) -> dict:
    """Auto-execute the response's trades and watchlist changes.

    Returns a JSON-serialisable record of results; per-action failures are
    captured as ``{"error": ...}`` rather than aborting the turn.
    """
    return {
        "trades": [await _run_trade(t) for t in response.trades],
        "watchlist_changes": [await _run_watchlist(w) for w in response.watchlist_changes],
    }


async def _run_trade(trade: TradeAction) -> dict:
    try:
        return await trading.execute_trade(trade.ticker, trade.side, trade.quantity)
    except trading.TradeError as exc:
        return {
            "ticker": trade.ticker,
            "side": trade.side,
            "quantity": trade.quantity,
            "error": str(exc),
        }


async def _run_watchlist(change: WatchlistChange) -> dict:
    try:
        if change.action == "add":
            await watchlist.add_ticker(change.ticker)
        else:
            await watchlist.remove_ticker(change.ticker)
        return {"ticker": change.ticker, "action": change.action}
    except Exception as exc:  # noqa: BLE001 — user-safe error in the record
        return {"ticker": change.ticker, "action": change.action, "error": str(exc)}


def _chunk_text(text: str) -> list[str]:
    """Split text into fixed-size chunks for token-by-token streaming."""
    if not text:
        return []
    return [text[i : i + _CHUNK_SIZE] for i in range(0, len(text), _CHUNK_SIZE)]
