"""Unit tests for retry safety and QU validation in batch_tools.

These tests mock the httpx client to verify:
- Mutating POSTs are never re-executed after they succeed (even when follow-up GET fails)
- Legitimate retries work when the POST itself fails transiently
- QU validation rejects mismatched units
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_bazel
from fastmcp import FastMCP
from fastmcp.client import Client
from fastmcp.client.transports import FastMCPTransport

from x.grocy_mcp.batch_tools import register_batch_tools
from x.grocy_mcp.config import ServerSettings


def _settings() -> ServerSettings:
    return ServerSettings(
        oidc_issuer="https://auth.example.com/application/o/test/",
        oidc_client_id="unused",
        oidc_client_secret="unused",
        public_base_url="https://test.example.com",
        grocy_url="https://grocy.example.com",
        grocy_proxy_client_id="unused",
        max_retries=2,
        retry_base_delay=0.01,
    )


def _make_response(status_code: int, json_data: object = None) -> httpx.Response:
    """Build a fake httpx.Response."""
    return httpx.Response(status_code=status_code, json=json_data, request=httpx.Request("GET", "https://fake"))


PRODUCT_DATA = {"id": 1, "name": "TestProduct", "qu_id_stock": 1, "location_id": 1}

QU_LIST = [{"id": 1, "name": "pieces"}, {"id": 2, "name": "grams"}]

ADD_RESPONSE = [{"transaction_id": "tx-123", "amount": 5}]
STOCK_RESPONSE = {"stock_amount": 5}


@pytest.fixture
def mock_http_client() -> AsyncMock:
    """Mock httpx.AsyncClient for Grocy API calls."""
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.base_url = httpx.URL("https://grocy.example.com/api")
    return mock_client


@pytest.fixture
async def mcp_client(mock_http_client: AsyncMock) -> AsyncGenerator[Client]:
    """MCP client backed by the mock httpx client."""
    mcp = FastMCP("test")
    register_batch_tools(mcp, mock_http_client, _settings())

    async with Client(FastMCPTransport(mcp)) as client:
        yield client


def _setup_mock_responses(mock_client: AsyncMock, post_responses: list[httpx.Response]) -> None:
    """Configure mock to return specific responses for POST (mutation) and GET (reads)."""
    post_call_count = 0

    async def _mock_get(url: str, **_kw: object) -> httpx.Response:
        if "/objects/quantity_units" in url:
            return _make_response(200, QU_LIST)
        if "/objects/products/" in url:
            return _make_response(200, PRODUCT_DATA)
        if "/stock/products/" in url:
            return _make_response(200, STOCK_RESPONSE)
        return _make_response(404)

    async def _mock_post(url: str, **_kw: object) -> httpx.Response:
        nonlocal post_call_count
        if "/objects/quantity_units" in url:
            return _make_response(200, QU_LIST)
        if "/objects/products/" in url:
            return _make_response(200, PRODUCT_DATA)
        if "/stock/products/" in url and "/add" in url:
            resp = post_responses[min(post_call_count, len(post_responses) - 1)]
            post_call_count += 1
            return resp
        return _make_response(404)

    mock_client.get = AsyncMock(side_effect=_mock_get)
    mock_client.post = AsyncMock(side_effect=_mock_post)


def _setup_mock_with_get_failure(mock_client: AsyncMock) -> None:
    """POST succeeds, but the follow-up GET (for new_amount) returns 500."""
    call_log: list[tuple[str, str]] = []

    async def _mock_get(url: str, **_kw: object) -> httpx.Response:
        call_log.append(("GET", url))
        if "/objects/quantity_units" in url:
            return _make_response(200, QU_LIST)
        if "/objects/products/" in url:
            return _make_response(200, PRODUCT_DATA)
        if "/stock/products/" in url:
            # Simulate GET failure for new_amount read
            return _make_response(500)
        return _make_response(404)

    async def _mock_post(url: str, **_kw: object) -> httpx.Response:
        call_log.append(("POST", url))
        if "/add" in url:
            return _make_response(200, ADD_RESPONSE)
        return _make_response(404)

    mock_client.get = AsyncMock(side_effect=_mock_get)
    mock_client.post = AsyncMock(side_effect=_mock_post)
    mock_client._call_log = call_log


async def test_add_stock_post_not_retried_when_get_fails(mcp_client: Client, mock_http_client: AsyncMock) -> None:
    """POST succeeds on first try, GET fails → POST must NOT be retried."""
    _setup_mock_with_get_failure(mock_http_client)

    result = await mcp_client.call_tool("add_stock", {"items": [{"product_id": 1, "amount": 5, "qu_name": "pieces"}]})
    sc = result.structured_content
    assert sc is not None
    op = sc["result"][0]
    assert op["kind"] == "ok", f"expected ok, got: {op}"
    # new_amount should be None because GET failed
    assert op["new_amount"] is None
    assert op["qu_name"] == "pieces"

    # Verify POST was called exactly once (not retried due to GET failure)
    post_calls = [(method, url) for method, url in mock_http_client._call_log if method == "POST" and "/add" in url]
    assert len(post_calls) == 1, f"POST /add called {len(post_calls)} times, expected 1"


async def test_add_stock_post_retried_on_transient_failure(mcp_client: Client, mock_http_client: AsyncMock) -> None:
    """POST fails with 500 then succeeds → POST should be retried (legitimate)."""
    _setup_mock_responses(
        mock_http_client,
        [
            _make_response(500),  # first attempt fails
            _make_response(200, ADD_RESPONSE),  # retry succeeds
        ],
    )

    result = await mcp_client.call_tool("add_stock", {"items": [{"product_id": 1, "amount": 5, "qu_name": "pieces"}]})
    sc = result.structured_content
    assert sc is not None
    op = sc["result"][0]
    assert op["kind"] == "ok", f"expected ok, got: {op}"
    assert op["new_amount"] == 5.0


async def test_unit_validation_rejects_wrong_qu(mcp_client: Client, mock_http_client: AsyncMock) -> None:
    """Specifying the wrong QU name should fail validation."""
    _setup_mock_responses(mock_http_client, [_make_response(200, ADD_RESPONSE)])

    result = await mcp_client.call_tool("add_stock", {"items": [{"product_id": 1, "amount": 5, "qu_name": "grams"}]})
    sc = result.structured_content
    assert sc is not None
    op = sc["result"][0]
    assert op["kind"] == "error", f"expected error for wrong QU, got: {op}"
    assert "pieces" in op["error"], "error should mention the expected QU"


async def test_unit_validation_rejects_missing_qu(mcp_client: Client) -> None:
    """Omitting both qu_id and qu_name should fail Pydantic validation."""
    # FastMCP raises on input validation failure rather than returning an error result
    with pytest.raises(Exception, match="qu_id or qu_name"):
        await mcp_client.call_tool("add_stock", {"items": [{"product_id": 1, "amount": 5}]})


if __name__ == "__main__":
    pytest_bazel.main()
