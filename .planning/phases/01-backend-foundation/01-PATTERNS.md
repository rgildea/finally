# Phase 1: Backend Foundation - Pattern Map

**Mapped:** 2026-05-29
**Files analyzed:** 10
**Analogs found:** 8 / 10

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `backend/app/__init__.py` | module-init | — | `backend/app/market/__init__.py` | exact |
| `backend/app/main.py` | entrypoint | event-driven (lifespan) | `backend/app/market/__init__.py` + RESEARCH.md | role-match |
| `backend/app/db/__init__.py` | module-init | — | `backend/app/market/__init__.py` | exact |
| `backend/app/db/database.py` | utility | request-response (sync I/O) | `backend/app/market/cache.py` (singleton pattern) | partial |
| `backend/app/db/schema.py` | config | — | RESEARCH.md Pattern 2 | no analog |
| `backend/app/db/seed.py` | utility | batch | RESEARCH.md Pattern 2 | no analog |
| `backend/app/routers/__init__.py` | module-init | — | `backend/app/market/__init__.py` | exact |
| `backend/app/routers/health.py` | router | request-response | RESEARCH.md Pattern 3 + FastAPI SKILL.md | role-match |
| `backend/tests/test_db.py` | test | batch | `backend/tests/market/test_cache.py` | role-match |
| `backend/tests/test_app.py` | test | event-driven | `backend/tests/market/test_loop.py` | role-match |

---

## Pattern Assignments

### `backend/app/__init__.py` (module-init)

**Analog:** `backend/app/market/__init__.py`

**Pattern** (lines 1-1 of analog — file is empty, one blank line):
```python
# empty — package marker only
```

The existing `backend/app/__init__.py` is already a single empty line. The new file is identical: an empty package marker. Do not add imports here.

---

### `backend/app/main.py` (entrypoint, event-driven)

**Analog:** `backend/app/market/__init__.py` (factory + env-var dispatch pattern) plus RESEARCH.md lifespan code examples.

**Imports pattern** — copy from RESEARCH.md Code Examples (verified against installed venv):
```python
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from dotenv import load_dotenv

from app.db.database import init_db, get_watchlist_tickers
from app.market import create_market_data_source
from app.market.loop import polling_loop
from app.routers.health import router as health_router
```

**Lifespan context manager** — the only startup/shutdown mechanism; do not use `@app.on_event`:
```python
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

**Static files stub** — mount only when the directory exists (frontend not built until Phase 6):
```python
from pathlib import Path
from fastapi.staticfiles import StaticFiles

static_dir = Path(__file__).parent.parent / "static"
if static_dir.exists():
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
```

**`polling_loop` contract** (from `backend/app/market/loop.py` lines 12-17): `get_tickers` is a `Callable[[], list[str]]` called on every cycle. Must pass a function that queries the DB — not a static list.

---

### `backend/app/db/__init__.py` (module-init)

**Analog:** `backend/app/market/__init__.py`

**Pattern:** Empty package marker — single blank line. No imports needed; callers import directly from `app.db.database`, `app.db.schema`, `app.db.seed`.

---

### `backend/app/db/database.py` (utility, sync I/O)

**Analog:** `backend/app/market/cache.py` (module-level singleton pattern, lines 47-48) and RESEARCH.md Pattern 2.

**Singleton pattern from analog** (`backend/app/market/cache.py` lines 47-48):
```python
# Module-level singleton — imported by loop.py and the SSE endpoint
price_cache = PriceCache()
```
Apply the same "one module-level object, imported everywhere" pattern: `DB_PATH` is the module-level constant, `get_connection()` is the reusable factory.

**Core pattern** (from RESEARCH.md Code Examples, verified):
```python
import sqlite3
import os
from pathlib import Path

DB_PATH = Path(os.getenv("DB_PATH", "db/finally.db"))


def get_connection() -> sqlite3.Connection:
    """Return a new sqlite3 connection. Caller is responsible for closing."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    return con


def get_watchlist_tickers() -> list[str]:
    """Callable for polling_loop — re-queries DB each call so new tickers are picked up."""
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

**DB_PATH note:** Default is `"db/finally.db"` (relative), which resolves to `backend/../db/finally.db` when run via `cd backend && uv run`. Docker sets `DB_PATH=/app/db/finally.db` via env.

**Blocking I/O note:** Use `def` (not `async def`) for all db functions. sqlite3 is synchronous; FastAPI will run `def` path operations in a threadpool automatically. Do not call `get_connection()` inside `async def` endpoints.

---

### `backend/app/db/schema.py` (config)

**No codebase analog** — use RESEARCH.md Pattern 2 directly.

**Pattern:** One `CREATE TABLE IF NOT EXISTS` string per table, collected in a `CREATE_TABLES` list. The caller (`init_db`) iterates and executes each in order.

```python
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

# positions, trades, portfolio_snapshots, chat_messages follow same pattern
# (full schema in planning/PLAN.md § 7 "Schema")

CREATE_TABLES = [
    CREATE_USERS_PROFILE,
    CREATE_WATCHLIST,
    CREATE_POSITIONS,
    CREATE_TRADES,
    CREATE_PORTFOLIO_SNAPSHOTS,
    CREATE_CHAT_MESSAGES,
]
```

**Critical:** The `UNIQUE(user_id, ticker)` constraint on `watchlist` is what makes `INSERT OR IGNORE` idempotent for seed rows — the UUID primary key is always new and would not prevent duplicates on its own.

---

### `backend/app/db/seed.py` (utility, batch)

**No codebase analog** — use RESEARCH.md Pattern 2 directly.

**Pattern:** `INSERT OR IGNORE` for all seed rows; `seed()` accepts an open connection so it runs within the same transaction as schema creation.

```python
import uuid
from datetime import datetime, timezone
import sqlite3

SEED_TICKERS = ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "NVDA", "META", "JPM", "V", "NFLX"]


def seed(con: sqlite3.Connection) -> None:
    """Insert default user and watchlist if not already present."""
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

**Critical:** Use `INSERT OR IGNORE`, never `INSERT OR REPLACE` — `REPLACE` deletes and re-inserts, resetting `cash_balance` to $10,000 on every restart.

---

### `backend/app/routers/__init__.py` (module-init)

**Analog:** `backend/app/market/__init__.py`

**Pattern:** Empty package marker only. Routers are imported directly by `main.py` (`from app.routers.health import router as health_router`).

---

### `backend/app/routers/health.py` (router, request-response)

**Analog:** FastAPI SKILL.md "Including Routers" section (lines 246-265 of SKILL.md) — prefix declared on the router, not in `include_router()`.

**Pattern** (from RESEARCH.md Pattern 3, consistent with FastAPI SKILL.md):
```python
from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health")
def health() -> dict:
    """Health check endpoint for Docker and load balancer probes."""
    return {"status": "ok"}
```

**Key rules from FastAPI SKILL.md:**
- Prefix and tags on the `APIRouter`, not in `include_router()` (SKILL.md lines 246-265)
- Use `def` not `async def` — no async work here
- Return type annotation (`-> dict`) rather than `ORJSONResponse` (SKILL.md line 240: "Do not use `ORJSONResponse` or `UJSONResponse`, they are deprecated")
- No `...` (Ellipsis) as default anywhere (SKILL.md lines 117-158)

---

### `backend/tests/test_db.py` (test, batch)

**Analog:** `backend/tests/market/test_cache.py` (role-match — unit tests against a data-layer module)

**Imports pattern** (from `backend/tests/market/test_cache.py` lines 1-6):
```python
import pytest
from app.market.cache import PriceCache
from app.market.interface import PriceUpdate
```
Apply same structure — import only what the test exercises:
```python
import sqlite3
import pytest
from app.db.database import get_connection, init_db
```

**Fixture pattern** (from `backend/tests/market/test_loop.py` lines 22-27 — reset shared state before each test):
```python
@pytest.fixture(autouse=True)
def clear_global_cache():
    cache_module.price_cache._data.clear()
    yield
    cache_module.price_cache._data.clear()
```
Adapt for DB tests — use a temp file or in-memory DB per test to avoid state leakage:
```python
import tempfile
import pytest
from pathlib import Path
from app.db import database as db_module

@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    """Point DB_PATH at a fresh temp file for each test."""
    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "test.db")
    yield
```

**Test structure** (from `backend/tests/market/test_cache.py` — one assertion per function, descriptive names):
```python
def test_init_creates_tables(tmp_db):
    init_db()
    con = get_connection()
    tables = {row[0] for row in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    assert "users_profile" in tables
    assert "watchlist" in tables
    # ... assert all 6 tables
    con.close()

def test_init_idempotent(tmp_db):
    init_db()
    init_db()  # second call must not raise

def test_seed_data(tmp_db):
    init_db()
    con = get_connection()
    profile = con.execute("SELECT * FROM users_profile WHERE id='default'").fetchone()
    assert profile is not None
    assert profile["cash_balance"] == 10000.0
    tickers = con.execute("SELECT ticker FROM watchlist WHERE user_id='default'").fetchall()
    assert len(tickers) == 10
    con.close()

def test_seed_idempotent(tmp_db):
    init_db()
    init_db()
    con = get_connection()
    count = con.execute("SELECT COUNT(*) FROM watchlist WHERE user_id='default'").fetchone()[0]
    assert count == 10  # not 20
    con.close()
```

**pytest config** (`backend/pyproject.toml` lines 18-20): `asyncio_mode = "auto"`, `testpaths = ["tests"]`. DB tests are synchronous — no `@pytest.mark.asyncio` needed.

---

### `backend/tests/test_app.py` (test, event-driven)

**Analog:** `backend/tests/market/test_loop.py` (role-match — async tests using `asyncio.create_task`, mock objects, `AsyncMock`)

**Imports pattern** (from `backend/tests/market/test_loop.py` lines 1-10):
```python
import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.market import cache as cache_module
from app.market.interface import PriceUpdate
from app.market.loop import _merge_with_prev, polling_loop
```
Adapt for app tests using `httpx.AsyncClient` with FastAPI's `ASGITransport`:
```python
import pytest
import httpx
from unittest.mock import AsyncMock, patch
from app.main import app
```

**Health endpoint test** — synchronous path operation, use `httpx.AsyncClient` with `ASGITransport`:
```python
@pytest.mark.asyncio
async def test_health_endpoint():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

**Lifespan startup test** — mock market data source to avoid real network/GBM calls:
```python
@pytest.mark.asyncio
async def test_lifespan_startup():
    mock_source = MagicMock()
    mock_source.start = AsyncMock()
    mock_source.stop = AsyncMock()
    mock_source.get_prices = AsyncMock(return_value={})
    with patch("app.main.create_market_data_source", return_value=mock_source):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/api/health")
        assert response.status_code == 200
    mock_source.start.assert_called_once()
    mock_source.stop.assert_called_once()
```

**Task cancellation pattern** (from `backend/tests/market/test_loop.py` lines 84-98):
```python
task = asyncio.create_task(polling_loop(...))
await asyncio.sleep(0.12)
task.cancel()
try:
    await task
except asyncio.CancelledError:
    pass
```
The same `try/except asyncio.CancelledError` pattern applies when testing that the lifespan shuts down cleanly.

---

## Shared Patterns

### Module-level singleton
**Source:** `backend/app/market/cache.py` lines 47-48
**Apply to:** `backend/app/db/database.py`
```python
# Module-level constant — imported by all db modules
DB_PATH = Path(os.getenv("DB_PATH", "db/finally.db"))
```
One authoritative source of `DB_PATH`; all other db modules import from `app.db.database`.

### `__all__` in package `__init__.py`
**Source:** `backend/app/market/__init__.py` lines 8-16
**Apply to:** `backend/app/db/__init__.py` if public API needs advertising; optional for this phase since all callers use direct imports.

### Test isolation via `monkeypatch` + `tmp_path`
**Source:** `backend/tests/market/test_loop.py` lines 22-27 (autouse fixture resetting global state)
**Apply to:** `backend/tests/test_db.py`
Use `monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "test.db")` so each test gets a fresh database without touching the real `db/finally.db`.

### `def` over `async def` for blocking I/O
**Source:** FastAPI SKILL.md (blocking I/O guidance); RESEARCH.md Pitfall 2
**Apply to:** All functions in `backend/app/db/` and `backend/app/routers/health.py`
SQLite calls block the event loop if placed in `async def`. Use plain `def`. FastAPI runs `def` path operations in a threadpool.

### Return type annotations, not ORJSONResponse
**Source:** FastAPI SKILL.md lines 162-181, 240-242
**Apply to:** `backend/app/routers/health.py` and all future routers
```python
@router.get("/health")
def health() -> dict:
    return {"status": "ok"}
```

### Router prefix on the router, not `include_router()`
**Source:** FastAPI SKILL.md lines 246-265
**Apply to:** `backend/app/routers/health.py` and all future routers
```python
router = APIRouter(prefix="/api", tags=["system"])
# In main.py:
app.include_router(health_router)  # no prefix/tags here
```

---

## No Analog Found

Files with no close match in the codebase (planner should use RESEARCH.md patterns directly):

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `backend/app/db/schema.py` | config | — | No SQL schema files exist yet; pattern is raw `CREATE TABLE IF NOT EXISTS` strings |
| `backend/app/db/seed.py` | utility | batch | No seed/fixture data files exist yet; pattern is `INSERT OR IGNORE` with stdlib sqlite3 |

Both are straightforward: RESEARCH.md Pattern 2 provides complete, verified code for both files.

---

## Metadata

**Analog search scope:** `backend/app/market/`, `backend/tests/market/`, `backend/pyproject.toml`, FastAPI installed SKILL.md
**Files scanned:** 9 source files + FastAPI SKILL.md
**Pattern extraction date:** 2026-05-29
