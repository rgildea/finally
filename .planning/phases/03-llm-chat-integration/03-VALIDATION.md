---
phase: 3
slug: llm-chat-integration
status: ready
nyquist_compliant: true
wave_0_complete: true
created: 2026-05-30
---

# Phase 3 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (async) |
| **Config file** | `backend/pyproject.toml` (pytest section) |
| **Quick run command** | `cd backend && uv run pytest tests/test_chat.py -x -q` |
| **Full suite command** | `cd backend && uv run pytest tests/ -x -q` |
| **Estimated runtime** | ~10 seconds |

---

## Sampling Rate

- **After every task commit:** Run `cd backend && uv run pytest tests/test_chat.py -x -q`
- **After every plan wave:** Run `cd backend && uv run pytest tests/ -x -q`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** ~30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 03-01-T0 | 01 | 1 | TEST-03 | — | N/A (scaffold) | wave0 | `cd backend && uv run python -c "import litellm" && uv run pytest tests/test_chat.py --collect-only -q` | ✅ W0 | ⬜ pending |
| 03-01-T1 | 01 | 1 | CHAT-02 | — | Context builder only reads DB; no external calls | unit | `cd backend && uv run pytest tests/test_chat.py::test_load_recent_history_chronological tests/test_chat.py::test_build_portfolio_context_includes_cash -x -q` | ✅ W0 | ⬜ pending |
| 03-01-T2 | 01 | 1 | CHAT-03, CHAT-06, TEST-03 | T-03-01 | Mock mode never makes network calls; malformed JSON returns graceful error ChatResponse | unit | `cd backend && uv run pytest tests/test_chat.py::test_mock_mode tests/test_chat.py::test_parse_valid_response tests/test_chat.py::test_parse_malformed_response -x -q` | ✅ W0 | ⬜ pending |
| 03-02-T1 | 02 | 2 | CHAT-01, CHAT-04, CHAT-05 | T-03-02, T-03-03 | SSE response streams; side effects execute before first yield; messages persisted | integration | `cd backend && uv run pytest tests/test_chat.py::test_chat_streams_response tests/test_chat.py::test_chat_persists_messages tests/test_chat.py::test_chat_auto_executes_trade -x -q` | ✅ W0 | ⬜ pending |
| 03-02-T2 | 02 | 2 | CHAT-01 | — | Chat route registered and reachable | integration | `cd backend && uv run pytest tests/ -x -q` | ✅ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [x] `backend/tests/test_chat.py` — stub file created with all test function stubs (03-01 Task 0)
- [x] `backend/app/chat/__init__.py` — package marker (03-01 Task 0)
- [x] `litellm` added via `uv add litellm` (03-01 Task 0)

*Wave 0 is fully handled by 03-01 Task 0.*

---

## Manual-Only Verifications

All phase behaviors have automated verification.

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 30s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
