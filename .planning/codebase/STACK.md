# Technology Stack

**Analysis Date:** 2026-05-29

## Languages

**Primary:**
- Python 3.12+ — Backend (FastAPI application, market data, all server logic)

**Secondary:**
- TypeScript — Frontend (planned Next.js static export; not yet scaffolded)

## Runtime

**Environment:**
- Python 3.12+ (lockfile pinned; tested on 3.13.2)

**Package Manager:**
- uv — manages Python dependencies for `backend/`
- Lockfile: `backend/uv.lock` (present, committed)

## Frameworks

**Core:**
- FastAPI 0.136.3 — REST API, SSE streaming, static file serving
- Starlette 1.1.0 — ASGI foundation under FastAPI
- uvicorn 0.48.0 (with `[standard]` extras: uvloop, websockets, httptools) — ASGI server

**Data Validation:**
- Pydantic 2.13.4 — Models, structured outputs, computed fields

**HTTP Client:**
- httpx 0.28.1 — Async HTTP client for Massive API calls

**Testing:**
- pytest 9.0.3 — Test runner
- pytest-asyncio 1.3.0 — Async test support (configured `asyncio_mode = "auto"`)
- respx 0.23.1 — httpx request mocking

**Build/Dev:**
- ruff 0.15.14 — Linting and formatting
- rich 15.0.0 — Terminal UI (used in `backend/demo.py` demo script)

## Key Dependencies

**Critical:**
- `fastapi>=0.111` — Core web framework; owns all routing and SSE
- `pydantic>=2.7` — Structured outputs for LLM responses and all API models
- `uvicorn[standard]>=0.29` — Production ASGI server
- `httpx>=0.27` — Async HTTP for Massive API polling
- `python-dotenv>=1.0` — Reads `.env` at the project root into the environment

**Infrastructure:**
- `anyio 4.13.0` — Async concurrency primitives (transitive via FastAPI)
- `uvloop 0.22.1` — High-performance event loop (included via uvicorn `[standard]`)
- `websockets 16.0` — Included via uvicorn `[standard]` (not used directly)

**Planned (not yet added):**
- `litellm` — LLM calls via OpenRouter/Cerebras (required per `cerebras-inference` skill)
- Node.js / Next.js — Frontend static export (not yet scaffolded)

## Configuration

**Environment:**
- `.env` file at project root (gitignored) — loaded by `python-dotenv`
- Key variables:
  - `MASSIVE_API_KEY` — optional; enables real market data if set and non-empty
  - `OPENROUTER_API_KEY` — required for LLM chat (not yet wired in backend)
  - `LLM_MOCK` — set `"true"` for deterministic mock LLM responses in tests

**Build:**
- `backend/pyproject.toml` — project metadata, dependencies, pytest config, hatchling build
- `backend/uv.lock` — fully pinned lockfile

**Test Config (in pyproject.toml):**
```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

## Platform Requirements

**Development:**
- Python 3.12+ with uv installed
- Run: `cd backend && uv run --group dev pytest`
- Demo: `cd backend && uv run --group dev python demo.py`

**Production:**
- Single Docker container, port 8000
- SQLite database at `/app/db/finally.db` (volume-mounted)
- Multi-stage Dockerfile (Node build stage + Python runtime stage) — not yet written
- Target deployment: Docker on local machine, optionally AWS App Runner or Render

---

*Stack analysis: 2026-05-29*
