"""Tests for challenge-response authentication endpoints."""

import asyncio
import html
import re
import subprocess
import sys
import textwrap
from datetime import datetime, timedelta
from http import HTTPStatus

import pytest_bazel
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from x.gatelet.server.config import Settings
from x.gatelet.server.endpoints.challenge import compute_correct_option
from x.gatelet.server.models import AuthCRSession, AuthKey, AuthNonce


async def test_start_challenge_creates_nonce(client: AsyncClient, db_session: AsyncSession, test_auth_key: AuthKey):
    response = await client.get(f"/cr/{test_auth_key.id}")
    assert response.status_code == HTTPStatus.OK
    nonce = (await db_session.execute(select(AuthNonce).order_by(AuthNonce.id.desc()))).scalars().first()
    assert nonce is not None
    assert nonce.is_valid


async def test_answer_challenge_success(
    client: AsyncClient, db_session: AsyncSession, test_auth_key: AuthKey, test_settings: Settings
):
    # test_settings fixture provides explicit test config (num_options=16)
    await client.get(f"/cr/{test_auth_key.id}")
    nonce = (await db_session.execute(select(AuthNonce).order_by(AuthNonce.id.desc()))).scalars().first()
    answer = str(
        compute_correct_option(
            test_auth_key.key_value, nonce.nonce_value, test_settings.auth.challenge_response.num_options
        )
    )
    response = await client.get(f"/cr/{test_auth_key.id}/{nonce.nonce_value}/{answer}")
    assert response.status_code == HTTPStatus.FOUND
    query = select(AuthCRSession).where(AuthCRSession.auth_key_id == test_auth_key.id)
    session = (await db_session.execute(query)).scalar_one()
    assert session.auth_key_id == test_auth_key.id


async def test_session_extension(client: AsyncClient, db_session: AsyncSession, test_auth_session: AuthCRSession):
    original_exp = datetime.now() + timedelta(seconds=1)
    test_auth_session.expires_at = original_exp
    await db_session.flush()
    await client.get(f"/s/{test_auth_session.session_token}/")
    await db_session.refresh(test_auth_session)
    assert test_auth_session.expires_at > original_exp


async def test_challenge_page_instructions_compute_the_accepted_option(
    client: AsyncClient, db_session: AsyncSession, test_auth_key: AuthKey, test_settings: Settings
):
    response = await client.get(f"/cr/{test_auth_key.id}")
    assert response.status_code == HTTPStatus.OK

    nonce = (await db_session.execute(select(AuthNonce).order_by(AuthNonce.id.desc()))).scalars().first()
    assert nonce is not None
    code_match = re.search(r"<pre>\s*(.*?)</pre", response.text, re.DOTALL)
    assert code_match is not None
    instructions = textwrap.dedent(html.unescape(code_match.group(1)))
    completed = await asyncio.to_thread(
        subprocess.run,
        [sys.executable, "-c", f"key = {test_auth_key.key_value!r}\n{instructions}"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert completed.stdout.strip() == str(
        compute_correct_option(
            test_auth_key.key_value, nonce.nonce_value, test_settings.auth.challenge_response.num_options
        )
    )


if __name__ == "__main__":
    pytest_bazel.main()
