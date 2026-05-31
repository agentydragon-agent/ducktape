import json

import httpx
import pytest_bazel

from plaid_utils.link_profiles import LinkProfile
from plaid_utils.plaid_link import PlaidLinkClient, PlaidLinkCreds


async def test_create_link_token_initializes_requested_products() -> None:
    requests: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"link_token": "link-sandbox-new"})

    client = PlaidLinkClient(
        PlaidLinkCreds(client_id="client", secret="secret", env="sandbox"), transport=httpx.MockTransport(handler)
    )

    result = await client.create_link_token(
        profile=LinkProfile.CREDIT_CARD_DETAIL,
        redirect_uri="https://example.test/link/callback",
        client_user_id="owner",
    )

    assert result.products == ["transactions", "liabilities"]
    assert requests == [
        {
            "client_id": "client",
            "secret": "secret",
            "client_name": "Plaid MCP",
            "user": {"client_user_id": "owner"},
            "products": ["transactions", "liabilities"],
            "country_codes": ["US"],
            "language": "en",
            "redirect_uri": "https://example.test/link/callback",
            "transactions": {"days_requested": 730},
        }
    ]


async def test_create_update_link_token_requests_additional_consented_products_only() -> None:
    requests: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"link_token": "link-sandbox-update"})

    client = PlaidLinkClient(
        PlaidLinkCreds(client_id="client", secret="secret", env="sandbox"), transport=httpx.MockTransport(handler)
    )

    result = await client.create_update_link_token(
        access_token="access-sandbox-existing",
        redirect_uri="https://example.test/link/callback",
        client_user_id="owner",
        additional_products=["investments"],
    )

    assert result.products == ["investments"]
    assert requests == [
        {
            "client_id": "client",
            "secret": "secret",
            "client_name": "Plaid MCP",
            "user": {"client_user_id": "owner"},
            "country_codes": ["US"],
            "language": "en",
            "redirect_uri": "https://example.test/link/callback",
            "access_token": "access-sandbox-existing",
            "additional_consented_products": ["investments"],
        }
    ]
    assert "products" not in requests[0]
    assert "transactions" not in requests[0]


if __name__ == "__main__":
    pytest_bazel.main()
