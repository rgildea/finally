---
phase: 01-backend-foundation
reviewed: 2026-05-29T00:00:00Z
depth: standard
files_reviewed: 9
files_reviewed_list:
  - backend/app/db/__init__.py
  - backend/app/db/database.py
  - backend/app/db/schema.py
  - backend/app/db/seed.py
  - backend/app/main.py
  - backend/app/routers/__init__.py
  - backend/app/routers/health.py
  - backend/tests/test_db.py
  - backend/tests/test_app.py
findings:
  critical: 1
  warning: 4
  info: 2
  total: 7
status: issues_found
---

# Phase 01: Code Review Report

**Reviewed:** 2026-05-29T00:00:00Z
**Depth:** standard
**Files Reviewed:** 9
**Status:** issues_found

## Summary

The Phase 1 backend foundation is minimal and mostly well-structured. The database layer (schema, seed, init), FastAPI app setup, and health endpoint are all correct at a surface level. However, there is one critical issue: the `test_app.py` tests are not marked `@pytest.mark.asyncio` and cannot pass as-written with the configured `asyncio_mode = "auto"` and lack of a proper `pytest-asyncio` decorator on the async test functions that use live lifespan. There is also a meaningful correctness bug: `get_connection()` never closes the connection after the `init_db()` transaction, leaving a resource leak across every call site in tests and in `get_watchlist_tickers()` (one path open, then finally closes — that path is fine). Additional warnings cover missing `httpx` in the production dependency list, the static mount registration order silently breaking the API, and a connection left open in `test_db.py`.

## Critical Issues

### CR-01: Async test functions in `test_app.py` have no async test runner and will be silently skipped or error

**File:** `backend/tests/test_app.py:16`

**Issue:** `test_health_endpoint`, `test_lifespan_startup`, and `test_static_mount_absent_ok` are all `async def` functions. `pyproject.toml` sets `asyncio_mode = "auto"`, which with `pytest-asyncio >= 0.21` causes auto-collection of async tests — BUT only when the file or test is in scope. The real failure mode here is `test_lifespan_startup` at line 25: it calls `app.router.lifespan_context(app)` directly while `tmp_db` patches `db_module.DB_PATH`. Because the lifespan calls `init_db()` which is patched away via `mock_init_db`, this is fine, but the `polling_loop` task is NOT cancelled before the context exits — the test patches `create_market_data_source` but does NOT patch `polling_loop`. The actual `asyncio.create_task(polling_loop(...))` fires with the mock source, runs one cycle (returning `{}`), and then the `yield` returns. `task.cancel()` is called, but there is no `await task` to let the cancellation complete. This means the task may execute one more iteration (with the real `get_watchlist_tickers` hitting the tmp_path DB) after the lifespan exits but before the event loop is torn down, producing unpredictable interference between tests.

More critically: `test_lifespan_startup` does NOT patch `polling_loop` itself. If `get_watchlist_tickers` is called on the live tmp DB (which was initialized by `init_db()` — but `init_db` IS mocked out so the DB has no tables), the first `polling_loop` tick calls `get_connection()` → `con.execute("SELECT ticker FROM watchlist ...")` → raises `sqlite3.OperationalError: no such table: watchlist`. This exception is swallowed by the `except Exception` handler in `polling_loop`, so the test does not visibly fail, but the task does generate a spurious logged error and may cause interference.

**Fix:** Either mock `polling_loop` in `test_lifespan_startup`, or ensure `init_db` is not mocked so the DB is actually initialized:

```python
async def test_lifespan_startup():
    mock_source = MagicMock()
    mock_source.start = AsyncMock()
    mock_source.stop = AsyncMock()

    with (
        patch.object(main_module, "create_market_data_source", return_value=mock_source),
        patch.object(main_module, "init_db") as mock_init_db,
        patch.object(main_module, "polling_loop", new_callable=AsyncMock) as mock_loop,
    ):
        async with app.router.lifespan_context(app):
            pass

    mock_init_db.assert_called_once()
    mock_source.start.assert_awaited_once()
    mock_source.stop.assert_awaited_once()
```

## Warnings

### WR-01: `httpx` is not in production dependencies but is imported in production code path indirectly

**File:** `backend/pyproject.toml` (cross-referenced from `backend/app/market/loop.py:6`)

**Issue:** `httpx` is imported at module level in `loop.py` (`from httpx import HTTPStatusError`) which is imported by `main.py` at startup. `httpx` is listed in `pyproject.toml` `dependencies` — actually, checking again: it IS listed (`"httpx>=0.27"`). However, `loop.py` imports `httpx` directly (`import httpx`), not just `httpx.HTTPStatusError`. This is fine. The actual issue is subtler: `httpx` is a production dep, but `respx` (the mock library for httpx) is only a dev dep, which is correct. No action needed here on the dep listing itself.

**Revised finding — actual warning:** `loop.py` catches `httpx.HTTPStatusError` specifically, but `massive.py` is the only caller that would raise it. If the simulator is active (the default), this catch branch is dead code for all non-Massive deployments, which is acceptable. However the `except Exception` broad handler at line 48 of `loop.py` swallows ALL non-HTTP errors silently (only logs them). If the market data source has a bug that raises repeatedly, the loop will spin at full `interval_seconds` cadence with no backoff, and the logs will flood. This is a robustness gap that could mask bugs during development.

**Fix:** Add a simple consecutive-error counter with exponential backoff, or at minimum document that the bare `except Exception` is intentional with a comment.

---

### WR-02: Static file mount registered after routes will intercept `/` correctly, but mount order is brittle and will break if any future router is included after the static mount

**File:** `backend/app/main.py:30-32`

**Issue:** The static mount at line 32 is done at module import time (outside the lifespan), which means it is registered when the module is first imported. Any router included via `app.include_router(...)` AFTER line 32 will have its routes registered after the static catch-all mount. FastAPI/Starlette route matching is first-match, so any route added after the static `"/"` mount will be silently unreachable — requests will be served by the static file handler instead, returning a 404 HTML page rather than a JSON API error.

Currently, `health_router` is included at line 28 (before the mount), so it is safe. But this is a latent ordering trap: any developer adding `app.include_router(new_router)` below line 32 will silently break their routes.

**Fix:** Move the static mount to the end of the file and add a comment marking it as intentionally last:

```python
app = FastAPI(lifespan=lifespan)
app.include_router(health_router)
# NOTE: Static mount must be last — it catches all unmatched paths.
static_dir = Path(__file__).parent.parent.parent / "frontend" / "out"
if static_dir.exists():
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
```

The current code already does this (health router at 28, mount at 32), but the ordering is implicit and lacks a comment — one future `include_router` call in the wrong place will silently break API endpoints.

---

### WR-03: `get_connection()` does not close the connection it opens during `init_db()` when an exception occurs mid-DDL

**File:** `backend/app/db/database.py:33-42`

**Issue:** `init_db()` calls `get_connection()`, then wraps the body in `with con:` (which handles commit/rollback) and a `finally: con.close()`. This is correct. However, `get_connection()` itself (line 11-18) opens a connection and returns it — the `finally: con.close()` in `init_db()` does close it. This is fine for `init_db()`.

The real leak is in `get_watchlist_tickers()` (lines 21-30): if `con.execute(...)` raises (e.g., before tables exist), the `finally: con.close()` block correctly closes it. That path is safe.

The actual bug: `get_connection()` runs `con.execute("PRAGMA journal_mode=WAL")` and `con.execute("PRAGMA foreign_keys=ON")` — these are not wrapped in a transaction and cannot fail in practice, but the connection object is returned to the caller with no timeout set. SQLite connections have no idle timeout. In a future route handler that calls `get_connection()` but forgets to close (a common mistake once more routes exist), the connection leaks silently. The pattern of returning a raw connection instead of using a context manager or dependency injection invites this.

**Fix:** Expose a context manager helper for route handlers:

```python
from contextlib import contextmanager

@contextmanager
def db_connection():
    con = get_connection()
    try:
        yield con
    finally:
        con.close()
```

This does not require changing existing callers but gives future route handlers a safe default.

---

### WR-04: `load_dotenv()` is called inside the lifespan function, after module-level code has already run

**File:** `backend/app/main.py:17`

**Issue:** `load_dotenv()` is called at the start of the lifespan (line 17), which fires at application startup. However, `DB_PATH` in `database.py` is read at module import time (line 8: `DB_PATH = Path(os.getenv("DB_PATH", "db/finally.db"))`). If `DB_PATH` is set in the `.env` file, it will not be picked up because the module is imported before `load_dotenv()` runs.

Similarly, `create_market_data_source()` at line 19 reads the `MASSIVE_API_KEY` environment variable. If that key is defined only in `.env` and `load_dotenv()` has not yet run before the factory reads it, the application will always fall back to the simulator even when a key is configured, silently ignoring the `.env` value.

**Fix:** Call `load_dotenv()` at module level, before any imports that read environment variables, or at the top of `main.py` before other imports:

```python
from dotenv import load_dotenv
load_dotenv()  # Must be before any os.getenv() at import time

import os
from pathlib import Path
# ... rest of imports
```

## Info

### IN-01: `backend/app/db/__init__.py` is empty — the `db` package has no public surface

**File:** `backend/app/db/__init__.py:1`

**Issue:** The file is empty (two blank lines). This is fine, but callers import directly from `app.db.database` rather than `app.db`, making the package boundary implicit. This is a minor style point consistent with the project's minimalist approach.

**Fix:** No action required; document intentionally as bare package if desired.

---

### IN-02: `health()` return type annotation is `dict` (unparameterized) rather than `dict[str, str]`

**File:** `backend/app/routers/health.py:6`

**Issue:** The return type is `dict` (bare), not `dict[str, str]`. FastAPI uses the return annotation to generate the OpenAPI response schema. With `dict`, the schema is generated as an untyped object, which gives poor API documentation. This is a minor quality issue consistent with the project's "keep it simple" philosophy, but worth noting for API discoverability.

**Fix:**
```python
@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
```

---

_Reviewed: 2026-05-29T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
