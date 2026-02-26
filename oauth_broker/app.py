"""FastAPI application for OAuth token brokering."""

import asyncio
import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from jinja2 import Environment, FileSystemLoader
from pydantic import BaseModel

from oauth_broker.k8s_client import K8sTokenStore
from oauth_broker.provider import GenericOAuth2Provider, PlaidProvider
from oauth_broker.refresh import token_refresh_loop

logger = logging.getLogger(__name__)

_pending_states: dict[str, str] = {}


class _PlaidCallbackBody(BaseModel):
    public_token: str


def create_app(providers: dict[str, GenericOAuth2Provider], target_namespace: str) -> FastAPI:
    app = FastAPI(title="OAuth Broker", docs_url=None, redoc_url=None)
    jinja_env = Environment(loader=FileSystemLoader(Path(__file__).parent), autoescape=True)
    index_template = jinja_env.get_template("index.html.j2")
    plaid_template = jinja_env.get_template("plaid_link.html.j2")
    background_tasks: set[asyncio.Task[None]] = set()
    k8s_store: K8sTokenStore | None = None

    @app.on_event("startup")
    async def startup() -> None:
        nonlocal k8s_store
        k8s_store = await K8sTokenStore.from_incluster()
        task = asyncio.create_task(token_refresh_loop(providers, k8s_store, target_namespace))
        background_tasks.add(task)
        task.add_done_callback(background_tasks.discard)

    def get_store() -> K8sTokenStore:
        assert k8s_store is not None, "K8sTokenStore not initialized"
        return k8s_store

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        provider_rows = []
        for name, provider in providers.items():
            token = await get_store().read_token(provider.config.secret_name, target_namespace)
            if token is not None:
                status = f"Connected (expires {token.expires_at.strftime('%Y-%m-%d')})"
                action = "Reconnect"
            else:
                status = "Not connected"
                action = "Connect"
            provider_rows.append(
                {"name": name, "display_name": provider.config.display_name, "status": status, "action": action}
            )
        return index_template.render(providers=provider_rows)

    @app.get("/authorize/{provider_name}")
    async def authorize(provider_name: str) -> Response:
        provider = providers.get(provider_name)
        if provider is None:
            raise HTTPException(404, f"Unknown provider: {provider_name}")
        state = provider.generate_state()
        _pending_states[state] = provider_name
        if isinstance(provider, PlaidProvider):
            link_token = await provider.create_link_token(state)
            return HTMLResponse(plaid_template.render(link_token=link_token, received_redirect_uri=None))
        url = provider.build_authorize_url(state)
        return RedirectResponse(url)

    @app.get("/callback/{provider_name}")
    async def callback_get(provider_name: str, request: Request) -> Response:
        provider = providers.get(provider_name)
        if provider is None:
            raise HTTPException(404, f"Unknown provider: {provider_name}")

        # Plaid OAuth institution mid-flow: bank redirected here with oauth_state_id.
        # Re-render the Plaid Link widget with receivedRedirectUri so it can resume.
        if isinstance(provider, PlaidProvider):
            oauth_state_id = request.query_params.get("oauth_state_id")
            if oauth_state_id is None:
                raise HTTPException(400, "Plaid callback missing oauth_state_id")
            # Create a fresh link_token for resuming the OAuth session.
            state = provider.generate_state()
            _pending_states[state] = provider_name
            link_token = await provider.create_link_token(state)
            return HTMLResponse(plaid_template.render(link_token=link_token, received_redirect_uri=str(request.url)))

        code = request.query_params.get("code")
        state = request.query_params.get("state")
        error = request.query_params.get("error")

        if error:
            raise HTTPException(400, f"OAuth error: {error}")
        if not code or not state:
            raise HTTPException(400, "Missing code or state parameter")

        expected_provider = _pending_states.pop(state, None)
        if expected_provider is None:
            raise HTTPException(400, "Invalid or expired state parameter")
        if expected_provider != provider_name:
            raise HTTPException(400, "State/provider mismatch")

        token = await provider.exchange_code(code)
        await get_store().write_token(
            provider.config.secret_name, target_namespace, token, annotations=provider.config.secret_annotations or None
        )
        logger.info(f"Stored tokens for {provider_name} (expires {token.expires_at})")
        return RedirectResponse("/")

    @app.post("/callback/{provider_name}")
    async def callback_post(provider_name: str, body: _PlaidCallbackBody) -> Response:
        """Receive the public_token from the Plaid Link JS widget and exchange it."""
        provider = providers.get(provider_name)
        if provider is None:
            raise HTTPException(404, f"Unknown provider: {provider_name}")
        if not isinstance(provider, PlaidProvider):
            raise HTTPException(405, f"{provider_name} does not support POST callback")
        token = await provider.exchange_public_token(body.public_token)
        await get_store().write_token(
            provider.config.secret_name, target_namespace, token, annotations=provider.config.secret_annotations or None
        )
        logger.info(f"Stored Plaid tokens for {provider_name}")
        return RedirectResponse("/", status_code=303)

    @app.get("/status")
    async def status() -> dict:
        result = {}
        for name, provider in providers.items():
            token = await get_store().read_token(provider.config.secret_name, target_namespace)
            if token is not None:
                result[name] = {"connected": True, "expires_at": token.expires_at.isoformat(), "scope": token.scope}
            else:
                result[name] = {"connected": False}
        return result

    return app
