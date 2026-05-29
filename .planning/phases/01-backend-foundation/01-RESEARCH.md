# Phase 1: Backend Foundation - Research

**Researched:** 2026-05-29
**Domain:** FastAPI application bootstrap, SQLite lazy init, uv project structure
**Confidence:** HIGH

---

## Summary

Phase 1 wires together the already-complete market data layer with a FastAPI application that starts cleanly, initialises SQLite, seeds default data, and exposes a single health endpoint. All external dependencies (FastAPI 0.136.3, Pydantic 2.13.4, uvicorn 0.48.0, python-dotenv) are already installed and locked in `backend/uv.lock`. No new packages are required.

The work is almost entirely structural: create `backend/app/main.py` with a lifespan context manager that starts the market data polling loop and initialises the database, create `backend/app/db/` with schema SQL and a seed function, register a single `/api/health` router, and write pytest tests that cover both the happy path and the idempotent re-start path.

FastAPI 0.136.3 ships native SSE support (`fastapi.sse.EventSourceResponse`) — confirmed present in the installed venv. No third-party SSE library is needed, not for this phase and not for Phase 2.

**Primary recommendation:** Use the FastAPI `lifespan` context manager (not deprecated `startup`/`shutdown` event handlers) to orchestrate startup. Use `sqlite3` stdlib (no ORM needed) with `CREATE TABLE IF NOT EXISTS` + `INSERT OR IGNORE` for fully idempotent initialisation. Keep the database module thin — raw SQL strings, no migration framework.

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| APP-01 | FastAPI app starts with a lifespan that launches the market data polling loop and initializes the SQLite database on first run | FastAPI lifespan pattern confirmed; `create_market_data_source()` factory and `polling_loop()` already exist in `app/market/` |
| APP-02 | FastAPI serves the Next.js static export from `/` (all non-API paths return `index.html`) | `StaticFiles` + catch-all route in FastAPI; static files won't exist until Phase 6, so this can be a stub or conditional mount |
| APP-03 | `GET /api/health` returns `{"status": "ok"}` for container health checks | Trivial FastAPI router; confirmed pattern |
| DB-01 | SQLite database is created and seeded automatically on first startup — no manual migration step | `CREATE TABLE IF NOT EXISTS` + `INSERT OR IGNORE` is idempotent; confirmed working with sqlite3 stdlib |
| DB-02 | Schema includes: `users_profile`, `watchlist`, `positions`, `trades`, `portfolio_snapshots`, `chat_messages` | Schema fully specified in PLAN.md; raw SQL, stdlib sqlite3 |
| DB-03 | Default seed data: one user profile (`id="default"`, `cash_balance=10000.0`) and 10 default watchlist tickers | `INSERT OR IGNORE` makes this safely re-runnable; tickers enumerated in PLAN.md |
</phase_requirements>

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Application startup / lifespan | API / Backend | — | FastAPI lifespan owns startup orchestration |
| Market data polling loop | API / Backend | — | Asyncio background task launched at startup |
| SQLite init + seed | API / Backend | Database / Storage | Backend owns init logic; SQLite is the storage |
| Health endpoint | API / Backend | — | Simple REST route, no DB needed |
| Static file serving (stub) | API / Backend | CDN / Static | FastAPI `StaticFiles`; frontend build not yet present |
| Environment variable loading | API / Backend | — | `python-dotenv` loads `.env` at process start |

---

## Standard Stack

### Core (all already installed, no new installs needed)

| Library | Installed Version | Purpose | Status |
|---------|-------------------|---------|--------|
| fastapi | 0.136.3 | Web framework, routing, dependency injection | [VERIFIED: installed in venv] |
| uvicorn[standard] | 0.48.0 | ASGI server | [VERIFIED: installed in venv] |
| pydantic | 2.13.4 | Data models and validation | [VERIFIED: installed in venv] |
| python-dotenv | (in uv.lock) | Load `.env` at startup | [VERIFIED: installed in venv] |
| sqlite3 | stdlib (3.50.4) | Database — no ORM needed | [VERIFIED: stdlib, WAL mode confirmed] |

### No new packages required for Phase 1

All dependencies for this phase are already present in `backend/pyproject.toml` and `uv.lock`. The only install command needed is the baseline:

```bash
cd backend && uv sync
```

### Key version note: FastAPI native SSE

FastAPI 0.136.3 ships `fastapi.sse.EventSourceResponse` and `fastapi.sse.ServerSentEvent` natively — confirmed importable in the installed venv. This matters for Phase 2 (SSE endpoint) but the Phase 1 planner should know **not** to add `sse-starlette` or any other SSE package**. [VERIFIED: import tested against installed venv]

---

## Package Legitimacy Audit

> No new packages are installed in this phase. All packages were already verified and locked
> when the market data layer was built. No audit action needed.

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

---

## Architecture Patterns

### System Architecture Diagram

```
.env (loaded by python-dotenv at startup)
         |
         v
backend/app/main.py  <-- FastAPI app, lifespan context manager
         |
         +-- lifespan startup:
         |     1. load_dotenv()
         |     2. db.init()          -- CREATE TABLE IF NOT EXISTS + INSERT OR IGNORE
         |     3. source = create_market_data_source()
         |     4. await source.start()
         |     5. asyncio.create_task(polling_loop(source, get_tickers, 0.5))
         |
         +-- routers/
         |     health.py  -->  GET /api/health  {"status": "ok"}
         |
         +-- db/
               schema.py   -- CREATE TABLE IF NOT EXISTS SQL strings
               seed.py     -- INSERT OR IGNORE default user + 10 tickers
               database.py -- get_db() connection helper (returns sqlite3.Connection)
```

### Recommended Project Structure

```
backend/
├── app/
│   ├── __init__.py
│   ├── main.py            # FastAPI app + lifespan
│   ├── db/
│   │   ├── __init__.py
│   │   ├── database.py    # Connection helper, DB_PATH constant
│   │   ├── schema.py      # CREATE TABLE IF NOT EXISTS SQL
│   │   └── seed.py        # INSERT OR IGNORE default data
│   ├── routers/
│   │   ├── __init__.py
│   │   └── health.py      # GET /api/health
│   └── market/            # Already complete — do not touch
│       └── ...
├── tests/
│   ├── __init__.py
│   ├── market/            # Already complete — do not touch
│   └── test_db.py         # New: database init and seed tests
├── pyproject.toml
└── uv.lock
```

### Pattern 1: FastAPI Lifespan Context Manager

**What:** Replaces deprecated `@app.on_event("startup")` handlers. The preferred pattern since FastAPI 0.93. Controls what happens before the app accepts requests and after it shuts down.

**When to use:** Always for resource management (DB init, background tasks, cleanup).

```python
# Source: FastAPI SKILL.md (installed venv), confirmed pattern in FastAPI 0.136.3
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.db.database import init_db
from app.market import create_market_data_source
from app.market.loop import polling_loop

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    init_db()
    source = create_market_data_source()
    await source.start()
    task = asyncio.create_task(
        polling_loop(source, get_tickers=lambda: get_watchlist_tickers(), interval_seconds=0.5)
    )
    yield
    # Shutdown
    task.cancel()
    await source.stop()

app = FastAPI(lifespan=lifespan)
```

### Pattern 2: SQLite Idempotent Init

**What:** Create tables only if absent; insert seed data only if absent. Runs safely on every startup.

**When to use:** Any time the DB file may or may not exist at startup.

```python
# Source: sqlite3 stdlib — CREATE TABLE IF NOT EXISTS and INSERT OR IGNORE
# Both confirmed idempotent via direct testing against Python 3.12 sqlite3 3.50.4
import sqlite3
from pathlib import Path

DB_PATH = Path("/app/db/finally.db")

def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    return con

def init_db() -> None:
    con = get_connection()
    with con:
        _create_tables(con)
        _seed(con)
    con.close()
```

```python
# Schema example — use CREATE TABLE IF NOT EXISTS for all six tables
CREATE_USERS_PROFILE = """
CREATE TABLE IF NOT EXISTS users_profile (
    id TEXT PRIMARY KEY,
    cash_balance REAL NOT NULL DEFAULT 10000.0,
    created_at TEXT NOT NULL
)
"""

CREATE_WATCHLIST = """
CREATE TABLE IF NOT EXISTS watchlist (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT 'default',
    ticker TEXT NOT NULL,
    added_at TEXT NOT NULL,
    UNIQUE(user_id, ticker)
)
"""
# ... (positions, trades, portfolio_snapshots, chat_messages follow same pattern)
```

```python
# Seed example — INSERT OR IGNORE for idempotency
import uuid
from datetime import datetime, timezone

SEED_TICKERS = ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "NVDA", "META", "JPM", "V", "NFLX"]

def _seed(con: sqlite3.Connection) -> None:
    now = datetime.now(timezone.utc).isoformat()
    con.execute(
        "INSERT OR IGNORE INTO users_profile (id, cash_balance, created_at) VALUES (?, ?, ?)",
        ("default", 10000.0, now),
    )
    for ticker in SEED_TICKERS:
        con.execute(
            "INSERT OR IGNORE INTO watchlist (id, user_id, ticker, added_at) VALUES (?, ?, ?, ?)",
            (str(uuid.uuid4()), "default", ticker, now),
        )
```

### Pattern 3: APIRouter with prefix on the router

**What:** Per FastAPI SKILL.md, declare prefix/tags on the router itself, not in `include_router()`.

```python
# Source: FastAPI SKILL.md
from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["system"])

@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}
```

```python
# In main.py
from app.routers.health import router as health_router
app.include_router(health_router)
```

### Pattern 4: Watchlist tickers callable for polling loop

The `polling_loop()` function (already written) takes `get_tickers: Callable[[], list[str]]`. The lifespan must pass a callable that reads the current watchlist from the database each cycle, not a static list. This is how newly added tickers are picked up without restarting the loop.

```python
# In lifespan — pass a DB-reading callable, not a static list
from app.db.database import get_connection

def get_watchlist_tickers() -> list[str]:
    con = get_connection()
    rows = con.execute(
        "SELECT ticker FROM watchlist WHERE user_id = 'default'"
    ).fetchall()
    con.close()
    return [row["ticker"] for row in rows]

# Then in lifespan:
task = asyncio.create_task(
    polling_loop(source, get_tickers=get_watchlist_tickers, interval_seconds=0.5)
)
```

### Anti-Patterns to Avoid

- **`@app.on_event("startup")`:** Deprecated since FastAPI 0.93. Use `lifespan` instead. [CITED: FastAPI SKILL.md]
- **`ORJSONResponse` or `UJSONResponse`:** Deprecated per FastAPI SKILL.md. Use return type annotations for serialization.
- **`...` (Ellipsis) as default:** Do not use `...` as default in path operations or Pydantic models per FastAPI SKILL.md.
- **SQLAlchemy or SQLModel for this phase:** The schema is simple and all queries are straightforward. stdlib `sqlite3` is sufficient and avoids unnecessary dependencies. SQLModel may be appropriate in future phases if the query complexity warrants it.
- **Static hardcoded ticker list in polling loop:** Must be a callable that re-reads the DB — this is the existing loop contract and must be honoured.
- **Re-seeding on every startup:** Use `INSERT OR IGNORE` not `INSERT`. Re-seeding resets cash to $10k on every restart, destroying portfolio state.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Market data polling loop | Custom asyncio loop | `app.market.loop.polling_loop()` — already written and tested | 59 tests passing; re-implementing risks breaking existing behavior |
| Price cache | Custom dict with locking | `app.market.cache.price_cache` singleton | Already handles asyncio.Lock, copy isolation, atomic batch updates |
| Market data source selection | Custom env-var branching | `app.market.create_market_data_source()` | Factory function already written and tested |
| Background task management | Custom task registry | `asyncio.create_task()` in lifespan + `task.cancel()` on shutdown | Standard pattern; no extra framework needed |
| Database connection pooling | Custom pool | None needed — SQLite + single process; one connection per request is fine | SQLite WAL mode handles concurrent reads; single-user app |
| Schema migrations | Alembic or similar | `CREATE TABLE IF NOT EXISTS` + `INSERT OR IGNORE` | No migration history needed; schema is stable; migration framework is overkill for this project |

**Key insight:** The market data layer is complete and battle-tested. Phase 1's job is to create the scaffolding that lets existing code run — not to reimagine it.

---

## Common Pitfalls

### Pitfall 1: Re-seeding cash balance on restart

**What goes wrong:** Using `INSERT OR REPLACE` or `INSERT INTO ... ON CONFLICT DO UPDATE` instead of `INSERT OR IGNORE` for the `users_profile` row. This resets `cash_balance` to $10,000 on every container restart, destroying the user's portfolio.

**Why it happens:** Developer treats seed data as "initial state" rather than "first-time-only default".

**How to avoid:** Use `INSERT OR IGNORE INTO users_profile ...` exclusively. The `IGNORE` in conflict means "if the row already exists, do nothing". [VERIFIED: tested against sqlite3 3.50.4]

**Warning signs:** `cash_balance` is always $10,000 after any restart regardless of trades.

---

### Pitfall 2: Blocking sqlite3 calls inside async path operations

**What goes wrong:** Calling `sqlite3.connect()` and executing queries directly inside an `async def` endpoint. This blocks the asyncio event loop, degrading SSE streaming performance.

**Why it happens:** sqlite3 is synchronous; async functions are not automatically threaded.

**How to avoid:** Per FastAPI SKILL.md, use `def` (not `async def`) for path operations that do blocking I/O, or use `asyncer.asyncify()` to run blocking code in a thread. For Phase 1 (health endpoint only), the health endpoint has no DB queries, so this is not an immediate concern. Document this for Phase 2 implementers.

**Warning signs:** SSE clients receive updates with irregular timing; high latency on concurrent requests.

---

### Pitfall 3: polling_loop get_tickers callable reads stale data

**What goes wrong:** Passing `lambda: ["AAPL", "MSFT", ...]` (a static list captured at startup) instead of a function that queries the database. This means watchlist additions (Phase 2) are never picked up by the polling loop.

**Why it happens:** The lifespan wires up the callable once; if it returns a static list the loop never sees changes.

**How to avoid:** The `get_tickers` argument must call `SELECT ticker FROM watchlist` on each invocation. This is the explicit design contract of `polling_loop()` — see `MARKET_DATA_SUMMARY.md`, "get_tickers callable (not a list)".

**Warning signs:** Prices for newly added tickers never appear in the price cache.

---

### Pitfall 4: DB_PATH hardcoded without parent directory creation

**What goes wrong:** `sqlite3.connect("/app/db/finally.db")` fails if `/app/db/` does not exist (fresh Docker volume, local dev without the `db/` directory).

**Why it happens:** sqlite3 creates the file but not parent directories.

**How to avoid:** `Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)` before connecting. [ASSUMED — standard Python pattern, not verified against Docker environment]

**Warning signs:** `sqlite3.OperationalError: unable to open database file` on first run.

---

### Pitfall 5: Duplicate watchlist seed rows

**What goes wrong:** Each seed ticker gets a new UUID as its primary key. If `INSERT OR IGNORE` is used correctly, only the UNIQUE constraint on `(user_id, ticker)` prevents duplicates — not the UUID primary key (which is always new). If `INSERT OR IGNORE` is missing, duplicate tickers appear in the watchlist on every restart.

**Why it happens:** The `UNIQUE(user_id, ticker)` constraint is what the `INSERT OR IGNORE` fires on. The PRIMARY KEY `id` (UUID) is new each time so it would not trigger the conflict without the UNIQUE constraint.

**How to avoid:** Ensure the `UNIQUE(user_id, ticker)` constraint is declared in the schema. `INSERT OR IGNORE` then fires on that constraint. [VERIFIED: confirmed with sqlite3 3.50.4 test]

---

### Pitfall 6: `@app.on_event("startup")` deprecation warning

**What goes wrong:** Using the deprecated event handler API produces a deprecation warning in uvicorn output and will eventually be removed.

**Why it happens:** Old FastAPI tutorials still use this pattern.

**How to avoid:** Use `lifespan` context manager exclusively. FastAPI 0.136.3 supports lifespan natively. [VERIFIED: FastAPI SKILL.md]

---

## Code Examples

### Complete lifespan wiring

```python
# backend/app/main.py
# Source: FastAPI SKILL.md pattern + market data MARKET_DATA_SUMMARY.md downstream usage example
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from dotenv import load_dotenv

from app.db.database import init_db, get_watchlist_tickers
from app.market import create_market_data_source
from app.market.loop import polling_loop
from app.routers.health import router as health_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_dotenv()
    init_db()
    source = create_market_data_source()
    await source.start()
    task = asyncio.create_task(
        polling_loop(source, get_tickers=get_watchlist_tickers, interval_seconds=0.5)
    )
    yield
    task.cancel()
    await source.stop()


app = FastAPI(lifespan=lifespan)
app.include_router(health_router)
```

### Health endpoint

```python
# backend/app/routers/health.py
# Source: FastAPI SKILL.md — router-level prefix, one function per HTTP operation
from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health")
def health() -> dict:
    """Health check endpoint for Docker and load balancer probes."""
    return {"status": "ok"}
```

### Database initialisation

```python
# backend/app/db/database.py
import sqlite3
from pathlib import Path
import os

DB_PATH = Path(os.getenv("DB_PATH", "/app/db/finally.db"))


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    return con


def get_watchlist_tickers() -> list[str]:
    """Callable for polling_loop — returns current watchlist from DB each call."""
    con = get_connection()
    rows = con.execute(
        "SELECT ticker FROM watchlist WHERE user_id = 'default' ORDER BY added_at"
    ).fetchall()
    con.close()
    return [row["ticker"] for row in rows]


def init_db() -> None:
    """Create schema and seed default data. Safe to call on every startup."""
    from app.db.schema import CREATE_TABLES
    from app.db.seed import seed
    con = get_connection()
    with con:
        for ddl in CREATE_TABLES:
            con.execute(ddl)
        seed(con)
    con.close()
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `@app.on_event("startup")` | `lifespan` context manager | FastAPI 0.93 | Deprecated handler; lifespan is now the only recommended pattern |
| `ORJSONResponse` | Return type annotation (Pydantic serializes in Rust) | FastAPI 0.100+ | ORJSONResponse deprecated; type annotations are faster and simpler |
| `sse-starlette` third-party package | `fastapi.sse.EventSourceResponse` built-in | FastAPI ~0.110+ | No extra package needed for SSE |
| SQLAlchemy for simple SQLite | stdlib `sqlite3` | — | ORM is unnecessary complexity for a single-file SQLite with a fixed schema |

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)` is needed before sqlite3.connect | Pitfall 4 | Low — if `/app/db/` already exists (Docker volume), mkdir is a no-op; if it doesn't exist, the app crashes without it |
| A2 | `APP-02` (static file serving) is a stub for this phase since frontend doesn't exist yet | Phase Requirements | Medium — if planner interprets APP-02 as "must fully work in Phase 1", a fallback 404 or no-op mount is needed |

**Notes on A2:** The ROADMAP.md phase description says "ready to mount API routes" and does not mention static serving. APP-02 is listed as a Phase 1 requirement in REQUIREMENTS.md but the frontend doesn't exist until Phase 4/6. The planner should implement APP-02 as a conditional `StaticFiles` mount that skips gracefully if the static directory doesn't exist, or stub it as a comment noting "mounted in Phase 6".

---

## Open Questions

1. **APP-02 scope in Phase 1**
   - What we know: APP-02 requires static file serving but the Next.js build doesn't exist until Phase 6
   - What's unclear: Should Phase 1 mount a placeholder StaticFiles, or defer entirely to Phase 6?
   - Recommendation: Mount conditionally — `if static_dir.exists(): app.mount(...)` so the app starts cleanly in both local dev and production. This avoids a startup error in Phase 1 while being Phase 6-ready.

2. **DB_PATH in local dev vs Docker**
   - What we know: Docker mounts `/app/db/`; local dev uses `backend/` as cwd
   - What's unclear: Should `DB_PATH` default to a local path for `uv run` invocations?
   - Recommendation: `DB_PATH = os.getenv("DB_PATH", "db/finally.db")` — relative path works for `cd backend && uv run` (creates `backend/../db/finally.db`, matching the repo's `db/` directory); Docker sets `DB_PATH=/app/db/finally.db` via env.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.12 | All backend | ✓ | 3.12 (venv active) | — |
| uv | Package management | ✓ | in PATH | — |
| fastapi | APP-01, APP-03 | ✓ | 0.136.3 | — |
| uvicorn[standard] | Running the app | ✓ | 0.48.0 | — |
| pydantic | Data models | ✓ | 2.13.4 | — |
| python-dotenv | .env loading | ✓ | in uv.lock | — |
| sqlite3 | DB-01, DB-02, DB-03 | ✓ | 3.50.4 (stdlib) | — |
| pytest / pytest-asyncio | Testing | ✓ | in dev group | — |

**Missing dependencies with no fallback:** None

**Missing dependencies with fallback:** None

All dependencies are already present. No new installs required.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 8.x + pytest-asyncio 0.23 |
| Config file | `backend/pyproject.toml` (`[tool.pytest.ini_options]` with `asyncio_mode = "auto"`) |
| Quick run command | `cd backend && uv run --group dev pytest tests/test_db.py -x -q` |
| Full suite command | `cd backend && uv run --group dev pytest -q` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| APP-01 | lifespan starts without error; polling loop task created | integration | `pytest tests/test_app.py::test_lifespan_startup -x` | No — Wave 0 |
| APP-03 | `GET /api/health` returns `{"status": "ok"}` | unit | `pytest tests/test_app.py::test_health_endpoint -x` | No — Wave 0 |
| DB-01 | `init_db()` creates all tables on empty DB | unit | `pytest tests/test_db.py::test_init_creates_tables -x` | No — Wave 0 |
| DB-01 | `init_db()` does not error on existing DB | unit | `pytest tests/test_db.py::test_init_idempotent -x` | No — Wave 0 |
| DB-02 | All 6 tables present after init | unit | `pytest tests/test_db.py::test_all_tables_exist -x` | No — Wave 0 |
| DB-03 | Seed data: 1 user profile, 10 watchlist tickers | unit | `pytest tests/test_db.py::test_seed_data -x` | No — Wave 0 |
| DB-03 | Re-running seed does not duplicate data | unit | `pytest tests/test_db.py::test_seed_idempotent -x` | No — Wave 0 |

### Sampling Rate

- **Per task commit:** `cd backend && uv run --group dev pytest tests/test_db.py tests/test_app.py -q`
- **Per wave merge:** `cd backend && uv run --group dev pytest -q` (full suite including 59 existing market tests)
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps

- [ ] `backend/tests/test_db.py` — covers DB-01, DB-02, DB-03
- [ ] `backend/tests/test_app.py` — covers APP-01, APP-03 (uses `httpx.AsyncClient` with `TestClient` or `ASGITransport`)
- [ ] No new framework install needed — pytest-asyncio already in dev group

---

## Security Domain

> `security_enforcement: true`, `security_asvs_level: 1`

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | No auth — single user, `user_id="default"` hardcoded by design |
| V3 Session Management | No | No sessions — stateless API |
| V4 Access Control | No | No multi-user access control |
| V5 Input Validation | Minimal | Health endpoint has no inputs; DB init has no external inputs |
| V6 Cryptography | No | No secrets stored or transmitted in this phase |
| V7 Error Handling | Yes | FastAPI default exception handlers; do not expose stack traces in health response |
| V14 Config | Yes | API keys in `.env` (gitignored); `.env.example` committed without values |

### Known Threat Patterns

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| `.env` committed to git with real API keys | Information Disclosure | `.env` is gitignored per PLAN.md; `.env.example` only |
| SQLite path traversal | Tampering | `DB_PATH` is controlled by env var; in Phase 1 there is no user-supplied path input |
| Error details in health response | Information Disclosure | Return only `{"status": "ok"}` — no stack traces, version info, or internal paths |

---

## Sources

### Primary (HIGH confidence)

- FastAPI SKILL.md (installed at `backend/.venv/lib/python3.12/site-packages/fastapi/.agents/skills/fastapi/SKILL.md`) — lifespan pattern, router conventions, SSE, async/sync guidance
- FastAPI streaming reference (same location, `references/streaming.md`) — native SSE confirmed
- `planning/MARKET_DATA_SUMMARY.md` — complete documentation of existing market data modules
- `backend/app/market/` source files — confirmed API: `create_market_data_source()`, `polling_loop()`, `price_cache` singleton
- `backend/pyproject.toml` + `uv.lock` — confirmed installed versions
- Direct venv tests — FastAPI 0.136.3 version, SSE import, sqlite3 3.50.4, WAL mode, INSERT OR IGNORE idempotency

### Secondary (MEDIUM confidence)

- `planning/PLAN.md` — schema specification, seed data list, architecture decisions
- `.planning/REQUIREMENTS.md` — requirement IDs and descriptions
- `.planning/ROADMAP.md` — phase goals and success criteria

### Tertiary (LOW confidence)

None — all research grounded in codebase inspection and direct verification.

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all packages confirmed installed and version-verified
- Architecture: HIGH — existing module APIs read directly from source; FastAPI patterns from installed SKILL.md
- Pitfalls: HIGH — most grounded in direct test results (INSERT OR IGNORE, CREATE TABLE IF NOT EXISTS) or explicit SKILL.md anti-patterns
- Test strategy: HIGH — existing pytest infrastructure confirmed with 59 passing tests

**Research date:** 2026-05-29
**Valid until:** 2026-07-29 (FastAPI patch releases unlikely to break these patterns)
