"""Structured-output schema parsing and malformed-response handling."""

import pytest
from pydantic import ValidationError

from app.llm.schema import ChatResponse


def test_minimal_message_only():
    resp = ChatResponse.model_validate_json('{"message": "Hello"}')
    assert resp.message == "Hello"
    assert resp.trades == []
    assert resp.watchlist_changes == []


def test_full_payload():
    payload = (
        '{"message": "Done", '
        '"trades": [{"ticker": "AAPL", "side": "buy", "quantity": 10}], '
        '"watchlist_changes": [{"ticker": "PYPL", "action": "add"}]}'
    )
    resp = ChatResponse.model_validate_json(payload)
    assert resp.trades[0].ticker == "AAPL"
    assert resp.trades[0].side == "buy"
    assert resp.trades[0].quantity == 10
    assert resp.watchlist_changes[0].action == "add"


def test_missing_message_rejected():
    with pytest.raises(ValidationError):
        ChatResponse.model_validate_json('{"trades": []}')


def test_invalid_side_rejected():
    payload = '{"message": "x", "trades": [{"ticker": "AAPL", "side": "hold", "quantity": 1}]}'
    with pytest.raises(ValidationError):
        ChatResponse.model_validate_json(payload)


def test_malformed_json_rejected():
    with pytest.raises(ValidationError):
        ChatResponse.model_validate_json("not json at all")
