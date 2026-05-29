# Coding Conventions

**Analysis Date:** 2026-05-29

## Naming Patterns

**Files:**
- Snake_case for all Python modules: `cache.py`, `simulator.py`, `massive.py`, `interface.py`, `loop.py`
- Test files prefixed with `test_`: `test_cache.py`, `test_simulator.py`, `test_massive.py`
- Directories: snake_case (`market/`, `tests/`)

**Classes:**
- PascalCase: `PriceCache`, `MarketSimulator`, `MassiveAPIClient`, `SimulatorConfig`, `TickerConfig`, `PriceUpdate`
- Abstract base classes use descriptive nouns: `MarketDataSource`

**Functions and Methods:**
- snake_case: `get_prices()`, `update_many()`, `polling_loop()`, `create_market_data_source()`
- Private/internal methods prefixed with `_`: `_tick()`, `_run_loop()`, `_draw_sector_shocks()`, `_maybe_trigger_event()`, `_parse_response()`, `_extract_price()`, `_extract_timestamp()`, `_merge_with_prev()`

**Variables:**
- snake_case: `api_key`, `tick_interval_seconds`, `seed_price`
- Module-level constants: `UPPER_SNAKE_CASE` — `MASSIVE_BASE_URL`, `SNAPSHOT_PATH`
- Module-level private dicts/objects: `_DEFAULT_TICKERS`, `_DEFAULT_CORRELATIONS`, `_FALLBACK_CONFIG`
- Instance attributes: prefixed with `_` for private state: `self._data`, `self._lock`, `self._task`, `self._client`, `self._prices`

**Type Annotations:**
- Full PEP 604 union syntax throughout: `float | None`, `asyncio.Task | None`, `httpx.AsyncClient | None`
- All function signatures annotated with return types: `-> None`, `-> dict[str, PriceUpdate]`, `-> float | None`

## Code Style

**Formatting:**
- Tool: `ruff` (configured in `backend/pyproject.toml` dev dependencies)
- No separate `.prettierrc` or `.flake8` — ruff handles both linting and formatting

**Linting:**
- Tool: `ruff` (version `>=0.15.14`)
- No inline `# noqa` or `# type: ignore` suppressions detected — clean codebase

## Import Organization

**Order (observed):**
1. Standard library imports (`asyncio`, `dataclasses`, `logging`, `math`, `random`, `os`)
2. Third-party imports (`httpx`, `pytest`, `pydantic`)
3. Local/relative imports (`.interface`, `.cache`, `.simulator`, `app.market.*`)

**Style:**
- Relative imports used within `app/market/` package: `from .interface import ...`, `from .cache import price_cache`
- Absolute imports used in tests: `from app.market.cache import PriceCache`
- Test files import specific names, not whole modules (except `from app.market import cache as cache_module` when patching module state)

## Error Handling

**Patterns:**
- Exceptions propagate naturally for caller handling (e.g., `httpx.HTTPStatusError` from `get_prices()`)
- Exceptions documented in docstrings under `Raises:` section: `RuntimeError`, `httpx.HTTPStatusError`, `asyncio.TimeoutError`
- `asyncio.CancelledError` is always re-raised explicitly — never swallowed: `except asyncio.CancelledError: raise`
- Transient errors in background loops are caught and logged, then the loop continues: `except Exception: logger.exception(...)`
- HTTP 429 errors in `polling_loop()` trigger 60-second back-off (`backend/app/market/loop.py:40-43`)
- Guard clauses raise `RuntimeError` for invalid pre-conditions: `if not self._client: raise RuntimeError("start() must be called...")`
- No bare `except:` clauses — always `except Exception:` or specific types

## Logging

**Framework:** Python standard library `logging`

**Setup pattern:**
```python
logger = logging.getLogger(__name__)
```
Used in `simulator.py`, `massive.py`, `loop.py`. Module-level logger, `__name__` as logger name.

**Patterns:**
- `logger.info()` for lifecycle events: start/stop of services
- `logger.warning()` for recoverable issues (rate limits)
- `logger.error()` for non-fatal HTTP errors
- `logger.debug()` for high-frequency operational detail (market events, skipped tickers)
- `logger.exception()` in broad except blocks to include traceback automatically

## Comments

**When to Comment:**
- Inline comments for non-obvious math/logic: GBM formula, sector-shock mixing, factor loadings
- Short inline annotations clarifying design intent: `# polling loop replaces this with cached prev`
- Module-level constants with inline explanations for parameters: `# Annual drift`, `# Per tick, globally`

**Docstrings:**
- Class-level docstrings describe purpose, threading model, and key behaviors
- Method docstrings include `Args:` and `Raises:` sections for non-trivial methods
- One-line docstrings for simple methods: `"""Store the latest PriceUpdate for a ticker."""`
- Test functions use docstrings to explain what property is being verified (especially for edge cases)

## Function Design

**Size:** Functions are short — largest production methods are `_tick()` (~20 lines), `_parse_response()` (~25 lines), `polling_loop()` (~20 lines). Private helpers are extracted for reuse and clarity.

**Parameters:** Prefer named parameters for config/optional values. Callables typed with `Callable[[], list[str]]`.

**Return Values:**
- Missing/unknown results expressed as `None` return or omission from dicts — never sentinel values
- Dicts returned as `dict[str, PriceUpdate]` — missing tickers are omitted (documented in docstrings)

## Module Design

**Exports:**
- `__all__` defined explicitly in `backend/app/market/__init__.py`
- Factory function `create_market_data_source()` exported from `__init__.py` as the single construction point

**Module-Level Singletons:**
- `price_cache = PriceCache()` in `backend/app/market/cache.py` — module-level singleton imported by `loop.py` and SSE endpoint
- Dataclass constants (`_DEFAULT_TICKERS`, `_FALLBACK_CONFIG`) at module level in `simulator.py`

**Dataclasses vs Pydantic:**
- Pydantic `BaseModel` for external data and computed fields: `PriceUpdate` in `interface.py`
- Python `@dataclass` for pure config/value objects with no validation needed: `TickerConfig`, `SimulatorConfig`

---

*Convention analysis: 2026-05-29*
