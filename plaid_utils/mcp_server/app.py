"""Plaid v0 web app: Link UI plus synchronous full-refresh sync."""

from __future__ import annotations

import contextlib
import logging
import re
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Annotated

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from plaid_utils.client import PlaidCreds, plaid_client
from plaid_utils.link_profiles import LinkProfile, products_for_profile
from plaid_utils.link_store import PlaidLinkStorage, StoredLink
from plaid_utils.plaid_link import PlaidLinkClient, PlaidLinkCreds
from plaid_utils.secret_store import K8sSecretStore, SecretStore
from plaid_utils.sync import SyncWindows, sync_all, sync_link

logger = logging.getLogger(__name__)

_NS_PATH = Path("/var/run/secrets/kubernetes.io/serviceaccount/namespace")


class PlaidWebSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PLAID_MCP_")

    plaid_env: str = Field(description="Plaid environment: sandbox or production.")
    client_id: str
    client_secret: str
    database_url: str = Field(validation_alias="DATABASE_URL")
    public_base_url: str = "https://plaid-mcp.allegedly.works"
    target_namespace: str | None = None
    managed_by: str = "plaid-mcp"
    host: str = "0.0.0.0"
    port: int = 8080
    transaction_days: int = 730
    investment_transaction_days: int = 730

    @field_validator("public_base_url", mode="after")
    @classmethod
    def _strip_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")

    @property
    def redirect_uri(self) -> str:
        return f"{self.public_base_url}/link/callback"

    @property
    def namespace(self) -> str:
        if self.target_namespace is not None:
            return self.target_namespace
        if _NS_PATH.exists():
            return _NS_PATH.read_text().strip()
        return "plaid-mcp"

    @property
    def sync_windows(self) -> SyncWindows:
        return SyncWindows(
            transaction_days=self.transaction_days, investment_transaction_days=self.investment_transaction_days
        )


class LinkTokenRequest(BaseModel):
    profile: LinkProfile
    advanced_products: list[str] | None = None


class LinkTokenResponse(BaseModel):
    link_token: str
    products: list[str]


class ExchangePublicTokenRequest(BaseModel):
    public_token: str
    profile: LinkProfile
    products: list[str]
    label: str | None = None
    institution_id: str | None = None
    institution_name: str | None = None


class LinkSummary(BaseModel):
    item_id: str
    label: str | None
    institution_id: str | None
    institution_name: str | None
    link_profile: LinkProfile
    products_requested: list[str]
    products_authorized: list[str]
    products_billed: list[str]
    status: str
    access_token_secret: str
    last_synced_at: str | None


class AppState:
    def __init__(self) -> None:
        self.storage: PlaidLinkStorage | None = None
        self.secrets: SecretStore | None = None


def create_app(
    settings: PlaidWebSettings, *, storage: PlaidLinkStorage | None = None, secrets: SecretStore | None = None
) -> FastAPI:
    state = AppState()
    link_client = PlaidLinkClient(
        PlaidLinkCreds(client_id=settings.client_id, secret=settings.client_secret, env=settings.plaid_env)
    )
    api = plaid_client(PlaidCreds(client_id=settings.client_id, secret=settings.client_secret, env=settings.plaid_env))

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        state.storage = storage or await PlaidLinkStorage.initialize(settings.database_url)
        state.secrets = secrets or await K8sSecretStore.from_incluster(settings.namespace, settings.managed_by)
        try:
            yield
        finally:
            if storage is None and state.storage is not None:
                await state.storage.close()

    app = FastAPI(title="Plaid Link Service", docs_url=None, redoc_url=None, lifespan=lifespan)

    def require_storage() -> PlaidLinkStorage:
        if state.storage is None:
            raise RuntimeError("storage not initialized")
        return state.storage

    def require_secrets() -> SecretStore:
        if state.secrets is None:
            raise RuntimeError("secret store not initialized")
        return state.secrets

    @app.get("/healthz")
    async def healthz() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/link", response_class=HTMLResponse)
    async def link_ui() -> str:
        return _LINK_HTML

    @app.get("/link/callback", response_class=HTMLResponse)
    async def link_callback() -> str:
        return _LINK_HTML

    @app.get("/", response_class=HTMLResponse)
    async def root() -> str:
        return _LINK_HTML

    @app.get("/api/links")
    async def list_links() -> list[LinkSummary]:
        return [_link_summary(link) for link in await require_storage().list_active_links()]

    @app.post("/api/link-token")
    async def create_link_token(body: LinkTokenRequest) -> LinkTokenResponse:
        result = await link_client.create_link_token(
            profile=body.profile,
            redirect_uri=settings.redirect_uri,
            client_user_id="owner",
            advanced_products=body.advanced_products,
        )
        return LinkTokenResponse(link_token=result.link_token, products=result.products)

    @app.post("/api/exchange-public-token")
    async def exchange_public_token(body: ExchangePublicTokenRequest) -> LinkSummary:
        exchange = await link_client.exchange_public_token(body.public_token)
        secret_name = _secret_name_for_item(exchange.item_id)
        await require_secrets().write_access_token(secret_name, exchange.access_token)
        requested = body.products or products_for_profile(body.profile)
        link = await require_storage().upsert_link(
            item_id=exchange.item_id,
            access_token_secret=secret_name,
            link_profile=body.profile,
            products_requested=requested,
            products_authorized=requested,
            products_billed=[],
            institution_id=body.institution_id,
            institution_name=body.institution_name,
            label=body.label,
        )
        await sync_link(
            api=api,
            storage=require_storage(),
            secrets=require_secrets(),
            link=link,
            trigger="link",
            windows=settings.sync_windows,
        )
        updated = await require_storage().get_link(exchange.item_id)
        if updated is None:
            raise RuntimeError("newly inserted Plaid link disappeared")
        return _link_summary(updated)

    @app.post("/api/links/{item_id}/remove")
    async def remove_link(item_id: Annotated[str, Field(description="Plaid item_id")]) -> dict[str, str]:
        link = await require_storage().get_link(item_id)
        if link is None:
            raise HTTPException(404, f"unknown item_id: {item_id}")
        access_token = await require_secrets().read_access_token(link.access_token_secret)
        await link_client.remove_item(access_token)
        await require_secrets().delete_access_token(link.access_token_secret)
        await require_storage().mark_link_revoked(item_id)
        return {"status": "revoked"}

    return app


async def run_sync(settings: PlaidWebSettings) -> list[str]:
    storage = await PlaidLinkStorage.initialize(settings.database_url)
    secrets = await K8sSecretStore.from_incluster(settings.namespace, settings.managed_by)
    api = plaid_client(PlaidCreds(client_id=settings.client_id, secret=settings.client_secret, env=settings.plaid_env))
    try:
        run_ids = await sync_all(
            api=api, storage=storage, secrets=secrets, trigger="cron", windows=settings.sync_windows
        )
        return [str(run_id) for run_id in run_ids]
    finally:
        await storage.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s", stream=sys.stderr)
    settings = PlaidWebSettings()
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, log_level="info")


def _secret_name_for_item(item_id: str) -> str:
    slug = re.sub("[^a-z0-9-]+", "-", item_id.lower()).strip("-")
    return f"plaid-{slug}-access-token"[:253]


def _link_summary(link: StoredLink) -> LinkSummary:
    return LinkSummary(
        item_id=link.item_id,
        label=link.label,
        institution_id=link.institution_id,
        institution_name=link.institution_name,
        link_profile=link.link_profile,
        products_requested=link.products_requested,
        products_authorized=link.products_authorized,
        products_billed=link.products_billed,
        status=link.status,
        access_token_secret=link.access_token_secret,
        last_synced_at=link.last_synced_at.isoformat() if link.last_synced_at else None,
    )


_LINK_HTML = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Plaid Links</title>
    <script src="https://cdn.plaid.com/link/v2/stable/link-initialize.js"></script>
    <style>
      :root { color-scheme: light dark; font-family: system-ui, sans-serif; }
      body { margin: 0; background: Canvas; color: CanvasText; }
      main { max-width: 960px; margin: 0 auto; padding: 32px 20px; }
      header { display: flex; justify-content: space-between; gap: 16px; align-items: center; }
      h1 { font-size: 28px; margin: 0; }
      section { margin-top: 24px; }
      form { display: grid; grid-template-columns: 1fr 1fr auto; gap: 12px; align-items: end; }
      label { display: grid; gap: 6px; font-size: 13px; color: color-mix(in srgb, CanvasText 78%, Canvas); }
      input, select, button { font: inherit; padding: 8px 10px; border-radius: 6px; border: 1px solid color-mix(in srgb, CanvasText 22%, Canvas); background: Canvas; color: CanvasText; }
      button { cursor: pointer; background: #276ef1; color: white; border-color: #276ef1; font-weight: 650; }
      .advanced { display: none; grid-column: 1 / -1; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }
      .advanced.visible { display: grid; }
      .check { display: flex; align-items: center; gap: 8px; padding: 8px 10px; border: 1px solid color-mix(in srgb, CanvasText 16%, Canvas); border-radius: 6px; color: CanvasText; }
      .check input { padding: 0; }
      table { width: 100%; border-collapse: collapse; margin-top: 12px; }
      th, td { text-align: left; padding: 10px 8px; border-bottom: 1px solid color-mix(in srgb, CanvasText 14%, Canvas); font-size: 14px; vertical-align: top; }
      .muted { color: color-mix(in srgb, CanvasText 62%, Canvas); }
      .danger { background: #b42318; border-color: #b42318; }
      @media (max-width: 720px) { form { grid-template-columns: 1fr; } }
    </style>
  </head>
  <body>
    <main>
      <header>
        <div>
          <h1>Plaid Links</h1>
          <div class="muted">Manage linked institutions and product profiles.</div>
        </div>
      </header>
      <section>
        <form id="link-form">
          <label>Label <input id="label" placeholder="Chase personal" /></label>
          <label>Data surface
            <select id="profile">
              <option value="cashflow">Cashflow</option>
              <option value="credit_card_detail">Credit card detail</option>
              <option value="investments_holdings">Investment holdings</option>
              <option value="investments_full">Investments full</option>
              <option value="full_picture">Full picture</option>
              <option value="advanced">Advanced</option>
            </select>
          </label>
          <div id="advanced-products" class="advanced">
            <label class="check"><input type="checkbox" value="transactions" checked />Transactions</label>
            <label class="check"><input type="checkbox" value="investments" />Investments</label>
            <label class="check"><input type="checkbox" value="liabilities" />Liabilities</label>
          </div>
          <button type="submit">Connect</button>
        </form>
      </section>
      <section>
        <h2>Current Links</h2>
        <table>
          <thead><tr><th>Institution</th><th>Profile</th><th>Products</th><th>Last Sync</th><th></th></tr></thead>
          <tbody id="links"></tbody>
        </table>
      </section>
    </main>
    <script>
      const pendingKey = 'plaid-link-pending';

      async function refreshLinks() {
        const links = await fetch('/api/links').then(r => r.json());
        const tbody = document.getElementById('links');
        tbody.innerHTML = '';
        for (const link of links) {
          const tr = document.createElement('tr');
          tr.innerHTML = `<td>${link.label || link.institution_name || link.item_id}<div class="muted">${link.institution_name || ''}</div></td><td>${link.link_profile}</td><td>${link.products_requested.join(', ')}</td><td>${link.last_synced_at || ''}</td><td><button class="danger" data-item="${link.item_id}">Remove</button></td>`;
          tbody.appendChild(tr);
        }
      }
      function advancedProducts() {
        return Array.from(document.querySelectorAll('#advanced-products input:checked')).map(input => input.value);
      }
      function setAdvancedVisibility() {
        document.getElementById('advanced-products').classList.toggle('visible', document.getElementById('profile').value === 'advanced');
      }
      async function exchangePublicToken(public_token, metadata, pending) {
        await fetch('/api/exchange-public-token', {
          method: 'POST',
          headers: {'content-type': 'application/json'},
          body: JSON.stringify({
            public_token,
            profile: pending.profile,
            products: pending.products,
            label: pending.label,
            institution_id: metadata.institution?.institution_id || null,
            institution_name: metadata.institution?.name || null
          })
        });
        sessionStorage.removeItem(pendingKey);
        await refreshLinks();
      }
      function openPlaid(pending, receivedRedirectUri) {
        const handler = Plaid.create({
          token: pending.link_token,
          receivedRedirectUri,
          onSuccess: async (public_token, metadata) => exchangePublicToken(public_token, metadata, pending)
        });
        handler.open();
      }
      document.getElementById('links').addEventListener('click', async (event) => {
        const item = event.target?.dataset?.item;
        if (!item) return;
        await fetch(`/api/links/${encodeURIComponent(item)}/remove`, {method: 'POST'});
        await refreshLinks();
      });
      document.getElementById('profile').addEventListener('change', setAdvancedVisibility);
      document.getElementById('link-form').addEventListener('submit', async (event) => {
        event.preventDefault();
        const profile = document.getElementById('profile').value;
        const label = document.getElementById('label').value || null;
        const advanced_products = profile === 'advanced' ? advancedProducts() : null;
        const token = await fetch('/api/link-token', {method: 'POST', headers: {'content-type': 'application/json'}, body: JSON.stringify({profile, advanced_products})}).then(r => r.json());
        const pending = {profile, products: token.products, label, link_token: token.link_token};
        sessionStorage.setItem(pendingKey, JSON.stringify(pending));
        openPlaid(pending);
      });
      setAdvancedVisibility();
      refreshLinks();
      const pending = JSON.parse(sessionStorage.getItem(pendingKey) || 'null');
      if (pending && new URLSearchParams(window.location.search).has('oauth_state_id')) {
        openPlaid(pending, window.location.href);
      }
    </script>
  </body>
</html>
"""


if __name__ == "__main__":
    main()
