"""Chat router: POST /api/chat — LLM structured response, auto-execution, SSE streaming."""
import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.chat.context import build_portfolio_context, load_recent_history
from app.chat.llm import ChatResponse, build_system_messages, get_llm_response
from app.db.database import get_connection
from app.market.cache import price_cache
from app.routers.portfolio import execute_trade

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["chat"])


class ChatRequest(BaseModel):
    message: str


def _save_message(role: str, content: str, actions: dict | None = None) -> None:
    """Insert one chat_messages row."""
    now = datetime.now(timezone.utc).isoformat()
    con = get_connection()
    try:
        with con:
            con.execute(
                "INSERT INTO chat_messages (id, user_id, role, content, actions, created_at) "
                "VALUES (?, 'default', ?, ?, ?, ?)",
                (str(uuid.uuid4()), role, content, json.dumps(actions) if actions else None, now),
            )
    finally:
        con.close()


async def _execute_side_effects(resp: ChatResponse) -> dict:
    """Execute trades and watchlist changes from the LLM response. Returns actions dict."""
    actions: dict = {"trades": [], "watchlist_changes": [], "errors": []}

    for trade in resp.trades:
        ticker = trade.ticker.upper().strip()
        update = await price_cache.get(ticker)
        if update is None:
            actions["errors"].append(f"No price available for {ticker}")
            continue
        try:
            result = execute_trade(ticker, trade.side, trade.quantity, update.price)
            actions["trades"].append(result)
        except ValueError as e:
            actions["errors"].append(str(e))

    for change in resp.watchlist_changes:
        ticker = change.ticker.upper().strip()
        if change.action == "add":
            now = datetime.now(timezone.utc).isoformat()
            con = get_connection()
            try:
                with con:
                    con.execute(
                        "INSERT OR IGNORE INTO watchlist (id, user_id, ticker, added_at) "
                        "VALUES (?, 'default', ?, ?)",
                        (str(uuid.uuid4()), ticker, now),
                    )
            finally:
                con.close()
            actions["watchlist_changes"].append({"ticker": ticker, "action": "add"})
        elif change.action == "remove":
            con = get_connection()
            try:
                with con:
                    con.execute(
                        "DELETE FROM watchlist WHERE user_id='default' AND ticker=?",
                        (ticker,),
                    )
            finally:
                con.close()
            await price_cache.remove(ticker)
            actions["watchlist_changes"].append({"ticker": ticker, "action": "remove"})

    return actions


async def _stream_text(text: str):
    """Yield message text word-by-word as SSE data events, ending with [DONE]."""
    for word in text.split(" "):
        yield f"data: {word} \n\n"
        await asyncio.sleep(0)
    yield "data: [DONE]\n\n"


@router.post("/chat")
async def chat(req: ChatRequest):
    """Persist user message, call LLM, auto-execute side effects, persist assistant response, stream reply."""
    # 1. Persist user message
    _save_message("user", req.message)

    # 2. Build messages: system prompt + portfolio context + history + new user message
    messages = build_system_messages()
    context = await build_portfolio_context()
    messages.append({"role": "user", "content": f"Portfolio context:\n{context}"})
    messages.extend(load_recent_history())
    messages.append({"role": "user", "content": req.message})

    # 3. Call LLM (structured, non-streaming)
    resp = await get_llm_response(messages)

    # 4. Execute side effects (all before streaming begins)
    actions = await _execute_side_effects(resp)

    # 5. Surface errors in the reply message
    if actions["errors"]:
        error_summary = "; ".join(actions["errors"])
        resp = ChatResponse(
            message=f"{resp.message}\n\nNote: Some actions could not be completed: {error_summary}",
            trades=resp.trades,
            watchlist_changes=resp.watchlist_changes,
        )

    # 6. Persist assistant response (with actions if any were attempted)
    has_actions = bool(actions["trades"] or actions["watchlist_changes"] or actions["errors"])
    _save_message("assistant", resp.message, actions if has_actions else None)

    # 7. Return StreamingResponse — all side effects complete before first yield
    return StreamingResponse(_stream_text(resp.message), media_type="text/event-stream")
