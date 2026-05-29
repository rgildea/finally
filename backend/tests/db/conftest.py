"""Fixtures giving each test a fresh, isolated SQLite database."""

import pytest

from app.db import connection


@pytest.fixture
async def db(tmp_path, monkeypatch):
    """Initialize a temp database, yield the connection module, then close it.

    Points ``DB_PATH`` at a temp file and ensures the module-level connection
    is reset before and after so tests do not share state.
    """
    db_file = tmp_path / "test.db"
    monkeypatch.setattr(connection, "DB_PATH", str(db_file))
    monkeypatch.setattr(connection, "_connection", None)

    await connection.init_db()
    yield connection
    await connection.close_db()
