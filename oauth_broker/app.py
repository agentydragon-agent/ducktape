"""FastAPI application for OAuth token brokering."""

import asyncio
import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from jinja2 import Environment, FileSystemLoader

from oauth_broker.k8s_client import K8sTokenWriter
from oauth_broker.provider import GenericOAuth2Provider
from oauth_broker.refresh import token_refresh_loop

logger = logging.getLogger(__name__)

_pending_states: dict[str, str] = {}


def create_app(
    providers: dict[str, GenericOAuth2Provider], k8s_writer: K8sTokenWriter, target_namespace: str
) -> FastAPI:
    app = FastAPI(title="OAuth Broker", docs_url=None, redoc_url=None)
    jinja_env = Environment(loader=FileSystemLoader(Path(__file__).parent), autoescape=True)
    template = jinja_env.get_template("index.html.j2")
    background_tasks: set[asyncio.Task[None]] = set()

    @app.on_event("startup")
    async def start_refresh_loop() -> None:
        task = asyncio.create_task(token_refresh_loop(providers, k8s_writer, target_namespace))
        background_tasks.add(task)
        task.add_done_callback(background_tasks.discard)

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        provider_rows = []
        for name, provider in providers.items():
            token = await k8s_writer.read_token(provider.config.secret_name, target_namespace)
            if token is not None:
                status = f"Connected (expires {token.expires_at.strftime('%Y-%m-%d')})"
                action = "Reconnect"
            else:
                status = "Not connected"
                action = "Connect"
            provider_rows.append(
                {"name": name, "display_name": provider.config.display_name, "status": status, "action": action}
            )
        return template.render(providers=provider_rows)

    @app.get("/authorize/{provider_name}")
    async def authorize(provider_name: str) -> Response:
        provider = providers.get(provider_name)
        if provider is None:
            raise HTTPException(404, f"Unknown provider: {provider_name}")
        state = provider.generate_state()
        _pending_states[state] = provider_name
        url = provider.build_authorize_url(state)
        return RedirectResponse(url)

    @app.get("/callback/{provider_name}")
    async def callback(provider_name: str, request: Request) -> Response:
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

        provider = providers.get(provider_name)
        if provider is None:
            raise HTTPException(404, f"Unknown provider: {provider_name}")

        token = await provider.exchange_code(code)
        await k8s_writer.write_token(provider.config.secret_name, target_namespace, token)
        logger.info(f"Stored tokens for {provider_name} (expires {token.expires_at})")
        return RedirectResponse("/")

    @app.get("/status")
    async def status() -> dict:
        result = {}
        for name, provider in providers.items():
            token = await k8s_writer.read_token(provider.config.secret_name, target_namespace)
            if token is not None:
                result[name] = {"connected": True, "expires_at": token.expires_at.isoformat(), "scope": token.scope}
            else:
                result[name] = {"connected": False}
        return result

    return app
