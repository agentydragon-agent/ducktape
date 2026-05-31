from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast

import pytest_bazel
from fastapi.testclient import TestClient
from plaid.model.accounts_get_request import AccountsGetRequest
from plaid.model.investments_holdings_get_request import InvestmentsHoldingsGetRequest
from plaid.model.investments_transactions_get_request import InvestmentsTransactionsGetRequest
from plaid.model.item_get_request import ItemGetRequest
from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
from plaid.model.item_remove_request import ItemRemoveRequest
from plaid.model.liabilities_get_request import LiabilitiesGetRequest
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.transactions_get_request import TransactionsGetRequest

from plaid_utils.link_profiles import LinkProfile
from plaid_utils.link_store import PlaidLinkStorage, StoredLink
from plaid_utils.mcp_server.app import (
    PlaidWebApi,
    PlaidWebSettings,
    _create_link_token,
    _create_update_link_token,
    _exchange_public_token,
    _remove_item,
    create_app,
)


class _FakeStorage:
    async def list_active_links(self) -> list[StoredLink]:
        return [
            StoredLink(
                item_id="item_123",
                label="Chase personal",
                institution_id="ins_3",
                institution_name="Chase",
                link_profile=LinkProfile.CREDIT_CARD_DETAIL,
                products_requested=["transactions", "liabilities"],
                products_authorized=["transactions"],
                products_billed=[],
                status="active",
                access_token_secret="plaid-item-123-access-token",
                last_synced_at=datetime(2026, 5, 31, 12, 0, tzinfo=UTC),
            )
        ]


class _FakeSecrets:
    async def read_access_token(self, secret_name: str) -> str:
        raise AssertionError(f"unexpected secret read in smoke test: {secret_name}")

    async def write_access_token(self, secret_name: str, access_token: str) -> None:
        raise AssertionError(f"unexpected secret write in smoke test: {secret_name}")

    async def delete_access_token(self, secret_name: str) -> None:
        raise AssertionError(f"unexpected secret delete in smoke test: {secret_name}")


class _FakePlaidApi:
    api_client = object()

    def __init__(self) -> None:
        self.link_token_requests: list[dict[str, object]] = []
        self.exchanged_public_tokens: list[str] = []
        self.removed_access_tokens: list[str] = []

    def link_token_create(self, request: LinkTokenCreateRequest) -> SimpleNamespace:
        self.link_token_requests.append(request.to_dict())
        return SimpleNamespace(link_token=f"link-token-{len(self.link_token_requests)}")

    def item_public_token_exchange(self, request: ItemPublicTokenExchangeRequest) -> SimpleNamespace:
        self.exchanged_public_tokens.append(request.public_token)
        return SimpleNamespace(access_token="access-sandbox-new", item_id="item-sandbox-new")

    def item_remove(self, request: ItemRemoveRequest) -> object:
        self.removed_access_tokens.append(request.access_token)
        return object()

    def item_get(self, request: ItemGetRequest) -> object:
        raise AssertionError("unexpected sync call in smoke test")

    def accounts_get(self, request: AccountsGetRequest) -> object:
        raise AssertionError("unexpected sync call in smoke test")

    def transactions_get(self, request: TransactionsGetRequest) -> object:
        raise AssertionError("unexpected sync call in smoke test")

    def investments_holdings_get(self, request: InvestmentsHoldingsGetRequest) -> object:
        raise AssertionError("unexpected sync call in smoke test")

    def investments_transactions_get(self, request: InvestmentsTransactionsGetRequest) -> object:
        raise AssertionError("unexpected sync call in smoke test")

    def liabilities_get(self, request: LiabilitiesGetRequest) -> object:
        raise AssertionError("unexpected sync call in smoke test")


def _client() -> TestClient:
    settings = PlaidWebSettings(
        plaid_env="sandbox",
        client_id="client-id",
        client_secret="client-secret",
        DATABASE_URL="postgresql://example.invalid/plaid",
        target_namespace="plaid-mcp",
    )
    return TestClient(
        create_app(
            settings,
            storage=cast(PlaidLinkStorage, _FakeStorage()),
            secrets=_FakeSecrets(),
            api=cast(PlaidWebApi, _FakePlaidApi()),
        )
    )


def test_link_ui_exposes_management_actions() -> None:
    with _client() as client:
        response = client.get("/link")
        root_response = client.get("/")

    assert response.status_code == 200
    assert root_response.status_code == 200
    assert "Connect Institution" in response.text
    assert "Connect Institution" in root_response.text
    assert "Active Links" in response.text
    assert "Add scopes" in response.text
    assert "Repair" in response.text
    assert "Sync" in response.text
    assert "Remove" in response.text


def test_list_links_exposes_product_and_secret_state() -> None:
    with _client() as client:
        response = client.get("/api/links")

    assert response.status_code == 200
    assert response.json() == [
        {
            "item_id": "item_123",
            "label": "Chase personal",
            "institution_id": "ins_3",
            "institution_name": "Chase",
            "link_profile": "credit_card_detail",
            "products_requested": ["transactions", "liabilities"],
            "products_authorized": ["transactions"],
            "products_billed": [],
            "status": "active",
            "access_token_secret": "plaid-item-123-access-token",
            "last_synced_at": "2026-05-31T12:00:00+00:00",
        }
    ]


def test_create_link_token_initializes_requested_products() -> None:
    api = _FakePlaidApi()

    result = _create_link_token(
        cast(PlaidWebApi, api),
        profile=LinkProfile.CREDIT_CARD_DETAIL,
        redirect_uri="https://example.test/link/callback",
        client_user_id="owner",
    )

    assert result.link_token == "link-token-1"
    assert result.products == ["transactions", "liabilities"]
    assert api.link_token_requests == [
        {
            "client_name": "Plaid MCP",
            "country_codes": ["US"],
            "language": "en",
            "products": ["transactions", "liabilities"],
            "redirect_uri": "https://example.test/link/callback",
            "transactions": {"days_requested": 730},
            "user": {"client_user_id": "owner"},
        }
    ]


def test_create_update_link_token_requests_additional_consented_products_only() -> None:
    api = _FakePlaidApi()

    result = _create_update_link_token(
        cast(PlaidWebApi, api),
        access_token="access-sandbox-existing",
        redirect_uri="https://example.test/link/callback",
        client_user_id="owner",
        additional_products=["investments"],
    )

    assert result.link_token == "link-token-1"
    assert result.products == ["investments"]
    assert api.link_token_requests == [
        {
            "access_token": "access-sandbox-existing",
            "additional_consented_products": ["investments"],
            "client_name": "Plaid MCP",
            "country_codes": ["US"],
            "language": "en",
            "redirect_uri": "https://example.test/link/callback",
            "user": {"client_user_id": "owner"},
        }
    ]
    assert "products" not in api.link_token_requests[0]
    assert "transactions" not in api.link_token_requests[0]


def test_exchange_public_token_uses_sdk_request() -> None:
    api = _FakePlaidApi()

    result = _exchange_public_token(cast(PlaidWebApi, api), "public-sandbox-token")

    assert api.exchanged_public_tokens == ["public-sandbox-token"]
    assert result.access_token == "access-sandbox-new"
    assert result.item_id == "item-sandbox-new"


def test_remove_item_uses_sdk_request() -> None:
    api = _FakePlaidApi()

    _remove_item(cast(PlaidWebApi, api), "access-sandbox-existing")

    assert api.removed_access_tokens == ["access-sandbox-existing"]


if __name__ == "__main__":
    pytest_bazel.main()
