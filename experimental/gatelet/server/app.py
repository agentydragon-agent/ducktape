"""FastAPI application for Gatelet server."""

import logging
from typing import Callable, Optional

from fastapi import Cookie, Depends, FastAPI, Request, status
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from .shared import templates, BASE_DIR

from .auth.handlers import AuthContext, AuthHandlerError
from .auth.dependencies import (
    Auth,
    get_key_path_auth_with_context,
    get_session_auth_with_context,
)
from .auth.webhook_auth import AuthError
from .config import settings
from .endpoints import challenge, webhook_receive, webhook_view

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Gatelet", description="LLM-friendly API for Home Assistant and webhooks"
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
    from fastapi.responses import JSONResponse

    return JSONResponse(
        status_code=status.HTTP_401_UNAUTHORIZED,
        content={"detail": "Authentication failed"},
        headers=getattr(exc, "headers", {}),
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


# Create auth-method-agnostic route handlers for each endpoint type
async def authenticated_root_handler(request: Request, auth: Auth):
    """Shared handler for authenticated root endpoint."""
    return templates.TemplateResponse(
        "index.html", {"request": request, "header": "Gatelet", "auth": auth}
    )


# Register root page with all auth methods
register_with_all_auth_methods("/", authenticated_root_handler)

# Register webhook routes with all auth methods
register_with_all_auth_methods("/webhooks/", webhook_view.list_all_payloads)
register_with_all_auth_methods(
    "/webhooks/{integration_name}", webhook_view.list_integration_payloads
)
