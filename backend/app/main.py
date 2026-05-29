import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

load_dotenv()

from app.db.database import get_watchlist_tickers, init_db  # noqa: E402
from app.market import create_market_data_source  # noqa: E402
from app.market.loop import polling_loop  # noqa: E402
from app.routers.health import router as health_router  # noqa: E402


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    source = create_market_data_source()
    await source.start()
    task = asyncio.create_task(polling_loop(source, get_watchlist_tickers, 0.5))
    yield
    task.cancel()
    await source.stop()


app = FastAPI(lifespan=lifespan)
app.include_router(health_router)

static_dir = Path(__file__).parent.parent.parent / "frontend" / "out"
if static_dir.exists():
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
