---
phase: 1
slug: backend-foundation
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-05-29
---

# Phase 1 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x + pytest-asyncio 0.23 |
| **Config file** | `backend/pyproject.toml` (`[tool.pytest.ini_options]` with `asyncio_mode = "auto"`) |
| **Quick run command** | `cd backend && uv run --group dev pytest tests/test_db.py tests/test_app.py -x -q` |
| **Full suite command** | `cd backend && uv run --group dev pytest -q` |
| **Estimated runtime** | ~10 seconds |

---

## Sampling Rate

- **After every task commit:** Run `cd backend && uv run --group dev pytest tests/test_db.py tests/test_app.py -x -q`
- **After every plan wave:** Run `cd backend && uv run --group dev pytest -q`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 1-01-01 | 01 | 1 | DB-01 | — | N/A | unit | `cd backend && uv run --group dev pytest tests/test_db.py::test_init_creates_tables -x` | ❌ W0 | ⬜ pending |
| 1-01-02 | 01 | 1 | DB-01 | — | N/A | unit | `cd backend && uv run --group dev pytest tests/test_db.py::test_init_idempotent -x` | ❌ W0 | ⬜ pending |
| 1-01-03 | 01 | 1 | DB-02 | — | N/A | unit | `cd backend && uv run --group dev pytest tests/test_db.py::test_all_tables_exist -x` | ❌ W0 | ⬜ pending |
| 1-01-04 | 01 | 1 | DB-03 | — | N/A | unit | `cd backend && uv run --group dev pytest tests/test_db.py::test_seed_data -x` | ❌ W0 | ⬜ pending |
| 1-01-05 | 01 | 1 | DB-03 | — | N/A | unit | `cd backend && uv run --group dev pytest tests/test_db.py::test_seed_idempotent -x` | ❌ W0 | ⬜ pending |
| 1-02-01 | 02 | 2 | APP-03 | T-1-01 | Health returns `{"status":"ok"}` only — no stack traces or version info | unit | `cd backend && uv run --group dev pytest tests/test_app.py::test_health_endpoint -x` | ❌ W0 | ⬜ pending |
| 1-02-02 | 02 | 2 | APP-01 | — | N/A | integration | `cd backend && uv run --group dev pytest tests/test_app.py::test_lifespan_startup -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `backend/tests/test_db.py` — stubs for DB-01, DB-02, DB-03
- [ ] `backend/tests/test_app.py` — stubs for APP-01, APP-03 (uses `httpx.AsyncClient` with `ASGITransport`)
- [ ] No new framework install needed — pytest-asyncio already in dev group

*Existing 59-test market data suite must remain green through all waves.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Market data polling loop populates price cache | APP-01 | Requires running app + time to elapse | `cd backend && uv run uvicorn app.main:app` — after startup, `curl http://localhost:8000/api/health` and observe logs for polling activity |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
