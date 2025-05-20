"""Tests for admin password authentication."""

import pytest
import re
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture(autouse=True)
async def _override_db(monkeypatch, db_session: AsyncSession):
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _override():
        yield db_session
        await db_session.execute("DELETE FROM admin_sessions")
        await db_session.commit()

    monkeypatch.setattr("server.database.get_db_session", _override)


@pytest.mark.asyncio
async def test_admin_login_success(client: AsyncClient, db_session: AsyncSession):
    home = await client.get("/")
    m = re.search(r'name="csrf_token" value="([^"]+)"', home.text)
    assert m
    token = m.group(1)
    response = await client.post(
        "/admin/login",
        data={"password": "gatelet", "csrf_token": token},
        headers={"X-CSRF-Token": token},
    )
    assert response.status_code == 302  # noqa: PLR2004
    assert response.headers["location"] == "/admin/"
    assert "admin_session" in response.cookies


@pytest.mark.asyncio
async def test_admin_login_invalid(client: AsyncClient, db_session: AsyncSession):
    home = await client.get("/")
    m = re.search(r'name="csrf_token" value="([^"]+)"', home.text)
    assert m
    token = m.group(1)
    response = await client.post(
        "/admin/login",
        data={"password": "wrong", "csrf_token": token},
        headers={"X-CSRF-Token": token},
    )
    assert response.status_code == 401  # noqa: PLR2004
    assert "Invalid password" in response.text
