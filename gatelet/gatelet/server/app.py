"""FastAPI application for Gatelet server."""

import logging
from datetime import datetime
from collections.abc import Callable

from fastapi import Cookie, Depends, FastAPI, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi_csrf_protect import CsrfProtect
from sqlalchemy import select

from .auth.dependencies import (
    Auth,
    get_admin_auth_with_context,
    get_key_path_auth_with_context,
    get_session_auth_with_context,
)
from .auth.handlers import AuthHandlerError
from .auth.webhook_auth import AuthError
from .config import settings
from .database import get_db_session
from .endpoints import (
    activitywatch,
    admin,
    challenge,
    homeassistant,
    webhook_receive,
    webhook_view,
)
from .endpoints.homeassistant import fetch_states
from .endpoints.webhook_view import get_latest_payloads
from .models import AdminSession
from .shared import BASE_DIR, templates

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Gatelet",
    description="LLM-friendly API for Home Assistant and webhooks",
)
app.mount(
    "/static",
    StaticFiles(directory=BASE_DIR / "static"),
    name="static",
)

# Include routers
app.include_router(webhook_receive.router)
app.include_router(webhook_view.router)
app.include_router(challenge.router)
app.include_router(admin.router)
app.include_router(homeassistant.router)


# Error handlers
@app.exception_handler(AuthHandlerError)
async def auth_error_handler(request: Request, exc: AuthHandlerError):
    """Handle all auth errors in HTML-friendly way."""
    return templates.TemplateResponse(
        "error.html",
        {
            "request": request,
            "status_code": status.HTTP_401_UNAUTHORIZED,
            "detail": "Authentication failed",
        },
        status_code=status.HTTP_401_UNAUTHORIZED,
    )


@app.exception_handler(AuthError)
async def webhook_auth_error(request: Request, exc: AuthError):
    """Handle webhook auth errors in API-friendly way."""
    return JSONResponse(
        status_code=status.HTTP_401_UNAUTHORIZED,
        content={"detail": "Authentication failed"},
        headers=getattr(exc, "headers", {}),
    )


@app.get("/", response_class=HTMLResponse)
async def root(
    request: Request,
    session: str | None = Cookie(None),
    csrf_protect: CsrfProtect = Depends(),
):
    """Root endpoint with service information and authentication options."""
    # Check if already authenticated via cookie
    if session:
        async with get_db_session() as db_session:
            stmt = select(AdminSession).where(AdminSession.session_token == session)
            admin_session = (await db_session.execute(stmt)).scalar_one_or_none()
            if admin_session and admin_session.expires_at > datetime.now():
                return RedirectResponse("/admin/", status_code=302)

    token, signed = csrf_protect.generate_csrf_tokens()
    response = templates.TemplateResponse(
        "public.html",
        {
            "request": request,
            "header": "Gatelet",
            "show_admin_login": True,
            "llm_instructions": "To access this service as an LLM, follow the instructions provided by your user.",
            "csrf_token": token,
        },
    )
    csrf_protect.set_csrf_cookie(signed, response)
    return response


def register_with_all_auth_methods(
    path: str,
    handler: Callable,
    register_admin: bool = True,
):
    """Register a handler with all available auth methods.

    Args:
        path: URL path to register (without auth prefix)
        handler: Handler function to register
        register_admin: Whether to expose this handler for admin sessions
    """
    # Key in path auth
    if settings.auth.key_in_url.enabled:
        app.add_api_route(
            f"/k/{{key}}{path}",
            handler,
            methods=["GET"],
            response_class=HTMLResponse,
            dependencies=[Depends(get_key_path_auth_with_context)],
        )

    # Challenge-response session auth
    if settings.auth.challenge_response.enabled:
        app.add_api_route(
            f"/s/{{session_token}}{path}",
            handler,
            methods=["GET"],
            response_class=HTMLResponse,
            dependencies=[Depends(get_session_auth_with_context)],
        )

    if register_admin:
        app.add_api_route(
            f"/admin{path}",
            handler,
            methods=["GET"],
            response_class=HTMLResponse,
            dependencies=[Depends(get_admin_auth_with_context)],
        )


# Create auth-method-agnostic route handlers for each endpoint type
async def authenticated_root_handler(request: Request, auth: Auth):
    """Shared handler for authenticated root endpoint."""
    async with get_db_session() as db_session:
        recent = await get_latest_payloads(db_session, limit=5)
    ha_states = await fetch_states()
    aw_summary = await activitywatch.fetch_recent_activity()
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "header": "Gatelet",
            "auth": auth,
            "recent_payloads": recent,
            "ha_states": ha_states,
            "aw_activity": aw_summary,
        },
    )


# Register root page with all auth methods
register_with_all_auth_methods("/", authenticated_root_handler, register_admin=False)

# Register webhook routes with all auth methods
register_with_all_auth_methods("/webhooks/", webhook_view.list_all_payloads)
register_with_all_auth_methods(
    "/webhooks/{integration_name}",
    webhook_view.list_integration_payloads,
)

# Register Home Assistant routes with all auth methods
register_with_all_auth_methods("/ha/", homeassistant.list_entities)
register_with_all_auth_methods("/ha/{entity_id}", homeassistant.entity_details)
