"""Challenge-response authentication endpoints."""

import hashlib
import random
import uuid
from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database import get_db_session
from ..models import AuthKey, AuthNonce, AuthCRSession
from ..shared import templates
from ..auth.handlers import AuthHandlerError

router = APIRouter(tags=["auth"])


async def _validate_key(key_id: int, db_session: AsyncSession) -> AuthKey:
    stmt = select(AuthKey).where(AuthKey.id == key_id)
    result = await db_session.execute(stmt)
    key = result.scalar_one_or_none()
    if not key or not key.is_valid(settings.auth.key_in_url.key_validity):
        raise AuthHandlerError()
    return key


def _create_options(correct: str) -> List[str]:
    options = {correct}
    while len(options) < settings.auth.challenge_response.num_options:
        options.add(random.randint(0, 255).to_bytes(1, "big").hex())
    return sorted(options)


async def _new_challenge(key: AuthKey, db_session: AsyncSession):
    nonce_value = uuid.uuid4().hex
    nonce = AuthNonce(
        nonce_value=nonce_value,
        expires_at=datetime.now() + settings.auth.challenge_response.nonce_validity,
    )
    db_session.add(nonce)
    await db_session.flush()

    digest = hashlib.sha256(f"{key.key_value}{nonce_value}".encode()).hexdigest()
    correct = digest[-2:]
    options = _create_options(correct)
    return nonce, correct, options


@router.get("/cr/{key_id}", response_class=HTMLResponse)
async def start_challenge(
    key_id: int, request: Request, db_session: AsyncSession = Depends(get_db_session)
):
    key = await _validate_key(key_id, db_session)
    nonce, _, options = await _new_challenge(key, db_session)
    return templates.TemplateResponse(
        "challenge.html",
        {
            "request": request,
            "key_id": key.id,
            "nonce_value": nonce.nonce_value,
            "options": options,
            "message": None,
        },
    )


async def _render_new_challenge(
    request: Request,
    key: AuthKey,
    db_session: AsyncSession,
    message: str,
):
    nonce, _, options = await _new_challenge(key, db_session)
    return templates.TemplateResponse(
        "challenge.html",
        {
            "request": request,
            "key_id": key.id,
            "nonce_value": nonce.nonce_value,
            "options": options,
            "message": message,
        },
    )


@router.get("/cr/{key_id}/{nonce_value}/{answer}", response_class=HTMLResponse)
async def answer_challenge(
    key_id: int,
    nonce_value: str,
    answer: str,
    request: Request,
    db_session: AsyncSession = Depends(get_db_session),
):
    key = await _validate_key(key_id, db_session)
    stmt = select(AuthNonce).where(AuthNonce.nonce_value == nonce_value)
    nonce = (await db_session.execute(stmt)).scalar_one_or_none()
    if not nonce or not nonce.is_valid:
        return await _render_new_challenge(
            request, key, db_session, "Invalid or expired challenge"
        )

    nonce.used_at = datetime.now()
    await db_session.flush()

    digest = hashlib.sha256(f"{key.key_value}{nonce_value}".encode()).hexdigest()
    correct = digest[-2:]
    if answer.lower() != correct:
        return await _render_new_challenge(request, key, db_session, "Incorrect answer")

    now = datetime.now()
    session = AuthCRSession(
        session_token=uuid.uuid4().hex,
        auth_key_id=key.id,
        created_at=now,
        expires_at=now + settings.auth.challenge_response.session_extension,
        last_activity_at=now,
    )
    db_session.add(session)
    await db_session.flush()
    url = f"/s/{session.session_token}/"
    return RedirectResponse(url, status_code=302)
