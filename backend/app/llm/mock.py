"""Deterministic mock LLM used when ``LLM_MOCK=true``.

No network calls. The reply is derived from the latest user message so E2E tests
can assert behaviour without an API key.

Mock triggers (case-insensitive substring match on the user's message):

- contains ``"buy"``  -> a single trade: buy 1 share of AAPL
- contains ``"sell"`` -> a single trade: sell 1 share of AAPL
- contains ``"watch"`` -> a watchlist change: add PYPL
- otherwise           -> a plain conversational reply, no actions

The conversational ``message`` is fixed per branch so tests are reproducible.
"""

from .schema import ChatResponse, TradeAction, WatchlistChange


def mock_chat(messages: list[dict]) -> ChatResponse:
    """Return a deterministic ChatResponse based on the last user message."""
    user_text = _last_user_message(messages).lower()

    if "buy" in user_text:
        return ChatResponse(
            message="Buying 1 share of AAPL for you.",
            trades=[TradeAction(ticker="AAPL", side="buy", quantity=1)],
        )
    if "sell" in user_text:
        return ChatResponse(
            message="Selling 1 share of AAPL for you.",
            trades=[TradeAction(ticker="AAPL", side="sell", quantity=1)],
        )
    if "watch" in user_text:
        return ChatResponse(
            message="Adding PYPL to your watchlist.",
            watchlist_changes=[WatchlistChange(ticker="PYPL", action="add")],
        )
    return ChatResponse(message="I'm FinAlly, your trading assistant. How can I help?")


def _last_user_message(messages: list[dict]) -> str:
    for msg in reversed(messages):
        if msg.get("role") == "user":
            return str(msg.get("content", ""))
    return ""
