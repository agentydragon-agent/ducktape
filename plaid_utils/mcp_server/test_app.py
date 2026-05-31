from datetime import UTC, datetime
from typing import cast

import pytest_bazel
from fastapi.testclient import TestClient

from plaid_utils.link_profiles import LinkProfile
from plaid_utils.link_store import PlaidLinkStorage, StoredLink
from plaid_utils.mcp_server.app import PlaidWebSettings, create_app


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


def _client() -> TestClient:
    settings = PlaidWebSettings(
        plaid_env="sandbox",
        client_id="client-id",
        client_secret="client-secret",
        DATABASE_URL="postgresql://example.invalid/plaid",
        target_namespace="plaid-mcp",
    )
    return TestClient(create_app(settings, storage=cast(PlaidLinkStorage, _FakeStorage()), secrets=_FakeSecrets()))


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


if __name__ == "__main__":
    pytest_bazel.main()
