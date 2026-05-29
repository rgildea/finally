"""FastAPI application assembly.

Wires the lifespan (DB init, watchlist load, market source, polling and snapshot
tasks), mounts the API routers, and serves the built frontend static export with
an SPA fallback. A missing static directory is tolerated for local development.
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse

from app import config
from app.api import health, portfolio, stream, watchlist
from app.db import close_db, init_db
from app.market import create_market_data_source
from app.market.loop import polling_loop
from app.services.portfolio import record_snapshot
from app.services.watchlist import get_watched_tickers, load_watchlist

logger = logging.getLogger(__name__)


async def _snapshot_loop() -> None:
    """Record a portfolio value snapshot on the configured interval."""
    while True:
        await asyncio.sleep(config.SNAPSHOT_INTERVAL_SECONDS)
        try:
            await record_snapshot()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Error recording portfolio snapshot")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start background services on boot and tear them down on shutdown."""
    await init_db()
    await load_watchlist()
    source = create_market_data_source()
    await source.start()
    tasks = [
        asyncio.create_task(
            polling_loop(
                source,
                get_tickers=get_watched_tickers,
                interval_seconds=config.POLL_INTERVAL_SECONDS,
            )
        ),
        asyncio.create_task(_snapshot_loop()),
    ]
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await source.stop()
        await close_db()


app = FastAPI(title="FinAlly", lifespan=lifespan)

app.include_router(health.router)
app.include_router(portfolio.router)
app.include_router(watchlist.router)
app.include_router(stream.router)

# The chat router is owned by llm-engineer; include it if present so the app
# still boots before chat lands.
try:
    from app.api import chat

    app.include_router(chat.router)
except Exception:
    logger.warning("Chat router unavailable; skipping /api/chat")


def _mount_static() -> None:
    """Serve the built frontend export at "/", with an SPA fallback.

    No-op when the static directory is absent (local dev without a build), so
    the API still runs. The static mount is added last so API routes win.
    """
    static_dir = config.STATIC_DIR
    if not static_dir.is_dir():
        logger.info("Static dir %s absent; serving API only", static_dir)
        return

    index = static_dir / "index.html"

    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str):
        """Serve a matching static file, else index.html for client routing."""
        if full_path.startswith("api/"):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        candidate = (static_dir / full_path).resolve()
        if (
            full_path
            and candidate.is_file()
            and static_dir.resolve() in candidate.parents
        ):
            return FileResponse(candidate)
        if index.is_file():
            return FileResponse(index)
        return JSONResponse({"detail": "Not Found"}, status_code=404)


_mount_static()
