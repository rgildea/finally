from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

import app.main as main_module
from app.main import app


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    import app.db.database as db_module
    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "test.db")


async def test_health_endpoint():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_lifespan_startup():
    mock_source = MagicMock()
    mock_source.start = AsyncMock()
    mock_source.stop = AsyncMock()
    mock_source.get_prices = AsyncMock(return_value={})

    with (
        patch.object(main_module, "create_market_data_source", return_value=mock_source),
        patch.object(main_module, "init_db") as mock_init_db,
    ):
        async with app.router.lifespan_context(app):
            pass

    mock_init_db.assert_called_once()
    mock_source.start.assert_awaited_once()
    mock_source.stop.assert_awaited_once()


async def test_static_mount_absent_ok():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/health")
    assert response.status_code == 200
