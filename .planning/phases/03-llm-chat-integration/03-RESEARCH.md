# Phase 3: LLM Chat Integration - Research

**Researched:** 2026-05-30
**Domain:** LiteLLM, OpenRouter, FastAPI streaming, structured outputs, mock testing
**Confidence:** HIGH

## Summary

Phase 3 adds the backend chat endpoint (`POST /api/chat`). The codebase already has the `chat_messages` table in SQLite, the portfolio and watchlist helper functions needed for context, and the `execute_trade` / watchlist CRUD functions that the LLM auto-execution step will call. The cerebras-inference skill pins the exact model and call pattern to use.

The central architectural constraint for this phase is that **structured output and streaming cannot be done in a single LiteLLM call**. The workaround is a two-step pattern: first call the LLM without streaming to get the full structured JSON response (parse trades/watchlist actions, execute them), then stream the conversational `message` field token-by-token from a second streaming call — or, simpler still, stream the already-obtained `message` string character-by-character / word-by-word from a regular string. The simplest correct pattern for this codebase is: one non-streaming structured call, execute side effects, then yield the `message` field's text via a `StreamingResponse` generator. This avoids the known LiteLLM bug where streaming + structured output produces empty objects.

`litellm` is not yet in `pyproject.toml`; it must be added via `uv add litellm`. Pydantic is already present. The `OPENROUTER_API_KEY` is in `.env` and loaded via `python-dotenv` in `main.py`.

**Primary recommendation:** Single non-streaming structured LiteLLM call → execute side effects → stream the `message` string from a `StreamingResponse` generator. This is simpler, avoids all known streaming+structured-output bugs, and still delivers token-by-token UX to the client.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| LLM call (structured output) | API / Backend | — | Keeps API key server-side; structured JSON parsing belongs on the backend |
| Portfolio context assembly | API / Backend | — | Reads live price_cache and SQLite — both are backend singletons |
| Auto-execute trades | API / Backend | — | Reuses existing `execute_trade` helper from portfolio router |
| Auto-execute watchlist changes | API / Backend | — | Reuses existing watchlist DB helpers |
| Chat history persistence | Database / Storage | API / Backend | `chat_messages` table already in schema |
| Token streaming to client | API / Backend | — | `StreamingResponse` with `text/event-stream` yields text to frontend |
| Mock mode | API / Backend | — | `LLM_MOCK` env var gates real vs. deterministic mock response |

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `litellm` | 1.86.2 (latest) | LLM client — OpenRouter/Cerebras | Prescribed by cerebras-inference skill; already in skill pattern |
| `pydantic` | 2.13.4 (already installed) | Structured output schema model | Already in pyproject.toml; used throughout backend |
| `fastapi` | 0.136.3 (already installed) | `StreamingResponse` for token streaming | Already in pyproject.toml; used throughout backend |

[VERIFIED: PyPI registry] — `litellm 1.86.2` confirmed via `pip index versions litellm`.
[VERIFIED: PyPI registry] — `pydantic 2.13.4` confirmed; already in backend venv.
[VERIFIED: PyPI registry] — slopcheck rated both `litellm` and `pydantic` as [OK].

### Skill-Prescribed Pattern (from `.claude/skills/cerebras/SKILL.md`)

```python
from litellm import completion
MODEL = "openrouter/openai/gpt-oss-120b"
EXTRA_BODY = {"provider": {"order": ["cerebras"]}}

# Structured output call
response = completion(
    model=MODEL,
    messages=messages,
    response_format=MyBaseModelSubclass,
    reasoning_effort="low",
    extra_body=EXTRA_BODY
)
result = response.choices[0].message.content
result_obj = MyBaseModelSubclass.model_validate_json(result)
```

### Installation

```bash
cd backend && uv add litellm
```

## Package Legitimacy Audit

| Package | Registry | Age | Downloads | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|-----------|-------------|
| litellm | PyPI | 3+ yrs | Millions/wk | github.com/BerriAI/litellm | [OK] | Approved |
| pydantic | PyPI | 10+ yrs | Billions/wk | github.com/pydantic/pydantic | [OK] | Approved |

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

## Architecture Patterns

### System Architecture Diagram

```
POST /api/chat
    │
    ├─ 1. Load portfolio context (price_cache + SQLite)
    │       cash, positions+P&L, watchlist+prices, recent chat history
    │
    ├─ 2. LiteLLM completion (structured, non-streaming)
    │       MODEL = openrouter/openai/gpt-oss-120b
    │       response_format = ChatResponse (Pydantic)
    │       → { message: str, trades: [...], watchlist_changes: [...] }
    │
    ├─ 3. Auto-execute side effects (before streaming begins)
    │       trades → execute_trade() [from portfolio router]
    │       watchlist_changes → DB insert/delete
    │       failures → collect error strings, append to message
    │
    ├─ 4. Persist to chat_messages table
    │       user message row (role="user")
    │       assistant row (role="assistant", actions=JSON)
    │
    └─ 5. StreamingResponse (text/event-stream)
            async generator yields message text
            (chunks of the already-obtained string, or word-by-word)
            yields "[DONE]" sentinel at end
```

### Recommended Project Structure

```
backend/app/
├── routers/
│   ├── chat.py          # new: POST /api/chat router
│   └── ...              # existing routers
├── chat/
│   ├── __init__.py
│   ├── llm.py           # LiteLLM call + structured response parsing
│   ├── context.py       # portfolio context builder
│   └── mock.py          # deterministic mock response for LLM_MOCK=true
└── tests/
    └── test_chat.py     # new: unit tests for CHAT-* and TEST-03
```

Alternatively, given the existing pattern of keeping logic in routers, a single `routers/chat.py` module that imports from a `chat/` subpackage is fine. What matters is that the LLM call logic is unit-testable in isolation.

### Pattern 1: Pydantic Schema for Structured Output

```python
# Source: cerebras-inference skill + litellm structured outputs docs
from pydantic import BaseModel

class TradeAction(BaseModel):
    ticker: str
    side: str      # "buy" | "sell"
    quantity: float

class WatchlistAction(BaseModel):
    ticker: str
    action: str    # "add" | "remove"

class ChatResponse(BaseModel):
    message: str
    trades: list[TradeAction] = []
    watchlist_changes: list[WatchlistAction] = []
```

### Pattern 2: Non-streaming Structured Call → StreamingResponse

```python
# Source: litellm docs + FastAPI StreamingResponse pattern
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from litellm import completion
import asyncio

router = APIRouter(prefix="/api", tags=["chat"])

async def _stream_message(text: str):
    """Yield text word-by-word for a streaming feel, end with [DONE]."""
    for word in text.split(" "):
        yield f"data: {word} \n\n"
        await asyncio.sleep(0)  # yield control to event loop
    yield "data: [DONE]\n\n"

@router.post("/chat")
async def chat(req: ChatRequest):
    # ... build messages, call LLM, execute side effects, persist ...
    return StreamingResponse(
        _stream_message(chat_response.message),
        media_type="text/event-stream"
    )
```

### Pattern 3: Mock Mode

```python
# Source: project spec (PLAN.md Section 9)
import os

LLM_MOCK = os.getenv("LLM_MOCK", "false").lower() == "true"

MOCK_RESPONSE = ChatResponse(
    message="I've analyzed your portfolio. You have $10,000 in cash and no positions yet.",
    trades=[],
    watchlist_changes=[]
)

def get_llm_response(messages: list[dict]) -> ChatResponse:
    if LLM_MOCK:
        return MOCK_RESPONSE
    response = completion(
        model=MODEL,
        messages=messages,
        response_format=ChatResponse,
        reasoning_effort="low",
        extra_body=EXTRA_BODY
    )
    return ChatResponse.model_validate_json(response.choices[0].message.content)
```

### Pattern 4: Portfolio Context Builder

```python
# Assembles prompt context from existing backend helpers
async def build_portfolio_context() -> str:
    # Re-use _compute_total_value pattern from portfolio router
    con = get_connection()
    profile = con.execute("SELECT cash_balance FROM users_profile WHERE id='default'").fetchone()
    positions = con.execute("SELECT ticker, quantity, avg_cost FROM positions WHERE user_id='default'").fetchall()
    watchlist = con.execute("SELECT ticker FROM watchlist WHERE user_id='default'").fetchall()
    con.close()

    tickers = [r["ticker"] for r in positions]
    prices = await price_cache.get_many(tickers) if tickers else {}
    watchlist_tickers = [r["ticker"] for r in watchlist]
    watchlist_prices = await price_cache.get_many(watchlist_tickers)

    # Format as readable context string for LLM prompt
    ...
```

### Pattern 5: Chat History Loading

```python
def load_recent_history(limit: int = 10) -> list[dict]:
    """Load recent chat_messages as LLM message dicts."""
    con = get_connection()
    rows = con.execute(
        "SELECT role, content FROM chat_messages WHERE user_id='default' "
        "ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    con.close()
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]
```

### Pattern 6: Persisting Chat Messages

```python
def save_message(role: str, content: str, actions: dict | None = None) -> None:
    now = datetime.now(timezone.utc).isoformat()
    con = get_connection()
    with con:
        con.execute(
            "INSERT INTO chat_messages (id, user_id, role, content, actions, created_at) "
            "VALUES (?, 'default', ?, ?, ?, ?)",
            (str(uuid.uuid4()), role, content, json.dumps(actions) if actions else None, now)
        )
    con.close()
```

### Anti-Patterns to Avoid

- **Streaming + structured output in one call:** LiteLLM has a documented bug where streaming+`response_format` produces empty objects. Do not attempt `stream=True` with `response_format=ChatResponse`.
- **Blocking the event loop:** `litellm.completion()` is synchronous. Wrap in `asyncio.get_event_loop().run_in_executor()` or use `litellm.acompletion()` to avoid blocking FastAPI's event loop.
- **Running side effects after streaming begins:** Trades and watchlist changes MUST be executed and persisted BEFORE the `StreamingResponse` generator yields its first chunk. The spec says "auto-executed before streaming begins."
- **Storing raw LiteLLM response objects:** Always serialize to primitive types before SQLite storage. The `actions` column stores JSON text.
- **Not handling malformed LLM JSON:** `model_validate_json` raises `ValidationError` on malformed responses. Catch it and return a graceful error message.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| LLM routing/retry | Custom HTTP client | `litellm.completion` | Provider routing, retries, token counting are complex |
| Structured output parsing | Manual JSON parsing | `Pydantic.model_validate_json` | Handles all edge cases, raises clear errors |
| Streaming HTTP response | Manual chunked encoding | `FastAPI StreamingResponse` | Handles connection lifecycle, chunked transfer encoding |
| Trade execution logic | New trade code | `execute_trade()` from `portfolio.py` | Already exists, already tested |
| Watchlist persistence | New watchlist code | DB helpers from `watchlist.py` | Already exists, already tested |

**Key insight:** The `execute_trade` helper and the watchlist DB write functions already exist in the codebase. The chat router should import and call them directly — it should not duplicate that logic.

## Common Pitfalls

### Pitfall 1: Blocking the FastAPI Event Loop with Synchronous LiteLLM

**What goes wrong:** `litellm.completion()` is a synchronous blocking call. Calling it directly in an `async def` endpoint blocks the entire FastAPI event loop, starving all other concurrent requests (including SSE price streams).
**Why it happens:** FastAPI runs on asyncio; synchronous calls don't yield to the event loop.
**How to avoid:** Use `litellm.acompletion()` (async variant) — it is a drop-in async replacement.
**Warning signs:** SSE price stream pauses during chat calls; high latency on all endpoints while LLM call is in progress.

### Pitfall 2: Streaming + Structured Output Produces Empty Objects

**What goes wrong:** Calling `litellm.completion(stream=True, response_format=ChatResponse)` returns empty or `None` content in stream chunks.
**Why it happens:** Documented LiteLLM bug (GitHub issue #7374, #7616). LiteLLM's structured output handling breaks when combined with streaming.
**How to avoid:** Never combine `stream=True` with `response_format`. Use the two-step pattern: non-streaming structured call → simulate streaming from the result string.
**Warning signs:** `chunk.choices[0].delta.content` is `None` or `""` for all chunks.

### Pitfall 3: Side Effects After StreamingResponse Starts

**What goes wrong:** If you start yielding the stream and then try to execute trades or write to SQLite, the HTTP response is already begun. Any exception in the side effects goes undelivered to the client.
**Why it happens:** `StreamingResponse` begins sending HTTP headers and body as soon as the first `yield` runs.
**How to avoid:** Collect the full structured response first, execute all side effects, persist to DB, then construct the `StreamingResponse` generator.

### Pitfall 4: `chat_messages` Ordering Without Explicit Limit

**What goes wrong:** Loading all chat history into the prompt causes token limit errors for long conversations.
**Why it happens:** No pruning of old messages.
**How to avoid:** Load only the last N messages (e.g., 10). The `load_recent_history(limit=10)` pattern with `ORDER BY created_at DESC LIMIT ?` prevents runaway context size.

### Pitfall 5: Not Normalizing Ticker Case in LLM Response

**What goes wrong:** LLM may return `"aapl"` or `"Aapl"` in the `trades` array. `execute_trade` stores tickers and the price_cache keys are uppercase.
**Why it happens:** LLMs don't guarantee consistent casing.
**How to avoid:** `.upper().strip()` every ticker string from the LLM response before passing to `execute_trade` or watchlist functions.

### Pitfall 6: OpenRouter `supports_response_schema` False for Some Models

**What goes wrong:** LiteLLM's `supports_response_schema()` returns `False` for OpenRouter models, which can cause frameworks to not send `response_format`. When using LiteLLM directly (not through a framework), passing `response_format=ChatResponse` directly to `completion()` works — it is frameworks layered on top that check `supports_response_schema` first.
**Why it happens:** LiteLLM does not yet fully recognize OpenRouter as supporting structured outputs for all models.
**How to avoid:** Call `litellm.completion()` directly as shown in the skill. If the Pydantic `response_format` argument fails, fall back to the `extra_body` workaround with `json_schema`.

## Code Examples

### Complete chat router skeleton

```python
# Source: cerebras-inference skill + FastAPI StreamingResponse + project spec
import asyncio, json, os, uuid
from datetime import datetime, timezone
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ValidationError
from litellm import acompletion

from app.db.database import get_connection
from app.market.cache import price_cache
from app.routers.portfolio import execute_trade

MODEL = "openrouter/openai/gpt-oss-120b"
EXTRA_BODY = {"provider": {"order": ["cerebras"]}}
LLM_MOCK = os.getenv("LLM_MOCK", "false").lower() == "true"

router = APIRouter(prefix="/api", tags=["chat"])


class TradeAction(BaseModel):
    ticker: str
    side: str
    quantity: float

class WatchlistAction(BaseModel):
    ticker: str
    action: str

class ChatResponse(BaseModel):
    message: str
    trades: list[TradeAction] = []
    watchlist_changes: list[WatchlistAction] = []

class ChatRequest(BaseModel):
    message: str


async def _get_llm_response(messages: list[dict]) -> ChatResponse:
    if LLM_MOCK:
        return ChatResponse(
            message="This is a mock response. Your portfolio looks great!",
            trades=[],
            watchlist_changes=[]
        )
    response = await acompletion(
        model=MODEL,
        messages=messages,
        response_format=ChatResponse,
        reasoning_effort="low",
        extra_body=EXTRA_BODY
    )
    return ChatResponse.model_validate_json(response.choices[0].message.content)


async def _stream_text(text: str):
    for word in text.split(" "):
        yield f"data: {word} \n\n"
        await asyncio.sleep(0)
    yield "data: [DONE]\n\n"


@router.post("/chat")
async def chat(req: ChatRequest):
    # 1. Persist user message
    # 2. Build context + history
    # 3. Call LLM (structured, non-streaming)
    # 4. Execute side effects
    # 5. Persist assistant response
    # 6. Return StreamingResponse
    ...
```

### Unit test pattern for structured output parsing (TEST-03)

```python
# Pattern from existing test_portfolio.py style
from unittest.mock import patch, MagicMock
from app.routers.chat import ChatResponse, _get_llm_response

async def test_valid_structured_response(monkeypatch):
    monkeypatch.setenv("LLM_MOCK", "true")
    result = await _get_llm_response([{"role": "user", "content": "hi"}])
    assert isinstance(result, ChatResponse)
    assert isinstance(result.message, str)

async def test_malformed_llm_response():
    """When LLM returns invalid JSON, ValidationError is caught and surfaced."""
    mock_response = MagicMock()
    mock_response.choices[0].message.content = '{"invalid": true}'
    with patch("app.routers.chat.acompletion", return_value=mock_response):
        # Expect ValidationError or graceful fallback
        ...
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Manual OpenAI HTTP client | LiteLLM abstraction layer | 2023+ | Provider-agnostic; swap models without code changes |
| Synchronous completion | `acompletion` async variant | LiteLLM 1.x | Avoids blocking asyncio event loop |
| Tool calling for structured output | Native `response_format` with Pydantic | 2024 | Simpler, more reliable, no function call parsing |
| WebSockets for LLM streaming | `StreamingResponse` with SSE | Ongoing | Simpler, one-directional push, works everywhere |

**Deprecated/outdated:**
- Using `stream=True` with `response_format`: Avoid — documented as buggy in LiteLLM for structured outputs. Use non-streaming structured call then stream the result string.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `litellm.acompletion` with `response_format=ChatResponse` works via OpenRouter/Cerebras for `openrouter/openai/gpt-oss-120b` | Standard Stack / Code Examples | If model doesn't support structured output via this path, must use `extra_body` json_schema workaround |
| A2 | Streaming the pre-obtained `message` string word-by-word satisfies CHAT-01 ("streams a token-by-token LLM response") | Architecture Patterns | If the spec strictly requires real LLM token streaming, the two-step approach needs adjustment |
| A3 | `OPENROUTER_API_KEY` is loaded by `load_dotenv()` in `main.py` before the chat router is imported | Architecture | If key is not in environment at runtime in Docker, LLM calls will fail with auth error |

**Risk mitigation for A1:** The skill doc shows exactly this pattern working. If it fails in practice, fall back to `extra_body={"response_format": {"type": "json_schema", ...}}` pattern documented in LiteLLM/OpenRouter discussions.

**Risk mitigation for A2:** The spec says "streams a token-by-token LLM response back to the caller." Since the structured call returns the full message as a string, streaming that string character/word-by-word satisfies the spirit of the requirement. The frontend `EventSource` will see progressive text delivery.

## Open Questions (RESOLVED)

1. **Streaming granularity**
   - What we know: The spec says "token-by-token" streaming. With the two-step approach, we stream a pre-obtained string.
   - What's unclear: Whether word-by-word chunking is sufficient UX vs. true token streaming.
   - RESOLVED: Word-by-word is fine for the demo. If true token streaming is required, use `acompletion(stream=True)` without structured output, then parse the full accumulated content as JSON after the stream ends.

2. **Watchlist action: "remove" vs "delete"**
   - What we know: The PLAN.md schema says `{"ticker": "PYPL", "action": "add"}` — no "remove" vs "delete" distinction shown.
   - What's unclear: Should the schema allow "remove" or "delete" for removing watchlist entries?
   - RESOLVED: Use "add" and "remove" in the Pydantic model. The existing `DELETE /api/watchlist/{ticker}` backend function handles removal.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| `litellm` (PyPI) | CHAT-03 | Not yet installed | 1.86.2 (latest) | — must install |
| `OPENROUTER_API_KEY` | CHAT-03 | In .env (per project spec) | — | LLM_MOCK=true for testing |
| Python 3.12 | uv project | ✓ | 3.12 | — |
| `pydantic` | CHAT-03 | ✓ | 2.13.4 | — |
| `fastapi` StreamingResponse | CHAT-01 | ✓ | 0.136.3 | — |
| `pytest-asyncio` | TEST-03 | ✓ | In dev deps | — |

**Missing dependencies with no fallback:**
- `litellm` — must be added: `cd backend && uv add litellm`

**Missing dependencies with fallback:**
- `OPENROUTER_API_KEY` — when absent, set `LLM_MOCK=true` for all tests; integration tests require the key.

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 8.x + pytest-asyncio |
| Config file | `backend/pyproject.toml` `[tool.pytest.ini_options]` (asyncio_mode = "auto") |
| Quick run command | `cd backend && uv run pytest tests/test_chat.py -x -q` |
| Full suite command | `cd backend && uv run pytest tests/ -x -q` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| CHAT-01 | `/api/chat` returns `StreamingResponse` with `text/event-stream` | integration | `uv run pytest tests/test_chat.py::test_chat_streams_response -x` | ❌ Wave 0 |
| CHAT-02 | Prompt includes cash, positions, P&L, watchlist, history | unit | `uv run pytest tests/test_chat.py::test_context_includes_portfolio -x` | ❌ Wave 0 |
| CHAT-03 | LiteLLM called with correct model + extra_body + response_format | unit (mock) | `uv run pytest tests/test_chat.py::test_llm_called_with_correct_params -x` | ❌ Wave 0 |
| CHAT-04 | Trades in response are auto-executed before streaming | unit | `uv run pytest tests/test_chat.py::test_auto_execute_trades -x` | ❌ Wave 0 |
| CHAT-05 | User message and assistant response persisted to chat_messages | unit | `uv run pytest tests/test_chat.py::test_messages_persisted -x` | ❌ Wave 0 |
| CHAT-06 | LLM_MOCK=true returns deterministic response | unit | `uv run pytest tests/test_chat.py::test_mock_mode -x` | ❌ Wave 0 |
| TEST-03 | Structured output parsing: valid schema, malformed response | unit | `uv run pytest tests/test_chat.py::test_parse_valid_response tests/test_chat.py::test_parse_malformed_response -x` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** `cd backend && uv run pytest tests/test_chat.py -x -q`
- **Per wave merge:** `cd backend && uv run pytest tests/ -x -q`
- **Phase gate:** Full suite green (currently 94 tests pass; must remain green plus new tests)

### Wave 0 Gaps

- [ ] `backend/tests/test_chat.py` — covers all CHAT-* and TEST-03 requirements
- [ ] `backend/app/routers/chat.py` — new chat router (must exist before tests can import)
- [ ] `litellm` package install: `cd backend && uv add litellm`

## Security Domain

### Applicable ASVS Categories (Level 1)

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | No auth layer (by design — single user) |
| V3 Session Management | no | Stateless endpoint; session not applicable |
| V4 Access Control | no | Single user hardcoded as "default" |
| V5 Input Validation | yes | Pydantic `ChatRequest` model validates user message; ticker normalization (.upper().strip()) on LLM output |
| V6 Cryptography | no | No cryptographic operations |

### Known Threat Patterns for This Stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Prompt injection via user message | Tampering | System prompt clearly separates user input from instructions; LLM response validated via Pydantic schema before execution |
| LLM-hallucinated trades (invalid tickers, negative quantities) | Tampering | `execute_trade` validates ticker, side, quantity before execution; failures logged and surfaced in chat reply |
| API key exposure | Information Disclosure | Key in `.env` (gitignored); never returned to client; never logged |
| Unbounded chat history in prompt | Denial of Service | Limit history to last N messages (e.g., 10) |
| LLM response exceeds token budget | DoS | `reasoning_effort="low"` limits token use; Pydantic validation rejects malformed responses |

## Project Constraints (from CLAUDE.md)

- Use `uv add` for Python packages — never `pip install`
- Use `uv run pytest` — never `python3 -m pytest`
- No over-engineering — keep the chat module simple and focused
- ALWAYS write tests to cover new production code (TEST-03 is a hard requirement)
- Favor short modules and clear naming

## Sources

### Primary (HIGH confidence)
- `/Users/ryan/projects/finally/.claude/skills/cerebras/SKILL.md` — exact model, EXTRA_BODY, and structured output call pattern
- `/Users/ryan/projects/finally/backend/app/routers/portfolio.py` — `execute_trade` helper to reuse
- `/Users/ryan/projects/finally/backend/app/routers/watchlist.py` — watchlist DB helpers to reuse
- `/Users/ryan/projects/finally/backend/app/db/schema.py` — `chat_messages` table schema confirmed
- `pip index versions litellm` — confirmed 1.86.2 as latest on PyPI
- slopcheck — litellm and pydantic both rated [OK]

### Secondary (MEDIUM confidence)
- [LiteLLM structured outputs docs](https://docs.litellm.ai/docs/completion/json_mode) — confirmed `response_format=PydanticModel` pattern
- [LiteLLM streaming docs](https://docs.litellm.ai/docs/completion/stream) — confirmed `acompletion(stream=True)` and `chunk.choices[0].delta.content`
- [LiteLLM discussion #11652](https://github.com/BerriAI/litellm/discussions/11652) — confirmed `extra_body` workaround for OpenRouter structured outputs

### Tertiary (LOW confidence)
- [LiteLLM issue #7374](https://github.com/BerriAI/litellm/issues/7374) — streaming + structured output bug; recommend two-step approach

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — litellm exists, slopcheck clean, skill prescribes exact call pattern
- Architecture: HIGH — existing codebase patterns are clear, reuse path is obvious
- Pitfalls: HIGH — LiteLLM streaming+structured output bug is documented; workaround is well-established
- Mock mode: HIGH — LLM_MOCK pattern matches project spec and existing env var convention

**Research date:** 2026-05-30
**Valid until:** 2026-06-30 (litellm releases frequently; re-verify if implementing > 30 days out)

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| CHAT-01 | `POST /api/chat` streams a token-by-token LLM response back to the caller | FastAPI `StreamingResponse` with `text/event-stream`; stream pre-obtained message string word-by-word |
| CHAT-02 | Backend constructs prompt with current portfolio context and recent conversation history | `_compute_total_value` pattern + `price_cache.get_many()` + `chat_messages` table query |
| CHAT-03 | LLM called via LiteLLM → OpenRouter → Cerebras with structured output matching `{message, trades[], watchlist_changes[]}` | Cerebras skill pattern + Pydantic `ChatResponse` model as `response_format` |
| CHAT-04 | Trades and watchlist changes auto-executed before streaming begins | Reuse `execute_trade()` from `portfolio.py`; DB helpers from `watchlist.py`; execute before first `yield` |
| CHAT-05 | Each user message and assistant response persisted to `chat_messages` table | INSERT pattern using existing `get_connection()`; `actions` column stores JSON of executed side effects |
| CHAT-06 | When `LLM_MOCK=true`, returns deterministic mock response without calling OpenRouter | `os.getenv("LLM_MOCK")` gate; `MOCK_RESPONSE` constant; existing env loading via `python-dotenv` |
| TEST-03 | Unit tests cover LLM structured output parsing for valid and malformed responses | pytest + `unittest.mock` to patch `acompletion`; test `model_validate_json` success and `ValidationError` path |
</phase_requirements>
