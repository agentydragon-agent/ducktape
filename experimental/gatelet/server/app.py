"""FastAPI application for Gatelet server."""

import logging
from pathlib import Path
from typing import Any, Callable, Optional, Type

from fastapi import Cookie, Depends, FastAPI, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from .auth.handlers import (
    AuthContext,
    AuthHandlerError,
    KeyPathAuthContext,
    SessionAuthContext,
    key_path_auth,
    session_auth,
)
from .auth.webhook_auth import AuthError
from .config import settings
from .database import get_db_session
from .endpoints import webhook_receive, webhook_view

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Gatelet", description="LLM-friendly API for Home Assistant and webhooks"
)
BASE_DIR = Path(__file__).parent
app.mount(
    "/static",
    StaticFiles(directory=BASE_DIR / "static"),
    name="static",
)
templates = Jinja2Templates(directory=BASE_DIR / "templates")

# Include routers
app.include_router(webhook_receive.router)
app.include_router(webhook_view.router)


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


# Root endpoint - public information and login form
@app.get("/", response_class=HTMLResponse)
async def root(request: Request, session: Optional[str] = Cookie(None)):
    """Root endpoint with service information and authentication options."""
    # Check if already authenticated via cookie
    if session:
        raise NotImplementedError("TODO: redirect to authenticated root")

    return templates.TemplateResponse(
        "public.html",
        {
            "request": request,
            "header": "Gatelet",
            "show_admin_login": True,
            "llm_instructions": "To access this service as an LLM, follow the instructions provided by your user.",
        },
    )


def register_with_all_auth_methods(path: str, handler: Callable):
    """Register a handler with all available auth methods.

    Args:
        path: URL path to register (without auth prefix)
        handler: Handler function to register
    """
    # Key in path auth
    if settings.auth.key_in_url.enabled:
        app.add_api_route(
            f"/k/{{key}}{path}",
            handler,
            methods=["GET"],
            response_class=HTMLResponse,
            dependencies=[Depends(key_path_auth)],
        )

    # Challenge-response session auth
    if settings.auth.challenge_response.enabled:
        app.add_api_route(
            f"/s/{{session_token}}{path}",
            handler,
            methods=["GET"],
            response_class=HTMLResponse,
            dependencies=[Depends(session_auth)],
        )


# Create auth-method-agnostic route handlers for each endpoint type
async def authenticated_root_handler(request: Request, auth: AuthContext):
    """Shared handler for authenticated root endpoint."""
    return templates.TemplateResponse(
        "index.html", {"request": request, "header": "Gatelet", "auth": auth}
    )


# Register root page with all auth methods
register_with_all_auth_methods("/", authenticated_root_handler)
