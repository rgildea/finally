# FinAlly Code Review

**Date:** 2026-05-29
**Branch:** `my-agent-teams` (diff vs `main`, ~15k-line platform build)
**Method:** Three parallel read-only reviewers (security, backend correctness, frontend quality) coordinated as the `finally-review` agent team.

---

## Consolidated Findings (ranked)

### Critical (1)

**1. Trade execution has no transaction** — `backend/app/services/trading.py:49-56`, `backend/app/db/queries.py:28-35,100-121,127-148`
`execute_trade` does three independent commits (cash, position upsert/delete, trade log) with no `BEGIN`/`COMMIT`. A crash, `CancelledError`, or exception between commits leaves the DB permanently inconsistent: buys debit cash with no position created (money vanishes); sells credit cash without reducing the position (money conjured). **Fix:** wrap all three mutations in one transaction with rollback on failure.

### High (2)

**2. Concurrent-trade race** — `backend/app/services/trading.py:40-56`
The read-modify-write spans six `await` points. A manual REST trade and an LLM auto-trade can interleave: both read `cash=10000`, both "afford" it, cash is debited once, and the `ON CONFLICT DO UPDATE` makes the second position write clobber the first (20 shares bought but position shows 10). The transaction fix (#1) also closes this window since SQLite serializes writes.

**3. Chat stream has no cancellation** — `frontend/components/ChatPanel.tsx:53` + `frontend/lib/chatStream.ts:80-98`
`sendChat` is called without the `AbortSignal` its signature already accepts; the `for(;;) reader.read()` loop never resolves if the backend hangs, so `busy` stays true and the cursor blinks forever with no escape. **Fix:** wire an `AbortController`, abort on unmount.

### Medium (5)

**4. Container runs as root** — `Dockerfile` (no `USER` directive). Any RCE runs as root inside the container with write access to the DB volume. Add a non-root `appuser` and `chown -R appuser /app`.

**5. `MASSIVE_API_KEY` in URL query string** — `backend/app/market/massive.py:67`. Leaks into provider/proxy/`httpx` DEBUG logs. Use an `Authorization: Bearer` header if the API supports it; never run `httpx` at DEBUG in deployed envs.

**6. Ghost positions from float equality** — `backend/app/services/trading.py:103` uses `new_qty == 0`; fractional sells leave `~5e-16` residual rows. Use `new_qty < 1e-9`.

**7. Keyboard-inaccessible rows** — `frontend/components/Watchlist.tsx:104-147` and `frontend/components/PositionsTable.tsx:79-102`: clickable `<li>`/`<tr>` with no `role`/`tabIndex`/`onKeyDown`. Keyboard and screen-reader users cannot select tickers. Add `role="button" tabIndex={0} onKeyDown={...}`.

**8. Raw LLM exception leaked to browser** — `backend/app/llm/service.py:34-35` forwards `f"Chat failed: {exc}"`, exposing provider URL/model/status on auth failures. Log internally, return a generic message.

### Low (2)

**9. Unbounded chat input** — `backend/app/api/chat.py:22` has no `max_length`; lets a user run up token cost on the API key. Add `Field(max_length=4000)`.

**10. Duplicate SVG gradient IDs** — `frontend/components/Sparkline.tsx:50,56` reuse `id="spark-up"`/`"spark-down"` across 10+ instances (invalid HTML; harmless here). Use React 19 `useId()`.

### Suggested fix order
Start with the transaction (#1) — it resolves the Critical and the High race (#2) at once. Then the chat abort (#3), then the four Medium items.

---

## What's solid

- **Security:** SQL is 100% parameterized, no secrets in the image or git, SPA fallback guards path traversal, and LLM trades correctly reuse the same validation as REST.
- **Backend:** price-cache lock usage, background-task lifecycle, portfolio/P&L math, and trade-guard edge cases (insufficient cash, sell-more-than-owned) are correct.
- **Frontend:** EventSource lifecycle/reconnect, SSE frame reassembly, `useFlash` timer cleanup, strong typing (zero `any`), and connection-status text labels (not color-only) are clean, with good unit-test breadth.

---

## Appendix A — Security Review (full)

Scope: `backend/app/config.py`, `api/portfolio.py`, `api/watchlist.py`, `api/chat.py`, `api/stream.py`, `db/queries.py`, `db/connection.py`, `llm/*`, `market/massive.py`, `main.py`, `Dockerfile`, `scripts/*`, `.env.example`, `.gitignore`.

### Clean areas
- **SQL injection** (`queries.py`, `connection.py`) — 100% parameterized, no string concatenation into SQL.
- **Secrets in Docker image** — no `ENV`/`ARG` key values; secrets arrive via `--env-file .env` at runtime.
- **Secrets in VCS** — `.env` gitignored (line 139); `.env.example` placeholders only.
- **`OPENROUTER_API_KEY`** — read from env (`config.py:28`); sent by LiteLLM as a Bearer header, never in a URL.
- **CORS** — no `CORSMiddleware` is correct for same-origin deployment.
- **Path traversal** — `main.py:100-105` resolves candidate and checks it stays under `static_dir`.
- **LLM auto-execution** — `service.py:95` calls the same `execute_trade` as REST; all validation applies equally.
- **Trade `side` validation** — `trading.py:30-31` rejects anything outside `{buy,sell}`.
- **Scripts** — `start_mac.sh` prints only a label for the Massive key, never the value.

### Findings
| Severity | Finding | Location | Confidence |
|---|---|---|---|
| Medium | Process runs as root in container | `Dockerfile` (no `USER`) | 100 |
| Medium | API key exposed in URL query string | `market/massive.py:63-68` | 90 |
| Low-Medium | Raw exception text sent to browser | `llm/service.py:34-35` | 85 |
| Low-Medium | Unbounded chat message to paid LLM | `api/chat.py:22-23` | 85 |

---

## Appendix B — Backend Correctness Review (full)

Scope: `services/trading.py`, `services/portfolio.py`, `services/watchlist.py`, `db/*`, `market/*`, `llm/*`, `api/*`, `main.py`, `config.py`.

### Critical
**1. `execute_trade` has no surrounding transaction** — `trading.py:49-56`, `queries.py:28-35,100-121,127-148` (confidence 90). Three independent commits; any failure between them corrupts cash/position state. `grep BEGIN|TRANSACTION|ROLLBACK` over `app/` returns no matches. Fix: single `BEGIN`/`COMMIT` with rollback.

### High
**2. Race condition in `execute_trade`** — `trading.py:40-56` (confidence 85). Read-modify-write across six `await` points; concurrent manual + LLM trades interleave → double-spend / lost shares. The transaction fix closes the window.

### Medium
**3. Float equality for zero-quantity check** — `trading.py:103` (confidence 80). `new_qty == 0` leaves `~5e-16` ghost positions after fractional sells. Use `new_qty < 1e-9`.

### Clean areas
Price cache (`asyncio.Lock`, shallow-copy on `get_all`); simulator (`_tick`/`get_prices` have no `await`, run atomically); polling loop (`CancelledError` re-raised, 429 back-off, errors logged-and-retried); background-task lifecycle (`main.py:56-62` cancels + gathers with `return_exceptions=True`, `source.stop()`/`close_db()` in `finally`); sell-more-than-owned and insufficient-cash raise `TradeError` before any writes; watchlist in-memory mirror sync; LLM structured-output validation + per-trade error capture; API status codes (400 on validation, 200 on reads); DB lazy init (`CREATE TABLE IF NOT EXISTS`, seed guarded by `SELECT 1`); portfolio math (weighted avg cost, unrealized/total P&L correct).

---

## Appendix C — Frontend Quality Review (full)

Scope: `lib/usePriceStream.ts`, `lib/chatStream.ts`, `lib/useTerminalData.ts`, `lib/useFlash.ts`, `lib/types.ts`, `lib/api.ts`, `lib/format.ts`, all `components/`.

### High
**1. No cancellation for hung chat stream** — `ChatPanel.tsx:53` + `chatStream.ts:80-98` (confidence 83). `sendChat` called without the `AbortSignal` it accepts; unbounded `reader.read()` loop hangs `busy` forever. Fix: `AbortController`, abort on unmount.

**2. `WatchRow` clickable `<li>` keyboard-inaccessible** — `Watchlist.tsx:104-147` (confidence 82). No `role`/`tabIndex`/`onKeyDown`.

**3. `PositionsTable` clickable `<tr>` keyboard-inaccessible** — `PositionsTable.tsx:79-102` (confidence 82). Same pattern.

### Medium (noted)
- **Duplicate SVG ids** — `Sparkline.tsx:50,56`; use `useId()`.
- **History map copied every tick** — `usePriceStream.ts:71` `setHistory({...})` re-renders all rows at ~2 Hz; no `React.memo`. Fine for 10 tickers.

### Clean areas
EventSource lifecycle (`source.close()` on unmount, correct status transitions, no double-fire); `chatStream.ts` SSE parsing (frame reassembly, CRLF, abort suppression); `useFlash` timer cleanup; `types.ts` zero `any`; `api.ts` typed `ApiError`/generics; `format.ts` null/NaN guards; `useTerminalData.ts` `Promise.allSettled` + stable `refresh`; charts `isAnimationActive={false}` + unique gradient ids; connection indicator has text labels; `TradeBar` `aria-label`s; meaningful unit-test breadth.
