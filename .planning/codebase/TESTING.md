# Testing Patterns

**Analysis Date:** 2026-05-29

## Test Framework

**Runner:**
- pytest `>=8.0`
- Config: `backend/pyproject.toml` under `[tool.pytest.ini_options]`
- `asyncio_mode = "auto"` — all async tests run automatically without extra decorator boilerplate (though `@pytest.mark.asyncio` is also used explicitly throughout)

**Async Extension:**
- pytest-asyncio `>=0.23`

**HTTP Mocking:**
- respx `>=0.21` — for mocking `httpx.AsyncClient` requests

**Assertion Library:**
- pytest built-in assertions + `pytest.approx` for float comparisons

**Run Commands:**
```bash
cd backend && uv run pytest              # Run all tests
cd backend && uv run pytest -v           # Verbose output
cd backend && uv run pytest tests/market/test_simulator.py  # Run specific file
```

## Test File Organization

**Location:**
- Separate `tests/` tree mirroring the `app/` package structure
- `backend/tests/` mirrors `backend/app/`
- `backend/tests/market/` mirrors `backend/app/market/`

**Naming:**
- Test files: `test_<module>.py` matching the module under test
- Test functions: `test_<behavior_description>()` — descriptive, lowercase with underscores

**Structure:**
```
backend/
├── app/
│   └── market/
│       ├── cache.py
│       ├── interface.py
│       ├── loop.py
│       ├── massive.py
│       └── simulator.py
└── tests/
    ├── __init__.py
    └── market/
        ├── __init__.py
        ├── test_cache.py
        ├── test_interface.py
        ├── test_loop.py
        ├── test_massive.py
        └── test_simulator.py
```

## Test Structure

**Suite Organization:**
```python
# No describe-style grouping — flat list of test functions per file
# Logical sections separated by comments when file covers multiple concerns

# ── _parse_response unit tests (no HTTP) ─────────────────────────────────────
def test_parse_response_uses_last_trade_price():
    ...

# ── HTTP-level tests (with respx mock) ───────────────────────────────────────
@pytest.mark.asyncio
@respx.mock
async def test_get_prices_calls_correct_url():
    ...
```
See `backend/tests/market/test_massive.py` for the section-comment pattern.

**Patterns:**
- Start/stop lifecycle explicitly managed in async tests with `try/finally`:
  ```python
  sim = MarketSimulator()
  await sim.start()
  try:
      result = await sim.get_prices(["AAPL"])
      assert ...
  finally:
      await sim.stop()
  ```
- Synchronous tests for pure logic (no I/O): `test_tick_produces_finite_prices()`, `test_change_pct_uptick()`
- Async tests for anything touching the event loop or I/O

## Mocking

**Framework:** `unittest.mock` (stdlib) + `respx` for HTTP

**`unittest.mock` patterns:**
```python
from unittest.mock import AsyncMock, MagicMock

mock_source = MagicMock()
mock_source.get_prices = AsyncMock(return_value={
    "AAPL": make_update("AAPL", 191.0),
})
```
See `backend/tests/market/test_loop.py:73-77`.

**`respx` patterns for HTTP:**
```python
@pytest.mark.asyncio
@respx.mock
async def test_get_prices_calls_correct_url():
    respx.get(SNAPSHOT_URL).mock(
        return_value=httpx.Response(200, json=MOCK_RESPONSE)
    )
    client = make_client()
    await client.start()
    result = await client.get_prices(["AAPL", "MSFT"])
    request = respx.calls.last.request
    assert "apiKey=test-key" in str(request.url)
    await client.stop()
```
See `backend/tests/market/test_massive.py:126-136`.

**Patching asyncio.sleep:**
```python
import unittest.mock
with unittest.mock.patch("asyncio.sleep", side_effect=capturing_sleep):
    task = asyncio.create_task(polling_loop(...))
```
Used to verify back-off timing without waiting real durations. See `backend/tests/market/test_loop.py:173`.

**What to Mock:**
- External HTTP calls (always mock via `respx`)
- `asyncio.sleep` when testing timing/back-off behavior
- The market data source interface (`MarketDataSource`) when testing the polling loop in isolation

**What NOT to Mock:**
- The `PriceCache` — use the real implementation; reset its state with a fixture instead
- Internal class methods — test through the public interface

## Fixtures and Factories

**Test Data:**
```python
# Factory functions (not pytest fixtures) defined at module level in each test file
def make_update(ticker: str, price: float, prev: float | None = None) -> PriceUpdate:
    return PriceUpdate(
        ticker=ticker,
        price=price,
        prev_price=prev if prev is not None else price,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )

def make_client() -> MassiveAPIClient:
    return MassiveAPIClient(api_key="test-key")
```
See `backend/tests/market/test_cache.py:9-15` and `backend/tests/market/test_massive.py:29-30`.

**Module-level mock response constant:**
```python
MOCK_RESPONSE = {
    "status": "OK",
    "count": 2,
    "tickers": [
        {"ticker": "AAPL", "lastTrade": {"p": 190.85, "t": 1703001234000}, ...},
        ...
    ],
}
```
See `backend/tests/market/test_massive.py:11-26`.

**pytest fixtures:**
```python
@pytest.fixture(autouse=True)
def clear_global_cache():
    """Reset the module-level price_cache before each test."""
    cache_module.price_cache._data.clear()
    yield
    cache_module.price_cache._data.clear()
```
Used in `backend/tests/market/test_loop.py:22-27` to reset module-level singleton state. `autouse=True` so it applies to every test in the file without explicit injection.

**Location:**
- No shared `conftest.py` — fixtures defined within individual test files where needed

## Coverage

**Requirements:** No coverage threshold enforced in `pyproject.toml`

**View Coverage:**
```bash
cd backend && uv run pytest --cov=app --cov-report=term-missing
```

## Test Types

**Unit Tests:**
- Scope: Single class or function, no I/O
- Examples: `test_change_pct_uptick()`, `test_tick_produces_finite_prices()`, `test_parse_response_uses_last_trade_price()`
- Use direct class instantiation, no fixtures needed

**Integration Tests (async lifecycle):**
- Scope: A component running with its full async lifecycle (start/stop)
- Examples: `test_get_prices_returns_all_default_tickers()`, `test_polling_loop_calls_source_and_updates_cache()`
- Manage start/stop explicitly; use `try/finally` to ensure cleanup

**HTTP Mock Tests:**
- Scope: HTTP client behavior against mock server responses
- Framework: `respx` decorating test functions with `@respx.mock`
- Examples: `test_get_prices_calls_correct_url()`, `test_get_prices_raises_on_429()`

**No E2E tests present yet** — planned in `test/` directory (Playwright), not yet implemented. See `planning/PLAN.md` section 12 for the planned approach.

## Common Patterns

**Async Testing:**
```python
@pytest.mark.asyncio
async def test_polling_loop_calls_source_and_updates_cache():
    mock_source = MagicMock()
    mock_source.get_prices = AsyncMock(return_value={...})
    task = asyncio.create_task(polling_loop(mock_source, get_tickers, interval_seconds=0.05))
    await asyncio.sleep(0.12)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert mock_source.get_prices.call_count >= 2
```

**Error Testing:**
```python
@pytest.mark.asyncio
@respx.mock
async def test_get_prices_raises_on_429():
    respx.get(SNAPSHOT_URL).mock(return_value=httpx.Response(429, json={"error": "rate limited"}))
    client = make_client()
    await client.start()
    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        await client.get_prices(["AAPL"])
    assert exc_info.value.response.status_code == 429
    await client.stop()
```

**Float Assertion:**
```python
assert sim._prices["FLAT"] == pytest.approx(100.0)
assert abs(u.change_pct - (1.0 / 190.0 * 100)) < 0.001
```

**Safety/Idempotency Tests:**
Every start/stop lifecycle is tested for idempotency and safe no-op behavior:
```python
async def test_stop_without_start_is_safe():
    sim = MarketSimulator()
    await sim.stop()  # Should not raise

async def test_start_idempotent():
    sim = MarketSimulator()
    await sim.start()
    task1 = sim._task
    await sim.start()
    task2 = sim._task
    assert task1 is task2
    await sim.stop()
```

---

*Testing analysis: 2026-05-29*
