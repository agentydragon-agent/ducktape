from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Optional

from fastapi import (
    APIRouter,
    Cookie,
    Depends,
    Form,
    HTTPException,
    Request,
    Response,
    status,
)
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi_csrf_protect import CsrfProtect
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database import get_db_session
from ..models import AdminSession, AuthKey
from ..security import verify_password
from ..shared import templates

router = APIRouter(tags=["admin"])


class _CsrfSettings(BaseModel):
    secret_key: str = settings.security.csrf_secret


@CsrfProtect.load_config
def _get_csrf_config():
    return _CsrfSettings()


SESSION_DURATION = timedelta(hours=1)


async def _get_admin_session(
    session_token: Optional[str] = Cookie(None, alias="admin_session"),
    db_session: AsyncSession = Depends(get_db_session),
) -> AdminSession:
    if not session_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    stmt = select(AdminSession).where(AdminSession.session_token == session_token)
    admin_session = (await db_session.execute(stmt)).scalar_one_or_none()
    if not admin_session or admin_session.expires_at <= datetime.now():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    return admin_session


@router.post("/admin/login", response_class=HTMLResponse)
async def login(
    request: Request,
    password: str = Form(...),
    db_session: AsyncSession = Depends(get_db_session),
    csrf_protect: CsrfProtect = Depends(),
) -> Response:
    await csrf_protect.validate_csrf(request)
    if not verify_password(password, settings.admin.password_hash):
        return templates.TemplateResponse(
            "public.html",
            {
                "request": request,
                "header": "Gatelet",
                "show_admin_login": True,
                "login_error": "Invalid password",
                "llm_instructions": "To access this service as an LLM, follow the instructions provided by your user.",
            },
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    session = AdminSession(
        session_token=uuid.uuid4().hex,
        created_at=datetime.now(),
        expires_at=datetime.now() + SESSION_DURATION,
    )
    db_session.add(session)
    await db_session.flush()
    response = RedirectResponse("/admin/", status_code=302)
    response.set_cookie("admin_session", session.session_token, httponly=True)
    token, signed = csrf_protect.generate_csrf_tokens()
    csrf_protect.set_csrf_cookie(signed, response)
    return response


@router.get("/admin/", response_class=HTMLResponse)
async def admin_root(
    request: Request, admin_session: AdminSession = Depends(_get_admin_session)
) -> HTMLResponse:
    return templates.TemplateResponse("admin_index.html", {"request": request})


@router.get("/admin/keys/", response_class=HTMLResponse)
async def list_keys(
    request: Request,
    admin_session: AdminSession = Depends(_get_admin_session),
    db_session: AsyncSession = Depends(get_db_session),
    csrf_protect: CsrfProtect = Depends(),
) -> HTMLResponse:
    keys = (
        (await db_session.execute(select(AuthKey).order_by(AuthKey.id))).scalars().all()
    )
    token, signed = csrf_protect.generate_csrf_tokens()
    response = templates.TemplateResponse(
        "admin_keys.html",
        {"request": request, "keys": keys, "csrf_token": token},
    )
    csrf_protect.set_csrf_cookie(signed, response)
    return response


@router.get("/admin/keys/new", response_class=HTMLResponse)
async def new_key_form(
    request: Request,
    admin_session: AdminSession = Depends(_get_admin_session),
    csrf_protect: CsrfProtect = Depends(),
) -> HTMLResponse:
    token, signed = csrf_protect.generate_csrf_tokens()
    response = templates.TemplateResponse(
        "admin_key_new.html", {"request": request, "csrf_token": token}
    )
    csrf_protect.set_csrf_cookie(signed, response)
    return response


@router.post("/admin/keys/new", response_class=HTMLResponse)
async def create_key(
    request: Request,
    description: str = Form(""),
    admin_session: AdminSession = Depends(_get_admin_session),
    db_session: AsyncSession = Depends(get_db_session),
    csrf_protect: CsrfProtect = Depends(),
) -> HTMLResponse:
    await csrf_protect.validate_csrf(request)
    key = AuthKey(
        key_value=uuid.uuid4().hex,
        description=description or None,
        created_at=datetime.now(),
    )
    db_session.add(key)
    await db_session.flush()
    token, signed = csrf_protect.generate_csrf_tokens()
    response = templates.TemplateResponse(
        "admin_key_created.html",
        {"request": request, "key": key, "csrf_token": token},
    )
    csrf_protect.set_csrf_cookie(signed, response)
    return response


@router.post("/admin/keys/{key_id}/revoke", response_class=RedirectResponse)
async def revoke_key(
    key_id: int,
    request: Request,
    admin_session: AdminSession = Depends(_get_admin_session),
    db_session: AsyncSession = Depends(get_db_session),
    csrf_protect: CsrfProtect = Depends(),
) -> Response:
    await csrf_protect.validate_csrf(request)
    stmt = select(AuthKey).where(AuthKey.id == key_id)
    key = (await db_session.execute(stmt)).scalar_one_or_none()
    if key and not key.revoked_at:
        key.revoked_at = datetime.now()
        await db_session.flush()
    response = RedirectResponse("/admin/keys/", status_code=302)
    return response
