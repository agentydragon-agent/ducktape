"""Tests for admin password authentication."""

from http import HTTPStatus

import pytest
from httpx import AsyncClient
from server.models import AdminUser
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture(autouse=True)
async def _override_db(monkeypatch, db_session: AsyncSession):
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _override():
        yield db_session
        await db_session.execute(AdminUser.__table__.delete())
        await db_session.commit()

    monkeypatch.setattr("server.database.get_db_session", _override)


@pytest.mark.asyncio
async def test_admin_login_success(client: AsyncClient, db_session: AsyncSession):
    response = await client.post("/admin/login", data={"password": "gatelet"})
    assert response.status_code == HTTPStatus.FOUND
    assert response.headers["location"] == "/admin/"
    assert "admin_session" in response.cookies


@pytest.mark.asyncio
async def test_admin_login_invalid(client: AsyncClient, db_session: AsyncSession):
    response = await client.post("/admin/login", data={"password": "wrong"})
    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert "Invalid password" in response.text
