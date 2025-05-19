"""FastAPI application for Gatelet server."""

import logging
from pathlib import Path
from typing import Any, Callable, Optional, Type

from fastapi import Cookie, Depends, FastAPI, Request, status
from fastapi.responses import HTMLResponse
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


# Create auth-method-agnostic route handlers for each endpoint type
async def authenticated_root_handler(request: Request, auth: AuthContext):
    """Shared handler for authenticated root endpoint."""
    return templates.TemplateResponse(
        "index.html", {"request": request, "header": "Gatelet", "auth": auth}
    )


async def webhook_list_handler(request: Request, auth: AuthContext):
    """Shared handler for webhook list endpoint."""
    # Get webhook integrations - implementation will be added later
    integrations = []

    return templates.TemplateResponse(
        "webhooks_list.html",
        {
            "request": request,
            "header": "Webhook Integrations",
            "auth": auth,
            "integrations": integrations,
        },
    )


def register_auth_routes(
    prefix: str,
    auth_dependency: Callable,
    auth_context_type: Type[AuthContext],
    enabled: bool,
):
    """Register all routes for a specific authentication method.

    Args:
        prefix: URL prefix for this auth method (e.g., "k/{key}")
        auth_dependency: Dependency function for this auth method
        auth_context_type: Type of auth context for type hints
        enabled: Whether this auth method is enabled
    """
    if not enabled:
        return

    # Root endpoint
    @app.get(f"/{prefix}/", response_class=HTMLResponse)
    async def auth_root(
        request: Request, auth: auth_context_type = Depends(auth_dependency)
    ):
        return await authenticated_root_handler(request, auth)

    # Webhook list endpoint
    @app.get(f"/{prefix}/webhooks/", response_class=HTMLResponse)
    async def auth_webhooks(
        request: Request,
        auth: auth_context_type = Depends(auth_dependency),
        db_session: AsyncSession = Depends(get_db_session),
    ):
        return await webhook_list_handler(request, auth, db_session)


# Register routes for each auth method
register_auth_routes(
    prefix="k/{key}",
    auth_dependency=key_path_auth,
    auth_context_type=KeyPathAuthContext,
    enabled=settings.auth.key_in_url.enabled,
)

register_auth_routes(
    prefix="s/{session_token}",
    auth_dependency=session_auth,
    auth_context_type=SessionAuthContext,
    enabled=settings.auth.challenge_response.enabled,
)

