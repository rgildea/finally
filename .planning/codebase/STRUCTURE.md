# Codebase Structure

**Analysis Date:** 2026-05-29

## Directory Layout

```
finally/                          # Project root
├── backend/                      # FastAPI uv project (Python)
│   ├── app/                      # Application package
│   │   ├── __init__.py
│   │   └── market/               # Market data subsystem (COMPLETE)
│   │       ├── __init__.py       # Factory: create_market_data_source()
│   │       ├── interface.py      # ABC + PriceUpdate model
│   │       ├── cache.py          # PriceCache singleton
│   │       ├── loop.py           # polling_loop() asyncio task
│   │       ├── simulator.py      # MarketSimulator (GBM)
│   │       └── massive.py        # MassiveAPIClient (REST)
│   ├── tests/                    # pytest test suite
│   │   ├── __init__.py
│   │   └── market/               # Market data tests (59 passing)
│   │       ├── __init__.py
│   │       ├── test_cache.py
│   │       ├── test_interface.py
│   │       ├── test_loop.py
│   │       ├── test_massive.py
│   │       └── test_simulator.py
│   ├── demo.py                   # Rich terminal demo (dev tool only)
│   ├── pyproject.toml            # uv project config + pytest config
│   └── uv.lock                   # Lockfile (committed)
├── frontend/                     # Next.js TypeScript project (NOT YET CREATED)
├── db/                           # SQLite volume mount target
│   └── .gitkeep                  # Keeps dir in repo; finally.db is gitignored
├── planning/                     # Project documentation for agents
│   ├── PLAN.md                   # Master specification
│   ├── MARKET_DATA_SUMMARY.md    # Market data component summary
│   └── archive/                  # Historical design docs
│       ├── MARKET_DATA_DESIGN.md
│       ├── MARKET_DATA_REVIEW.md
│       ├── MARKET_INTERFACE.md
│       ├── MARKET_SIMULATOR.md
│       └── MASSIVE_API.md
├── .planning/                    # GSD agent planning artifacts
│   └── codebase/                 # Codebase map documents (this file)
├── .claude/                      # Claude/GSD tooling
│   ├── skills/
│   │   └── cerebras/             # LiteLLM+OpenRouter+Cerebras skill
│   │       └── SKILL.md
│   └── agents/                   # Agent definitions
├── .github/
│   └── workflows/
│       ├── claude.yml            # Claude Code GitHub Action
│       └── claude-code-review.yml # Auto PR review
├── scripts/                      # Docker start/stop scripts (NOT YET CREATED)
├── test/                         # Playwright E2E tests (NOT YET CREATED)
├── Dockerfile                    # Multi-stage build (NOT YET CREATED)
├── docker-compose.yml            # Optional convenience wrapper (NOT YET CREATED)
├── CLAUDE.md                     # Project Claude instructions
├── README.md                     # Project overview
├── .env                          # Secrets — gitignored, never commit
└── .gitignore
```

## Directory Purposes

**`backend/app/market/`:**
- Purpose: Complete market data subsystem — the only implemented backend code
- Contains: ABC, two data-source implementations, in-memory price cache, polling task, factory
- Key files: `interface.py` (contract), `cache.py` (singleton), `__init__.py` (factory)

**`backend/tests/market/`:**
- Purpose: Full pytest suite for the market data subsystem
- Contains: 59 tests across 5 files covering all modules
- Key files: `test_simulator.py`, `test_massive.py`, `test_loop.py`

**`db/`:**
- Purpose: Runtime volume mount point for SQLite database
- Contains: `.gitkeep` only; `finally.db` is created at runtime and gitignored
- Generated: Yes (at runtime by the backend)
- Committed: No (`finally.db` is gitignored)

**`planning/`:**
- Purpose: Human- and agent-readable project documentation
- Contains: Master spec (`PLAN.md`), component summaries, design archives
- Key files: `PLAN.md` (authoritative spec), `MARKET_DATA_SUMMARY.md`

**`.planning/codebase/`:**
- Purpose: GSD-generated codebase map documents
- Contains: ARCHITECTURE.md, STRUCTURE.md, and future analysis docs
- Generated: Yes (by GSD map-codebase command)
- Committed: Yes

**`.claude/skills/cerebras/`:**
- Purpose: Project skill defining LiteLLM + OpenRouter + Cerebras integration pattern
- Key file: `SKILL.md` — must be read before implementing any LLM calls

## Key File Locations

**Entry Points:**
- `backend/app/market/__init__.py`: Factory `create_market_data_source()` — start here for market data
- `backend/demo.py`: Standalone Rich terminal demo of the simulator

**Configuration:**
- `backend/pyproject.toml`: Python dependencies, pytest config, build system
- `backend/uv.lock`: Pinned dependency lockfile (committed)
- `.env`: Runtime secrets (`OPENROUTER_API_KEY`, `MASSIVE_API_KEY`) — gitignored

**Core Logic:**
- `backend/app/market/interface.py`: `PriceUpdate` model and `MarketDataSource` ABC
- `backend/app/market/cache.py`: `PriceCache` singleton (`price_cache`)
- `backend/app/market/loop.py`: `polling_loop()` — the bridge between source and cache
- `backend/app/market/simulator.py`: `MarketSimulator` — GBM with sector correlations
- `backend/app/market/massive.py`: `MassiveAPIClient` — httpx REST client

**Testing:**
- `backend/tests/market/`: All 59 market data tests
- `backend/pyproject.toml`: `[tool.pytest.ini_options]` — `asyncio_mode = "auto"`, `testpaths = ["tests"]`

**Planning (read before implementing):**
- `planning/PLAN.md`: Full project specification including API contracts, DB schema, UI design
- `planning/MARKET_DATA_SUMMARY.md`: Market data architecture summary with usage examples
- `.claude/skills/cerebras/SKILL.md`: Required reading before writing any LLM call code

## Naming Conventions

**Files:**
- Python modules: `snake_case.py` (e.g., `interface.py`, `cache.py`, `simulator.py`)
- Test files: `test_<module>.py` co-located under `tests/<subsystem>/`
- Planning docs: `UPPER_CASE_WITH_UNDERSCORES.md`

**Directories:**
- Python packages: `snake_case/` with `__init__.py`
- Subsystem grouping under `app/`: e.g., `market/`, future `api/`, `db/`
- Test mirror: `tests/<subsystem>/` mirrors `app/<subsystem>/`

**Python:**
- Classes: `PascalCase` (e.g., `MarketSimulator`, `PriceCache`, `MassiveAPIClient`)
- Functions/methods: `snake_case` (e.g., `get_prices`, `polling_loop`, `update_many`)
- Constants: `UPPER_SNAKE_CASE` (e.g., `MASSIVE_BASE_URL`, `SNAPSHOT_PATH`)
- Private helpers: leading underscore (e.g., `_merge_with_prev`, `_tick`, `_DEFAULT_TICKERS`)
- Module singletons: `snake_case` (e.g., `price_cache`)

## Where to Add New Code

**New backend API route (e.g., portfolio, watchlist, chat):**
- Create router module: `backend/app/<subsystem>.py` or `backend/app/<subsystem>/`
- Register with FastAPI app: `backend/app/main.py` (to be created)
- Unit tests: `backend/tests/<subsystem>/test_<module>.py`

**New market data source implementation:**
- Implement: `backend/app/market/<name>.py` — subclass `MarketDataSource`
- Export: Add to `backend/app/market/__init__.py` `__all__` and update `create_market_data_source()`
- Tests: `backend/tests/market/test_<name>.py` — follow `test_massive.py` pattern

**New Pydantic model (request/response schema):**
- Place with the router or subsystem it belongs to: `backend/app/<subsystem>/models.py` or inline in module
- Follow `PriceUpdate` pattern: `BaseModel` with explicit field types; use `computed_field` for derived values

**SQLite schema (planned):**
- Schema SQL: `backend/db/schema.sql` (to be created per PLAN.md)
- Seed data logic: `backend/db/seed.py` (to be created)
- Lazy init: called from FastAPI lifespan handler in `backend/app/main.py`

**Frontend components (planned):**
- All frontend code: `frontend/` (Next.js TypeScript project, not yet created)
- Follow plan: `planning/PLAN.md` section 10 for layout and component requirements

**E2E tests (planned):**
- Location: `test/` (Playwright, not yet created)
- Infrastructure: `test/docker-compose.test.yml`

## Special Directories

**`db/`:**
- Purpose: Docker volume mount target for SQLite file
- Generated: `db/finally.db` created at runtime
- Committed: Only `.gitkeep`; `finally.db` is in `.gitignore`

**`.planning/`:**
- Purpose: GSD workflow planning artifacts
- Generated: Yes, by GSD commands
- Committed: Yes (part of the dev workflow)

**`planning/archive/`:**
- Purpose: Historical design documents from completed phases
- Committed: Yes (reference only; `MARKET_DATA_SUMMARY.md` is the live summary)

---

*Structure analysis: 2026-05-29*
