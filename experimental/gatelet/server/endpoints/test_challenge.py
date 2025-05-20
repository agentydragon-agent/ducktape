"""Tests for challenge-response authentication endpoints."""

import hashlib
from datetime import datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.models import AuthCRSession, AuthNonce, AuthKey  # type: ignore[import]


@pytest.fixture(autouse=True)
def _override_get_db(monkeypatch, db_session: AsyncSession):
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _override():
        yield db_session

    monkeypatch.setattr("server.database.get_db_session", _override)


@pytest.mark.asyncio
async def test_start_challenge_creates_nonce(
    client: AsyncClient, db_session: AsyncSession, test_auth_key: AuthKey
):
    response = await client.get(f"/cr/{test_auth_key.id}")
    assert response.status_code == 200
    nonce = (
        (await db_session.execute(select(AuthNonce).order_by(AuthNonce.id.desc())))
        .scalars()
        .first()
    )
    assert nonce and nonce.is_valid


@pytest.mark.asyncio
async def test_answer_challenge_success(
    client: AsyncClient, db_session: AsyncSession, test_auth_key: AuthKey
):
    await client.get(f"/cr/{test_auth_key.id}")
    nonce = (
        (await db_session.execute(select(AuthNonce).order_by(AuthNonce.id.desc())))
        .scalars()
        .first()
    )
    digest = hashlib.sha256(
        f"{test_auth_key.key_value}{nonce.nonce_value}".encode()
    ).hexdigest()
    answer = digest[-2:]
    response = await client.get(f"/cr/{test_auth_key.id}/{nonce.nonce_value}/{answer}")
    assert response.status_code == 302
    session = (await db_session.execute(select(AuthCRSession))).scalar_one()
    assert session.auth_key_id == test_auth_key.id


@pytest.mark.asyncio
async def test_session_extension(
    client: AsyncClient, db_session: AsyncSession, test_auth_session: AuthCRSession
):
    original_exp = datetime.now() + timedelta(seconds=1)
    test_auth_session.expires_at = original_exp
    await db_session.flush()
    await client.get(f"/s/{test_auth_session.session_token}/")
    await db_session.refresh(test_auth_session)
    assert test_auth_session.expires_at > original_exp
