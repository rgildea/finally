"""Unit tests for LLM chat integration: context builder, history loader, LLM call."""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.db.database as db_module
from app.chat.context import build_portfolio_context, load_recent_history
from app.chat.llm import (
    EXTRA_BODY,
    MODEL,
    ChatResponse,
    TradeAction,
    get_llm_response,
)
from app.db.database import get_connection, init_db
from app.market.cache import price_cache
from app.market.interface import PriceUpdate


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    """Point DB_PATH at a fresh temp file for every test."""
    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "test.db")
    init_db()


def _make_price(ticker: str, price: float) -> PriceUpdate:
    return PriceUpdate(
        ticker=ticker, price=price, prev_price=price, timestamp="2024-01-01T00:00:00Z"
    )


def _insert_message(role: str, content: str) -> None:
    """Insert a chat_messages row directly for test setup."""
    import uuid
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    con = get_connection()
    try:
        with con:
            con.execute(
                "INSERT INTO chat_messages (id, user_id, role, content, actions, created_at) "
                "VALUES (?, 'default', ?, ?, NULL, ?)",
                (str(uuid.uuid4()), role, content, now),
            )
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Task 1: Context builder and history loader tests (CHAT-02)
# ---------------------------------------------------------------------------


async def test_load_recent_history_chronological():
    """Empty DB returns []; after inserts, messages are returned oldest-first."""
    result = load_recent_history()
    assert result == []

    _insert_message("user", "Hello")
    _insert_message("assistant", "Hi there")

    result = load_recent_history()
    assert len(result) == 2
    assert result[0] == {"role": "user", "content": "Hello"}
    assert result[1] == {"role": "assistant", "content": "Hi there"}


async def test_load_recent_history_limit():
    """Inserting 15 messages and calling with limit=10 returns exactly 10, most-recent, chronological."""
    for i in range(15):
        role = "user" if i % 2 == 0 else "assistant"
        _insert_message(role, f"message {i}")

    result = load_recent_history(limit=10)
    assert len(result) == 10
    # Should be the last 10 (messages 5-14), in chronological order
    assert result[0]["content"] == "message 5"
    assert result[-1]["content"] == "message 14"


async def test_context_includes_portfolio(monkeypatch):
    """build_portfolio_context includes cash, a known position ticker, and a watchlist ticker."""
    from app.routers.portfolio import execute_trade

    # Seed a position
    execute_trade("AAPL", "buy", 10, 100.0)

    # Mock price cache to return prices
    aapl_price = _make_price("AAPL", 150.0)
    msft_price = _make_price("MSFT", 300.0)
    monkeypatch.setattr(
        price_cache,
        "get_many",
        AsyncMock(return_value={"AAPL": aapl_price, "MSFT": msft_price}),
    )

    context = await build_portfolio_context()

    assert "9,000.00" in context  # cash after buy: 10000 - 1000 = 9000
    assert "AAPL" in context
    assert "MSFT" in context  # watchlist ticker (default seed)


async def test_context_empty_positions(monkeypatch):
    """build_portfolio_context with no positions still includes cash and watchlist."""
    monkeypatch.setattr(
        price_cache, "get_many", AsyncMock(return_value={})
    )

    context = await build_portfolio_context()

    assert "10,000.00" in context  # default cash
    # Should not crash and should have some content
    assert isinstance(context, str)
    assert len(context) > 0


# ---------------------------------------------------------------------------
# Task 2: LLM call tests (CHAT-03, CHAT-06, TEST-03)
# ---------------------------------------------------------------------------


async def test_mock_mode(monkeypatch):
    """When LLM_MOCK=true, get_llm_response returns deterministic ChatResponse without calling acompletion."""
    monkeypatch.setenv("LLM_MOCK", "true")

    # Patch acompletion to raise if called — proves it's not invoked
    with patch("app.chat.llm.acompletion", new_callable=AsyncMock) as mock_acomplete:
        mock_acomplete.side_effect = AssertionError("acompletion should not be called in mock mode")
        result = await get_llm_response([{"role": "user", "content": "hi"}])

    assert isinstance(result, ChatResponse)
    assert isinstance(result.message, str)
    assert result.trades == []
    assert result.watchlist_changes == []


async def test_parse_valid_response(monkeypatch):
    """When acompletion returns valid structured JSON, ChatResponse fields are parsed correctly."""
    monkeypatch.setenv("LLM_MOCK", "false")

    valid_payload = {
        "message": "I recommend buying TSLA.",
        "trades": [{"ticker": "TSLA", "side": "buy", "quantity": 5}],
        "watchlist_changes": [],
    }
    mock_response = MagicMock()
    mock_response.choices[0].message.content = json.dumps(valid_payload)

    with patch("app.chat.llm.acompletion", new_callable=AsyncMock, return_value=mock_response):
        result = await get_llm_response([{"role": "user", "content": "What should I buy?"}])

    assert isinstance(result, ChatResponse)
    assert result.message == "I recommend buying TSLA."
    assert len(result.trades) == 1
    assert result.trades[0].ticker == "TSLA"
    assert result.trades[0].side == "buy"
    assert result.trades[0].quantity == 5
    assert result.watchlist_changes == []


async def test_parse_malformed_response(monkeypatch):
    """When acompletion returns malformed JSON, get_llm_response returns graceful ChatResponse."""
    monkeypatch.setenv("LLM_MOCK", "false")

    mock_response = MagicMock()
    mock_response.choices[0].message.content = '{"invalid": true}'

    with patch("app.chat.llm.acompletion", new_callable=AsyncMock, return_value=mock_response):
        result = await get_llm_response([{"role": "user", "content": "test"}])

    assert isinstance(result, ChatResponse)
    assert "error" in result.message.lower() or "encountered" in result.message.lower()
    assert result.trades == []
    assert result.watchlist_changes == []


async def test_llm_called_with_correct_params(monkeypatch):
    """In real mode, acompletion is called with model=MODEL, response_format=ChatResponse, reasoning_effort='low', extra_body=EXTRA_BODY."""
    monkeypatch.setenv("LLM_MOCK", "false")

    valid_payload = {
        "message": "OK",
        "trades": [],
        "watchlist_changes": [],
    }
    mock_response = MagicMock()
    mock_response.choices[0].message.content = json.dumps(valid_payload)

    messages = [{"role": "user", "content": "hello"}]

    with patch("app.chat.llm.acompletion", new_callable=AsyncMock, return_value=mock_response) as mock_acomplete:
        await get_llm_response(messages)

    mock_acomplete.assert_awaited_once_with(
        model=MODEL,
        messages=messages,
        response_format=ChatResponse,
        reasoning_effort="low",
        extra_body=EXTRA_BODY,
    )
