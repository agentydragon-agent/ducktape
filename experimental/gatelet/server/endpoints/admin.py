from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Cookie, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db_session
from ..models import AdminSession, AdminUser
from ..shared import templates

router = APIRouter(tags=["admin"])

SESSION_DURATION = timedelta(hours=1)


def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


async def _get_admin(db_session: AsyncSession) -> AdminUser:
    admin = (await db_session.execute(select(AdminUser))).scalar_one_or_none()
    if not admin:
        admin = AdminUser(password_hash=_hash_password("gatelet"))
        db_session.add(admin)
        await db_session.flush()
    return admin


async def _get_admin_session(
    session_token: Optional[str] = Cookie(None),
    db_session: AsyncSession = Depends(get_db_session),
) -> AdminSession:
    if not session_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    stmt = select(AdminSession).where(AdminSession.session_token == session_token)
    admin_session = (await db_session.execute(stmt)).scalar_one_or_none()
    if not admin_session or admin_session.expires_at <= datetime.now():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    return admin_session


@router.get("/admin/login", response_class=HTMLResponse)
async def login_form(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        "admin_login.html", {"request": request, "error": None}
    )


@router.post("/admin/login", response_class=HTMLResponse)
async def login(
    request: Request,
    password: str = Form(...),
    db_session: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    admin = await _get_admin(db_session)
    if admin.password_hash != _hash_password(password):
        return templates.TemplateResponse(
            "admin_login.html",
            {"request": request, "error": "Invalid password"},
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
    return response


@router.get("/admin/", response_class=HTMLResponse)
async def admin_root(
    request: Request, admin_session: AdminSession = Depends(_get_admin_session)
) -> HTMLResponse:
    return templates.TemplateResponse("admin_index.html", {"request": request})
