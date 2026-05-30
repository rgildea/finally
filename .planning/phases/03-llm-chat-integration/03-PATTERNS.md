# Phase 3: LLM Chat Integration - Pattern Map

**Mapped:** 2026-05-30
**Files analyzed:** 6 new/modified files
**Analogs found:** 6 / 6

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `backend/app/routers/chat.py` | router | request-response + streaming | `backend/app/routers/portfolio.py` | role-match |
| `backend/app/chat/llm.py` | service | request-response | `backend/app/routers/portfolio.py` (`execute_trade`) | partial-match |
| `backend/app/chat/context.py` | utility | CRUD + request-response | `backend/app/routers/portfolio.py` (`_compute_total_value`) | role-match |
| `backend/app/chat/mock.py` | utility | request-response | `backend/app/routers/portfolio.py` (env-gated logic) | partial-match |
| `backend/app/chat/__init__.py` | config | — | `backend/app/routers/__init__.py` | exact |
| `backend/tests/test_chat.py` | test | CRUD + request-response | `backend/tests/test_portfolio.py` | exact |
| `backend/app/main.py` | config | — | existing `backend/app/main.py` (router registration) | exact |

## Pattern Assignments

### `backend/app/routers/chat.py` (router, request-response + streaming)

**Analog:** `backend/app/routers/portfolio.py`

**Imports pattern** (lines 1-16 of portfolio.py):
```python
"""Portfolio router: positions, trade execution, history, and snapshot recorder."""
import asyncio
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator

from app.db.database import get_connection
from app.market.cache import price_cache

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["portfolio"])
```

**For chat.py, adapt imports to:**
```python
"""Chat router: POST /api/chat — LLM structured response, auto-execution, SSE streaming."""
import asyncio
import json
import logging
import os
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ValidationError
from litellm import acompletion

from app.db.database import get_connection
from app.market.cache import price_cache
from app.routers.portfolio import execute_trade

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["chat"])
```

**Pydantic request model pattern** (portfolio.py lines 23-48 — `TradeRequest` with `field_validator`):
```python
class TradeRequest(BaseModel):
    ticker: str
    side: str
    quantity: float

    @field_validator("ticker")
    @classmethod
    def normalize_ticker(cls, v: str) -> str:
        v = v.upper().strip()
        if not v or len(v) > 10:
            raise ValueError("Invalid ticker")
        return v
```

**For chat.py, use simpler request (no field_validator needed):**
```python
class ChatRequest(BaseModel):
    message: str

class TradeAction(BaseModel):
    ticker: str
    side: str
    quantity: float

class WatchlistAction(BaseModel):
    ticker: str
    action: str   # "add" | "remove"

class ChatResponse(BaseModel):
    message: str
    trades: list[TradeAction] = []
    watchlist_changes: list[WatchlistAction] = []
```

**DB write pattern** (portfolio.py lines 157-168 — `_write_snapshot`):
```python
def _write_snapshot(total_value: float) -> None:
    """Insert one portfolio_snapshots row."""
    now = datetime.now(timezone.utc).isoformat()
    con = get_connection()
    try:
        with con:
            con.execute(
                "INSERT INTO portfolio_snapshots (id, user_id, total_value, recorded_at) "
                "VALUES (?, 'default', ?, ?)",
                (str(uuid.uuid4()), total_value, now),
            )
    finally:
        con.close()
```

**For chat.py, adapt for `chat_messages` table (schema.py lines 51-60):**
```python
def _save_message(role: str, content: str, actions: dict | None = None) -> None:
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
```

**ValueError → HTTPException pattern** (portfolio.py lines 237-246):
```python
@router.post("/portfolio/trade")
async def trade(req: TradeRequest) -> dict:
    update = await price_cache.get(req.ticker)
    if update is None:
        raise HTTPException(status_code=503, detail="Price not available for ticker")
    try:
        result = execute_trade(req.ticker, req.side, req.quantity, update.price)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
```

**StreamingResponse pattern** — from `backend/app/routers/market.py` (lines 17-38), adapted for text/event-stream word-by-word:
```python
# market.py uses EventSourceResponse with ServerSentEvent objects.
# chat.py uses StreamingResponse with raw SSE text — simpler for one-shot string streaming.

async def _stream_text(text: str):
    """Yield message text word-by-word as SSE data events, ending with [DONE]."""
    for word in text.split(" "):
        yield f"data: {word} \n\n"
        await asyncio.sleep(0)
    yield "data: [DONE]\n\n"

@router.post("/chat")
async def chat(req: ChatRequest):
    # Steps: persist user msg → build context → call LLM → execute side effects
    # → persist assistant msg → return StreamingResponse
    ...
    return StreamingResponse(_stream_text(chat_response.message), media_type="text/event-stream")
```

**Ticker normalization pattern** (portfolio.py lines 29-32 and watchlist.py lines 65-67):
```python
# portfolio.py field_validator:
v = v.upper().strip()

# watchlist.py path param normalization:
ticker = ticker.upper().strip()
if not ticker or len(ticker) > 10:
    raise HTTPException(status_code=422, detail="Invalid ticker")
```
Apply `.upper().strip()` to every ticker in `trades` and `watchlist_changes` from the LLM response before calling `execute_trade` or the watchlist DB helpers.

---

### `backend/app/chat/llm.py` (service, request-response)

**Analog:** `backend/app/routers/portfolio.py` (`execute_trade` helper function pattern)

**Pattern:** Stateless module-level helper function that can be imported and unit-tested directly — same pattern as `execute_trade`. The LLM call is the "heavy" operation, analogous to a DB write.

**Cerebras skill pattern** (from `.claude/skills/cerebras/SKILL.md`):
```python
from litellm import completion
MODEL = "openrouter/openai/gpt-oss-120b"
EXTRA_BODY = {"provider": {"order": ["cerebras"]}}

# For structured output (use acompletion — async variant — to avoid blocking event loop):
response = await acompletion(
    model=MODEL,
    messages=messages,
    response_format=ChatResponse,
    reasoning_effort="low",
    extra_body=EXTRA_BODY,
)
result = ChatResponse.model_validate_json(response.choices[0].message.content)
```

**Mock mode gate** — no direct analog in codebase; use env var convention from `backend/app/main.py` (`load_dotenv()` already called at startup, so `os.getenv` is available):
```python
import os
LLM_MOCK = os.getenv("LLM_MOCK", "false").lower() == "true"

MOCK_RESPONSE = ChatResponse(
    message="This is a mock response. Your portfolio looks great!",
    trades=[],
    watchlist_changes=[],
)

async def get_llm_response(messages: list[dict]) -> ChatResponse:
    if LLM_MOCK:
        return MOCK_RESPONSE
    response = await acompletion(
        model=MODEL,
        messages=messages,
        response_format=ChatResponse,
        reasoning_effort="low",
        extra_body=EXTRA_BODY,
    )
    return ChatResponse.model_validate_json(response.choices[0].message.content)
```

**ValidationError handling** — mirror the `ValueError` catch in `portfolio.py trade()`:
```python
from pydantic import ValidationError
try:
    return ChatResponse.model_validate_json(response.choices[0].message.content)
except ValidationError:
    logger.exception("LLM returned malformed structured response")
    return ChatResponse(message="I encountered an error processing the response. Please try again.")
```

---

### `backend/app/chat/context.py` (utility, CRUD + request-response)

**Analog:** `backend/app/routers/portfolio.py` (`_compute_total_value` and `get_portfolio`)

**DB query pattern** (portfolio.py lines 129-153 — `_compute_total_value`):
```python
async def _compute_total_value() -> float:
    con = get_connection()
    try:
        profile = con.execute(
            "SELECT cash_balance FROM users_profile WHERE id='default'"
        ).fetchone()
        rows = con.execute(
            "SELECT ticker, quantity, avg_cost FROM positions WHERE user_id='default'"
        ).fetchall()
    finally:
        con.close()

    tickers = [r["ticker"] for r in rows]
    prices = await price_cache.get_many(tickers) if tickers else {}
    ...
```

**Chat history query pattern** (from RESEARCH.md Pattern 5 — matches existing DB query style):
```python
def load_recent_history(limit: int = 10) -> list[dict]:
    """Load recent chat_messages as LLM message dicts (role + content only)."""
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
```

**Watchlist query pattern** (watchlist.py lines 27-42):
```python
con = get_connection()
try:
    rows = con.execute(
        "SELECT ticker FROM watchlist WHERE user_id='default' ORDER BY added_at"
    ).fetchall()
    tickers = [row["ticker"] for row in rows]
finally:
    con.close()

prices = await price_cache.get_many(tickers)
```

---

### `backend/app/chat/mock.py` (utility, deterministic response)

**Analog:** No direct file analog in codebase; the pattern is the `LLM_MOCK` env gate in `llm.py`. Keep `mock.py` minimal — just a constant.

```python
"""Deterministic mock LLM response for LLM_MOCK=true."""
from app.chat.llm import ChatResponse  # or define inline in llm.py

MOCK_RESPONSE = ChatResponse(
    message="This is a mock response. Your portfolio looks great!",
    trades=[],
    watchlist_changes=[],
)
```

Note: Consider inlining the mock constant directly in `llm.py` to keep module count low (consistent with "short modules" guideline in CLAUDE.md).

---

### `backend/app/main.py` (modified — router registration)

**Analog:** `backend/app/main.py` lines 14-18 and 35-38 (existing router registrations)

**Pattern to copy** (main.py lines 14-38):
```python
from app.routers.health import router as health_router
from app.routers.market import router as market_router
from app.routers.portfolio import router as portfolio_router
from app.routers.watchlist import router as watchlist_router

# Add for Phase 3:
from app.routers.chat import router as chat_router

app = FastAPI(lifespan=lifespan)
app.include_router(health_router)
app.include_router(market_router)
app.include_router(portfolio_router)
app.include_router(watchlist_router)
app.include_router(chat_router)   # add this line
```

---

### `backend/tests/test_chat.py` (test, unit + integration)

**Analog:** `backend/tests/test_portfolio.py` — exact pattern match for fixture setup, monkeypatching, async test style, and direct helper function testing.

**Fixture pattern** (test_portfolio.py lines 26-30):
```python
@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    """Point DB_PATH at a fresh temp file for every test."""
    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "test.db")
    init_db()
```

**Mock patch pattern** (test_portfolio.py lines 165-176 and 241-248):
```python
# Patching async cache methods:
@pytest.fixture
def no_cache(monkeypatch):
    monkeypatch.setattr(price_cache, "get_many", AsyncMock(return_value={}))

# Patching with patch.object:
with patch.object(price_cache, "get", AsyncMock(return_value=None)):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(...)
```

**Direct helper function test pattern** (test_portfolio.py lines 69-76):
```python
def test_buy_new_position():
    """Buying 10 shares @ 100 of a new ticker creates position, debits cash, logs trade."""
    execute_trade("AAPL", "buy", 10, 100.0)
    pos = _position("AAPL")
    assert pos is not None
    ...
```

**For test_chat.py, apply to `_get_llm_response` and `_save_message`:**
```python
import app.db.database as db_module
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from app.db.database import get_connection, init_db
from app.main import app
from app.routers.chat import ChatResponse, _get_llm_response

@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "test.db")
    init_db()

async def test_mock_mode(monkeypatch):
    monkeypatch.setenv("LLM_MOCK", "true")
    # reload LLM_MOCK constant — or pass via function arg if designed for it
    result = await _get_llm_response([{"role": "user", "content": "hi"}])
    assert isinstance(result, ChatResponse)
    assert isinstance(result.message, str)

async def test_chat_streams_response(monkeypatch):
    monkeypatch.setenv("LLM_MOCK", "true")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post("/api/chat", json={"message": "hello"})
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]
```

**Async test config** — `pyproject.toml` already has `asyncio_mode = "auto"` (confirmed in RESEARCH.md). No additional setup needed in test_chat.py.

---

## Shared Patterns

### DB Connection Pattern
**Source:** `backend/app/db/database.py` lines 11-19, used in every router
**Apply to:** `chat.py`, `context.py`
```python
con = get_connection()
try:
    with con:   # for writes (auto-commit/rollback)
        con.execute("INSERT ...", (...))
finally:
    con.close()

# For reads (no 'with con' context manager needed):
con = get_connection()
try:
    rows = con.execute("SELECT ...").fetchall()
finally:
    con.close()
```

### UUID + ISO timestamp pattern
**Source:** `backend/app/routers/portfolio.py` lines 58-59
**Apply to:** `chat.py` (`_save_message`)
```python
import uuid
from datetime import datetime, timezone
now = datetime.now(timezone.utc).isoformat()
str(uuid.uuid4())
```

### Error logging pattern
**Source:** `backend/app/routers/portfolio.py` lines 13, 183-184
**Apply to:** `chat.py`, `llm.py`
```python
import logging
logger = logging.getLogger(__name__)
# Non-fatal errors:
logger.exception("Description of failure — non-fatal")
```

### Ticker normalization
**Source:** `backend/app/routers/portfolio.py` lines 29-32 and `watchlist.py` lines 65-66
**Apply to:** `chat.py` (before passing LLM-returned tickers to `execute_trade` or watchlist DB helpers)
```python
ticker = trade_action.ticker.upper().strip()
```

### Environment variable reading
**Source:** `backend/app/main.py` line 9 (`load_dotenv()` called at startup)
**Apply to:** `backend/app/chat/llm.py`
```python
import os
LLM_MOCK = os.getenv("LLM_MOCK", "false").lower() == "true"
```
`os.getenv` is safe at module import time because `load_dotenv()` runs in `main.py` before any router is imported.

### Watchlist DB write helpers
**Source:** `backend/app/routers/watchlist.py` lines 45-58 (add) and lines 62-78 (remove)
**Apply to:** `chat.py` auto-execution of `watchlist_changes`

Add ticker:
```python
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
```

Remove ticker:
```python
con = get_connection()
try:
    with con:
        con.execute(
            "DELETE FROM watchlist WHERE user_id='default' AND ticker=?", (ticker,)
        )
finally:
    con.close()
await price_cache.remove(ticker)
```

### StreamingResponse
**Source:** `backend/app/routers/market.py` lines 17-38 (EventSourceResponse / SSE pattern)
**Apply to:** `chat.py`

The market router uses `EventSourceResponse` + `ServerSentEvent` objects. The chat router uses the simpler `StreamingResponse` with raw SSE-formatted strings — appropriate because chat streams a single pre-obtained string, not a perpetual event loop.

---

## No Analog Found

All files have analogs in the codebase. The only new external dependency is `litellm` (not yet installed).

| Gap | Resolution |
|-----|------------|
| `litellm` not in `pyproject.toml` | `cd backend && uv add litellm` before implementing |

---

## Metadata

**Analog search scope:** `backend/app/routers/`, `backend/tests/`, `backend/app/db/`, `backend/app/main.py`, `.claude/skills/cerebras/SKILL.md`
**Files scanned:** 10
**Pattern extraction date:** 2026-05-30
