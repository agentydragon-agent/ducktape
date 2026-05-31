"""Plaid v0 web app: Link UI plus synchronous full-refresh sync."""

from __future__ import annotations

import contextlib
import json
import logging
import re
import sys
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal, Protocol
from uuid import UUID

import uvicorn
from fastapi import FastAPI, HTTPException, Path as ApiPath
from fastapi.responses import HTMLResponse, Response
from plaid.exceptions import ApiException as PlaidApiException
from plaid.model.country_code import CountryCode
from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
from plaid.model.item_remove_request import ItemRemoveRequest
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
from plaid.model.products import Products
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from plaid_utils.client import PlaidCreds, plaid_client
from plaid_utils.link_profiles import LinkProfile, products_for_profile
from plaid_utils.link_store import PlaidLinkStorage, StoredLink
from plaid_utils.secret_store import K8sSecretStore, SecretStore
from plaid_utils.sync import PlaidApiLike, SyncWindows, sync_all, sync_link

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


class LinkUpdateTokenRequest(BaseModel):
    reason: Literal["repair", "add_scope"] = "repair"
    profile: LinkProfile | None = None
    advanced_products: list[str] | None = None


class LinkUpdateTokenResponse(BaseModel):
    link_token: str
    products: list[str]
    additional_products: list[str]


class CompleteLinkUpdateRequest(BaseModel):
    profile: LinkProfile | None = None
    products: list[str] = Field(default_factory=list)
    sync: bool = True


class SyncResponse(BaseModel):
    run_id: str


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


@dataclass(frozen=True)
class LinkTokenResult:
    link_token: str
    products: list[str]


@dataclass(frozen=True)
class PublicTokenExchange:
    access_token: str
    item_id: str


class PlaidLinkApiError(RuntimeError):
    def __init__(self, *, endpoint: str, status_code: int, text: str, payload: dict[str, Any] | None = None) -> None:
        self.endpoint = endpoint
        self.status_code = status_code
        self.text = text
        self.payload = payload
        message = payload.get("error_message") if payload else text
        super().__init__(f"Plaid {endpoint} {status_code}: {message}")

    def public_detail(self) -> dict[str, Any]:
        detail: dict[str, Any] = {"endpoint": self.endpoint, "status_code": self.status_code}
        if self.payload:
            for key in (
                "error_type",
                "error_code",
                "error_message",
                "display_message",
                "documentation_url",
                "request_id",
            ):
                if key in self.payload:
                    detail[key] = self.payload[key]
        else:
            detail["error_message"] = self.text
        return detail


class LinkTokenCreateResponse(Protocol):
    link_token: str


class ItemPublicTokenExchangeResponse(Protocol):
    access_token: str
    item_id: str


class PlaidWebApi(PlaidApiLike, Protocol):
    """Plaid SDK methods used by the Link management UI."""

    def link_token_create(self, request: LinkTokenCreateRequest, /) -> LinkTokenCreateResponse: ...
    def item_public_token_exchange(
        self, request: ItemPublicTokenExchangeRequest, /
    ) -> ItemPublicTokenExchangeResponse: ...
    def item_remove(self, request: ItemRemoveRequest, /) -> object: ...


class AppState:
    def __init__(self) -> None:
        self.storage: PlaidLinkStorage | None = None
        self.secrets: SecretStore | None = None


def create_app(
    settings: PlaidWebSettings,
    *,
    storage: PlaidLinkStorage | None = None,
    secrets: SecretStore | None = None,
    api: PlaidWebApi | None = None,
) -> FastAPI:
    state = AppState()
    plaid_api = api or plaid_client(
        PlaidCreds(client_id=settings.client_id, secret=settings.client_secret, env=settings.plaid_env)
    )

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

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon() -> Response:
        return Response(status_code=204)

    @app.get("/api/links")
    async def list_links() -> list[LinkSummary]:
        return [_link_summary(link) for link in await require_storage().list_active_links()]

    @app.post("/api/link-token")
    async def create_link_token(body: LinkTokenRequest) -> LinkTokenResponse:
        try:
            result = _create_link_token(
                plaid_api,
                profile=body.profile,
                redirect_uri=settings.redirect_uri,
                client_user_id="owner",
                advanced_products=body.advanced_products,
            )
        except PlaidLinkApiError as exc:
            raise HTTPException(502, exc.public_detail()) from exc
        return LinkTokenResponse(link_token=result.link_token, products=result.products)

    @app.post("/api/exchange-public-token")
    async def exchange_public_token(body: ExchangePublicTokenRequest) -> LinkSummary:
        try:
            exchange = _exchange_public_token(plaid_api, body.public_token)
        except PlaidLinkApiError as exc:
            raise HTTPException(502, exc.public_detail()) from exc
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
            api=plaid_api,
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

    @app.post("/api/links/{item_id}/update-link-token")
    async def create_update_link_token(
        item_id: Annotated[str, ApiPath(description="Plaid item_id")], body: LinkUpdateTokenRequest
    ) -> LinkUpdateTokenResponse:
        link = await require_storage().get_link(item_id)
        if link is None:
            raise HTTPException(404, f"unknown item_id: {item_id}")
        access_token = await require_secrets().read_access_token(link.access_token_secret)
        requested = _requested_products_for_update(link, body)
        additional = [product for product in requested if product not in link.products_authorized]
        try:
            result = _create_update_link_token(
                plaid_api,
                access_token=access_token,
                redirect_uri=settings.redirect_uri,
                client_user_id="owner",
                additional_products=additional if body.reason == "add_scope" else None,
            )
        except PlaidLinkApiError as exc:
            raise HTTPException(502, exc.public_detail()) from exc
        return LinkUpdateTokenResponse(
            link_token=result.link_token,
            products=_merge_products(link.products_requested, requested),
            additional_products=additional,
        )

    @app.post("/api/links/{item_id}/complete-update")
    async def complete_link_update(
        item_id: Annotated[str, ApiPath(description="Plaid item_id")], body: CompleteLinkUpdateRequest
    ) -> LinkSummary:
        current = await require_storage().get_link(item_id)
        if current is None:
            raise HTTPException(404, f"unknown item_id: {item_id}")
        products = _merge_products(current.products_requested, body.products)
        profile = body.profile or current.link_profile
        link = await require_storage().mark_link_update_succeeded(
            item_id=item_id, link_profile=profile, products_requested=products
        )
        if link is None:
            raise HTTPException(404, f"unknown item_id: {item_id}")
        if body.sync:
            await _sync_one_link(api=plaid_api, storage=require_storage(), secrets=require_secrets(), link=link)
            refreshed = await require_storage().get_link(item_id)
            if refreshed is not None:
                link = refreshed
        return _link_summary(link)

    @app.post("/api/links/{item_id}/sync")
    async def sync_existing_link(item_id: Annotated[str, ApiPath(description="Plaid item_id")]) -> SyncResponse:
        link = await require_storage().get_link(item_id)
        if link is None:
            raise HTTPException(404, f"unknown item_id: {item_id}")
        run_id = await _sync_one_link(api=plaid_api, storage=require_storage(), secrets=require_secrets(), link=link)
        return SyncResponse(run_id=str(run_id))

    @app.post("/api/links/{item_id}/remove")
    async def remove_link(item_id: Annotated[str, ApiPath(description="Plaid item_id")]) -> dict[str, str]:
        link = await require_storage().get_link(item_id)
        if link is None:
            raise HTTPException(404, f"unknown item_id: {item_id}")
        access_token = await require_secrets().read_access_token(link.access_token_secret)
        try:
            _remove_item(plaid_api, access_token)
        except PlaidLinkApiError as exc:
            raise HTTPException(502, exc.public_detail()) from exc
        await require_secrets().delete_access_token(link.access_token_secret)
        await require_storage().mark_link_revoked(item_id)
        return {"status": "revoked"}

    return app


def _create_link_token(
    api: PlaidWebApi,
    *,
    profile: LinkProfile,
    redirect_uri: str,
    client_user_id: str,
    advanced_products: list[str] | None = None,
    client_name: str = "Plaid MCP",
) -> LinkTokenResult:
    products = products_for_profile(profile, advanced_products)
    request = LinkTokenCreateRequest(
        client_name=client_name,
        user=LinkTokenCreateRequestUser(client_user_id=client_user_id),
        products=[Products(product) for product in products],
        country_codes=[CountryCode("US")],
        language="en",
        redirect_uri=redirect_uri,
        transactions={"days_requested": 730},
    )
    try:
        response = api.link_token_create(request)
    except PlaidApiException as exc:
        raise _plaid_api_error("/link/token/create", exc) from exc
    return LinkTokenResult(link_token=response.link_token, products=products)


def _create_update_link_token(
    api: PlaidWebApi,
    *,
    access_token: str,
    redirect_uri: str,
    client_user_id: str,
    additional_products: list[str] | None = None,
    client_name: str = "Plaid MCP",
) -> LinkTokenResult:
    request = LinkTokenCreateRequest(
        client_name=client_name,
        user=LinkTokenCreateRequestUser(client_user_id=client_user_id),
        country_codes=[CountryCode("US")],
        language="en",
        redirect_uri=redirect_uri,
        access_token=access_token,
    )
    if additional_products:
        request.additional_consented_products = [Products(product) for product in additional_products]
    try:
        response = api.link_token_create(request)
    except PlaidApiException as exc:
        raise _plaid_api_error("/link/token/create", exc) from exc
    return LinkTokenResult(link_token=response.link_token, products=additional_products or [])


def _exchange_public_token(api: PlaidWebApi, public_token: str) -> PublicTokenExchange:
    try:
        response = api.item_public_token_exchange(ItemPublicTokenExchangeRequest(public_token=public_token))
    except PlaidApiException as exc:
        raise _plaid_api_error("/item/public_token/exchange", exc) from exc
    return PublicTokenExchange(access_token=response.access_token, item_id=response.item_id)


def _remove_item(api: PlaidWebApi, access_token: str) -> None:
    try:
        api.item_remove(ItemRemoveRequest(access_token=access_token))
    except PlaidApiException as exc:
        raise _plaid_api_error("/item/remove", exc) from exc


def _plaid_api_error(endpoint: str, exc: PlaidApiException) -> PlaidLinkApiError:
    text = str(getattr(exc, "body", None) or exc)
    payload = None
    try:
        parsed = json.loads(text)
    except ValueError:
        parsed = None
    if isinstance(parsed, dict):
        payload = parsed
    status_code = int(getattr(exc, "status", None) or 500)
    return PlaidLinkApiError(endpoint=endpoint, status_code=status_code, text=text, payload=payload)


async def _sync_one_link(
    *, api: PlaidApiLike, storage: PlaidLinkStorage, secrets: SecretStore, link: StoredLink
) -> UUID:
    try:
        return await sync_link(api=api, storage=storage, secrets=secrets, link=link, trigger="manual")
    except RuntimeError as exc:
        if "sync already running" in str(exc):
            raise HTTPException(409, str(exc)) from exc
        raise


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


def _requested_products_for_update(link: StoredLink, body: LinkUpdateTokenRequest) -> list[str]:
    if body.reason == "repair" or body.profile is None:
        return link.products_requested
    return products_for_profile(body.profile, body.advanced_products)


def _merge_products(*groups: list[str]) -> list[str]:
    merged: list[str] = []
    for group in groups:
        for product in group:
            if product not in merged:
                merged.append(product)
    return merged


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
      main { max-width: 1120px; margin: 0 auto; padding: 32px 20px; }
      header { display: flex; justify-content: space-between; gap: 16px; align-items: center; flex-wrap: wrap; }
      h1 { font-size: 28px; margin: 0; }
      h2 { font-size: 18px; margin: 0 0 12px; }
      section { margin-top: 24px; }
      form { display: grid; grid-template-columns: minmax(180px, 1fr) minmax(220px, 1fr) auto; gap: 12px; align-items: end; }
      label { display: grid; gap: 6px; font-size: 13px; color: color-mix(in srgb, CanvasText 78%, Canvas); }
      input, select, button { font: inherit; min-height: 38px; padding: 8px 10px; border-radius: 6px; border: 1px solid color-mix(in srgb, CanvasText 22%, Canvas); background: Canvas; color: CanvasText; }
      button { cursor: pointer; background: #276ef1; color: white; border-color: #276ef1; font-weight: 650; white-space: nowrap; }
      button.secondary { background: Canvas; color: CanvasText; border-color: color-mix(in srgb, CanvasText 24%, Canvas); }
      button.danger { background: #b42318; border-color: #b42318; color: white; }
      button:disabled { opacity: 0.6; cursor: wait; }
      .advanced { display: none; grid-column: 1 / -1; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }
      .advanced.visible { display: grid; }
      .check { display: flex; align-items: center; gap: 8px; padding: 8px 10px; border: 1px solid color-mix(in srgb, CanvasText 16%, Canvas); border-radius: 6px; color: CanvasText; }
      .check input { padding: 0; }
      .status { min-height: 22px; margin-top: 14px; color: color-mix(in srgb, CanvasText 70%, Canvas); font-size: 14px; }
      .table-wrap { overflow-x: auto; }
      table { width: 100%; min-width: 980px; border-collapse: collapse; margin-top: 12px; }
      th, td { text-align: left; padding: 10px 8px; border-bottom: 1px solid color-mix(in srgb, CanvasText 14%, Canvas); font-size: 14px; vertical-align: top; }
      th { font-size: 12px; text-transform: uppercase; color: color-mix(in srgb, CanvasText 58%, Canvas); letter-spacing: 0; }
      .name { font-weight: 700; }
      .muted { color: color-mix(in srgb, CanvasText 62%, Canvas); }
      .meta { margin-top: 3px; font-size: 12px; overflow-wrap: anywhere; }
      .pill-row { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 4px; }
      .pill { border: 1px solid color-mix(in srgb, CanvasText 16%, Canvas); border-radius: 999px; padding: 3px 8px; font-size: 12px; background: color-mix(in srgb, CanvasText 5%, Canvas); }
      .actions { display: grid; grid-template-columns: minmax(180px, 1fr) repeat(4, auto); gap: 8px; align-items: center; }
      .empty { padding: 18px 8px; color: color-mix(in srgb, CanvasText 62%, Canvas); }
      @media (max-width: 820px) {
        form { grid-template-columns: 1fr; }
        .advanced { grid-template-columns: 1fr; }
        table { min-width: 760px; }
        .actions { grid-template-columns: 1fr; }
      }
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
        <h2>Connect Institution</h2>
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
        <div id="status" class="status" role="status"></div>
      </section>
      <section>
        <h2>Active Links</h2>
        <div class="table-wrap">
          <table>
            <thead><tr><th>Institution</th><th>Access</th><th>Sync</th><th>Actions</th></tr></thead>
            <tbody id="links"></tbody>
          </table>
        </div>
      </section>
    </main>
    <script>
      const pendingKey = 'plaid-link-pending';
      const profiles = [
        ['cashflow', 'Cashflow'],
        ['credit_card_detail', 'Credit card detail'],
        ['investments_holdings', 'Investment holdings'],
        ['investments_full', 'Investments full'],
        ['full_picture', 'Full picture']
      ];
      const statusEl = document.getElementById('status');

      function setStatus(message) {
        statusEl.textContent = message || '';
      }
      function escapeHtml(value) {
        return String(value || '').replace(/[&<>"']/g, char => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[char]));
      }
      function pills(products) {
        if (!products || products.length === 0) return '<span class="muted">none recorded</span>';
        return `<div class="pill-row">${products.map(product => `<span class="pill">${escapeHtml(product)}</span>`).join('')}</div>`;
      }
      function profileSelect(link) {
        const current = link.link_profile || 'cashflow';
        return `<select data-role="scope-profile">${profiles.map(([value, label]) => `<option value="${value}" ${value === current ? 'selected' : ''}>${label}</option>`).join('')}</select>`;
      }
      async function apiFetch(url, options) {
        const response = await fetch(url, options);
        const contentType = response.headers.get('content-type') || '';
        const body = contentType.includes('application/json') ? await response.json() : await response.text();
        if (!response.ok) {
          throw new Error(apiErrorMessage(body, response));
        }
        return body;
      }
      function apiErrorMessage(body, response) {
        const detail = body && typeof body === 'object' && 'detail' in body ? body.detail : body;
        if (detail && typeof detail === 'object') {
          const bits = [];
          if (detail.error_code) bits.push(detail.error_code);
          if (detail.error_message) bits.push(detail.error_message);
          if (detail.request_id) bits.push(`request ${detail.request_id}`);
          if (bits.length) return bits.join(': ');
          return JSON.stringify(detail);
        }
        return String(detail || `${response.status} ${response.statusText}`);
      }
      async function withStatus(message, work) {
        setStatus(message);
        document.querySelectorAll('button').forEach(button => { button.disabled = true; });
        try {
          const result = await work();
          return result;
        } catch (error) {
          setStatus(error.message || String(error));
          throw error;
        } finally {
          document.querySelectorAll('button').forEach(button => { button.disabled = false; });
        }
      }

      async function refreshLinks() {
        const links = await apiFetch('/api/links');
        const tbody = document.getElementById('links');
        tbody.innerHTML = '';
        if (links.length === 0) {
          tbody.innerHTML = '<tr><td class="empty" colspan="4">No active Plaid links.</td></tr>';
          return;
        }
        for (const link of links) {
          const tr = document.createElement('tr');
          tr.dataset.item = link.item_id;
          tr.innerHTML = `
            <td>
              <div class="name">${escapeHtml(link.label || link.institution_name || link.item_id)}</div>
              <div class="muted">${escapeHtml(link.institution_name || '')}</div>
              <div class="meta muted">${escapeHtml(link.item_id)}</div>
              <div class="meta">Status: ${escapeHtml(link.status)}</div>
            </td>
            <td>
              <div>Requested ${pills(link.products_requested)}</div>
              <div class="meta muted">Authorized ${pills(link.products_authorized)}</div>
              <div class="meta muted">Billed ${pills(link.products_billed)}</div>
            </td>
            <td>
              <div>${escapeHtml(link.last_synced_at || 'not synced yet')}</div>
              <div class="meta muted">Secret: ${escapeHtml(link.access_token_secret)}</div>
            </td>
            <td>
              <div class="actions">
                ${profileSelect(link)}
                <button class="secondary" data-action="update">Add scopes</button>
                <button class="secondary" data-action="repair">Repair</button>
                <button class="secondary" data-action="sync">Sync</button>
                <button class="danger" data-action="remove">Remove</button>
              </div>
            </td>`;
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
        await apiFetch('/api/exchange-public-token', {
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
        setStatus('Link connected and synced.');
      }
      async function completeUpdate(metadata, pending) {
        await apiFetch(`/api/links/${encodeURIComponent(pending.item_id)}/complete-update`, {
          method: 'POST',
          headers: {'content-type': 'application/json'},
          body: JSON.stringify({profile: pending.profile, products: pending.products, sync: true})
        });
        sessionStorage.removeItem(pendingKey);
        await refreshLinks();
        setStatus(metadata?.institution?.name ? `Updated ${metadata.institution.name}.` : 'Link updated and synced.');
      }
      function openPlaid(pending, receivedRedirectUri) {
        const handler = Plaid.create({
          token: pending.link_token,
          receivedRedirectUri,
          onSuccess: async (public_token, metadata) => {
            if (pending.mode === 'update') {
              await completeUpdate(metadata, pending);
            } else {
              await exchangePublicToken(public_token, metadata, pending);
            }
          },
          onExit: (error) => {
            if (error) setStatus(error.display_message || error.error_message || 'Plaid Link exited with an error.');
          }
        });
        handler.open();
      }
      document.getElementById('links').addEventListener('click', async (event) => {
        const button = event.target.closest('button[data-action]');
        if (!button) return;
        const row = button.closest('tr[data-item]');
        const item = row?.dataset?.item;
        const action = button.dataset.action;
        if (!item || !action) return;
        if (action === 'remove') {
          if (!window.confirm('Remove this Plaid link and delete its access-token Secret?')) return;
          await withStatus('Removing link...', async () => {
            await apiFetch(`/api/links/${encodeURIComponent(item)}/remove`, {method: 'POST'});
            await refreshLinks();
            setStatus('Link removed.');
          });
          return;
        }
        if (action === 'sync') {
          await withStatus('Syncing link...', async () => {
            const result = await apiFetch(`/api/links/${encodeURIComponent(item)}/sync`, {method: 'POST'});
            await refreshLinks();
            setStatus(`Sync completed: ${result.run_id}`);
          });
          return;
        }
        const body = action === 'repair'
          ? {reason: 'repair'}
          : {reason: 'add_scope', profile: row.querySelector('[data-role="scope-profile"]').value};
        await withStatus(action === 'repair' ? 'Opening Plaid repair flow...' : 'Opening Plaid scope request...', async () => {
          const token = await apiFetch(`/api/links/${encodeURIComponent(item)}/update-link-token`, {
            method: 'POST',
            headers: {'content-type': 'application/json'},
            body: JSON.stringify(body)
          });
          const pending = {
            mode: 'update',
            item_id: item,
            profile: body.profile || null,
            products: token.products,
            link_token: token.link_token
          };
          sessionStorage.setItem(pendingKey, JSON.stringify(pending));
          openPlaid(pending);
        });
      });
      document.getElementById('profile').addEventListener('change', setAdvancedVisibility);
      document.getElementById('link-form').addEventListener('submit', async (event) => {
        event.preventDefault();
        await withStatus('Creating Plaid Link session...', async () => {
          const profile = document.getElementById('profile').value;
          const label = document.getElementById('label').value || null;
          const advanced_products = profile === 'advanced' ? advancedProducts() : null;
          const token = await apiFetch('/api/link-token', {method: 'POST', headers: {'content-type': 'application/json'}, body: JSON.stringify({profile, advanced_products})});
          const pending = {mode: 'new', profile, products: token.products, label, link_token: token.link_token};
          sessionStorage.setItem(pendingKey, JSON.stringify(pending));
          openPlaid(pending);
        });
      });
      setAdvancedVisibility();
      refreshLinks();
      const pending = JSON.parse(sessionStorage.getItem(pendingKey) || 'null');
      if (pending && new URLSearchParams(window.location.search).has('oauth_state_id')) {
        setStatus('Completing Plaid redirect...');
        openPlaid(pending, window.location.href);
      }
    </script>
  </body>
</html>
"""


if __name__ == "__main__":
    main()
