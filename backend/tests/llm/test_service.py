"""Chat service orchestration: action execution, persistence, and the streamed
event protocol. Dependencies (db, services, LLM) are monkeypatched so the test
is hermetic."""

import pytest

from app.llm import service
from app.llm.schema import ChatResponse, TradeAction, WatchlistChange


@pytest.fixture
def patched(monkeypatch):
    """Patch the service's collaborators and capture persisted messages."""
    saved: list[dict] = []
    calls = {"trades": [], "watchlist_add": [], "watchlist_remove": []}

    async def fake_get_portfolio():
        return {"cash_balance": 10000.0, "positions": []}

    async def fake_list_watchlist():
        return ["AAPL"]

    async def fake_list_chat_messages(limit=20):
        return []

    async def fake_insert_chat_message(role, content, actions):
        row = {"id": f"id-{len(saved)}", "role": role, "content": content, "actions": actions}
        saved.append(row)
        return row

    async def fake_execute_trade(ticker, side, quantity):
        calls["trades"].append((ticker, side, quantity))
        return {"ticker": ticker, "side": side, "quantity": quantity, "price": 100.0}

    async def fake_add_ticker(ticker):
        calls["watchlist_add"].append(ticker)
        return ["AAPL", ticker]

    async def fake_remove_ticker(ticker):
        calls["watchlist_remove"].append(ticker)
        return ["AAPL"]

    monkeypatch.setattr(service.portfolio_service, "get_portfolio", fake_get_portfolio)
    monkeypatch.setattr(service.db, "list_watchlist", fake_list_watchlist)
    monkeypatch.setattr(service.db, "list_chat_messages", fake_list_chat_messages)
    monkeypatch.setattr(service.db, "insert_chat_message", fake_insert_chat_message)
    monkeypatch.setattr(service.trading, "execute_trade", fake_execute_trade)
    monkeypatch.setattr(service.watchlist, "add_ticker", fake_add_ticker)
    monkeypatch.setattr(service.watchlist, "remove_ticker", fake_remove_ticker)

    async def fake_get(ticker):
        return None

    monkeypatch.setattr(service.price_cache, "get", fake_get)
    return saved, calls


async def _collect(message: str):
    return [evt async for evt in service.run_chat(message)]


def _set_response(monkeypatch, response: ChatResponse):
    async def fake_generate(_message):
        return response

    monkeypatch.setattr(service, "_generate_response", fake_generate)


async def test_plain_reply_streams_tokens_then_done(patched, monkeypatch):
    saved, calls = patched
    _set_response(monkeypatch, ChatResponse(message="Hello there friend"))

    events = await _collect("hi")

    names = [name for name, _ in events]
    assert names[-2:] == ["action", "done"]
    assert "token" in names
    text = "".join(d["text"] for n, d in events if n == "token")
    assert text == "Hello there friend"
    assert events[-1][1]["message_id"] == saved[-1]["id"]


async def test_buy_trade_is_executed_and_recorded(patched, monkeypatch):
    saved, calls = patched
    _set_response(
        monkeypatch,
        ChatResponse(
            message="Buying", trades=[TradeAction(ticker="AAPL", side="buy", quantity=2)]
        ),
    )

    events = await _collect("buy")

    assert calls["trades"] == [("AAPL", "buy", 2)]
    action_evt = next(d for n, d in events if n == "action")
    assert action_evt["trades"][0]["ticker"] == "AAPL"
    # assistant message persisted with executed actions
    assistant = saved[-1]
    assert assistant["role"] == "assistant"
    assert assistant["actions"]["trades"][0]["ticker"] == "AAPL"


async def test_user_and_assistant_messages_persisted(patched, monkeypatch):
    saved, calls = patched
    _set_response(monkeypatch, ChatResponse(message="ok"))

    await _collect("question")

    assert [m["role"] for m in saved] == ["user", "assistant"]
    assert saved[0]["content"] == "question"
    assert saved[0]["actions"] is None


async def test_watchlist_change_executed(patched, monkeypatch):
    saved, calls = patched
    _set_response(
        monkeypatch,
        ChatResponse(
            message="Adding",
            watchlist_changes=[WatchlistChange(ticker="PYPL", action="add")],
        ),
    )

    events = await _collect("watch PYPL")

    assert calls["watchlist_add"] == ["PYPL"]
    action_evt = next(d for n, d in events if n == "action")
    assert action_evt["watchlist_changes"][0] == {"ticker": "PYPL", "action": "add"}


async def test_failed_trade_recorded_as_error_not_aborted(patched, monkeypatch):
    saved, calls = patched

    async def failing_trade(ticker, side, quantity):
        raise service.trading.TradeError("Insufficient cash")

    monkeypatch.setattr(service.trading, "execute_trade", failing_trade)
    _set_response(
        monkeypatch,
        ChatResponse(
            message="Trying", trades=[TradeAction(ticker="AAPL", side="buy", quantity=999)]
        ),
    )

    events = await _collect("buy lots")

    action_evt = next(d for n, d in events if n == "action")
    assert action_evt["trades"][0]["error"] == "Insufficient cash"
    assert [n for n, _ in events][-1] == "done"


async def test_generation_failure_yields_error_event(patched, monkeypatch):
    saved, calls = patched

    async def boom(_message):
        raise RuntimeError("model down")

    monkeypatch.setattr(service, "_generate_response", boom)

    events = await _collect("hi")

    assert len(events) == 1
    name, data = events[0]
    assert name == "error"
    assert "model down" in data["detail"]
    assert saved == []  # nothing persisted on failure
