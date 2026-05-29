"""Mock LLM determinism and trigger behaviour."""

from app.llm.mock import mock_chat


def _user(text: str) -> list[dict]:
    return [{"role": "user", "content": text}]


def test_buy_trigger_creates_aapl_buy():
    resp = mock_chat(_user("please buy something"))
    assert len(resp.trades) == 1
    assert resp.trades[0].ticker == "AAPL"
    assert resp.trades[0].side == "buy"
    assert resp.trades[0].quantity == 1


def test_sell_trigger_creates_aapl_sell():
    resp = mock_chat(_user("sell my shares"))
    assert resp.trades[0].side == "sell"


def test_watch_trigger_adds_pypl():
    resp = mock_chat(_user("watch PYPL for me"))
    assert resp.trades == []
    assert resp.watchlist_changes[0].ticker == "PYPL"
    assert resp.watchlist_changes[0].action == "add"


def test_default_has_no_actions():
    resp = mock_chat(_user("how is my portfolio?"))
    assert resp.trades == []
    assert resp.watchlist_changes == []
    assert resp.message


def test_deterministic_across_calls():
    a = mock_chat(_user("buy now"))
    b = mock_chat(_user("buy now"))
    assert a.model_dump() == b.model_dump()


def test_uses_last_user_message():
    messages = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
        {"role": "user", "content": "buy AAPL"},
    ]
    resp = mock_chat(messages)
    assert resp.trades[0].side == "buy"
