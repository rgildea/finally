"""Central application settings.

Loads the project-root ``.env`` and exposes typed configuration values used
across the backend. Market-data poll cadence and the static asset directory are
derived here so the rest of the app stays free of environment lookups.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# backend/app/config.py -> project root is two parents up from this file.
PROJECT_ROOT = Path(__file__).resolve().parents[2]

load_dotenv(PROJECT_ROOT / ".env")


def _env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes"}


# Database: overridable path, defaulting to db/finally.db under the project root.
DB_PATH = Path(os.getenv("FINALLY_DB_PATH", str(PROJECT_ROOT / "db" / "finally.db")))

# LLM configuration.
LLM_MOCK = _env_bool("LLM_MOCK", False)
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()

# Market data: real Massive feed when a key is present, simulator otherwise.
MASSIVE_API_KEY = os.getenv("MASSIVE_API_KEY", "").strip()
USE_MASSIVE = bool(MASSIVE_API_KEY)

# Poll cadence: fast for the in-process simulator, slow for the rate-limited API.
POLL_INTERVAL_SECONDS = 15.0 if USE_MASSIVE else 0.5

# Portfolio value snapshot cadence (feeds the P&L chart).
SNAPSHOT_INTERVAL_SECONDS = 15.0

# Built frontend export served by FastAPI at "/". Absent during local dev.
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
