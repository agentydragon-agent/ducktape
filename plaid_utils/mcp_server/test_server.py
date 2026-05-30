"""End-to-end tool tests via an in-memory FastMCP client (FakePlaidApi, no network)."""

from typing import Any

import pytest
import pytest_bazel
from fastmcp.client import Client
from fastmcp.exceptions import ToolError

from plaid_utils.mcp_server.config import ResolvedItem
from plaid_utils.mcp_server.conftest import FakePlaidApi
from plaid_utils.mcp_server.server import build_server


def unwrap(result: Any) -> Any:
    """Structured content of a CallToolResult, unwrapping FastMCP's {'result': ...} list wrapper."""
    sc = result.structured_content
    assert sc is not None, "no structured_content in CallToolResult"
    if isinstance(sc, dict) and len(sc) == 1 and "result" in sc:
        return sc["result"]
    return sc


async def test_list_items_lists_configured_items(client: Client) -> None:
    items = unwrap(await client.call_tool("list_items", {}))
    assert {i["key"] for i in items} == {"chase", "bofa"}
    chase = next(i for i in items if i["key"] == "chase")
    assert "liabilities" in chase["products"]


async def test_list_accounts_returns_balances(client: Client) -> None:
    accounts = unwrap(await client.call_tool("list_accounts", {"item": "chase"}))
    by_id = {a["account_id"]: a for a in accounts}
    assert set(by_id) == {"acc_cc", "acc_chk"}
    assert by_id["acc_cc"]["balances"]["limit"] == 10000.0


async def test_list_transactions_paginates_within_range(client: Client) -> None:
    page = unwrap(
        await client.call_tool(
            "list_transactions",
            {"item": "chase", "start_date": "2026-05-01", "end_date": "2026-05-31", "offset": 1, "count": 2},
        )
    )
    # total is the full in-range count (5) before offset/count slicing.
    assert page["total"] == 5
    assert [t["transaction_id"] for t in page["transactions"]] == ["txn_1", "txn_2"]
    assert page["transactions"][0]["amount"] == 11.0
    assert page["transactions"][0]["personal_finance_category"]["primary"] == "FOOD_AND_DRINK"


async def test_get_liabilities(client: Client) -> None:
    liabilities = unwrap(await client.call_tool("get_liabilities", {"item": "chase"}))
    # Card-only item: mortgage/student arrays are null.
    assert liabilities["mortgage"] is None
    assert liabilities["student"] is None
    cards = liabilities["credit"]
    assert len(cards) == 1
    assert cards[0]["account_id"] == "acc_cc"
    assert cards[0]["last_statement_balance"] == 1543.21
    assert cards[0]["aprs"][0]["apr_type"] == "purchase_apr"


async def test_liabilities_rejects_item_without_product(client: Client) -> None:
    # bofa is configured without the 'liabilities' product.
    with pytest.raises(ToolError):
        await client.call_tool("get_liabilities", {"item": "bofa"})


async def test_unknown_item_raises(client: Client) -> None:
    with pytest.raises(ToolError):
        await client.call_tool("list_accounts", {"item": "nope"})


async def test_get_item_history_window_returns_oldest_and_newest(client: Client) -> None:
    # Fixture has 5 transactions all dated 2026-05-20; probing both ends should agree.
    window = unwrap(await client.call_tool("get_item_history_window", {"item": "chase"}))
    assert window == {"earliest_date": "2026-05-20", "latest_date": "2026-05-20", "total_transactions": 5}


async def test_get_item_history_window_empty_returns_nulls(items: dict[str, ResolvedItem]) -> None:
    empty_api = FakePlaidApi(accounts=[], transactions=[], credit=[])
    async with Client(build_server(empty_api, items)) as connected:
        window = unwrap(await connected.call_tool("get_item_history_window", {"item": "chase"}))
    assert window == {"earliest_date": None, "latest_date": None, "total_transactions": 0}


if __name__ == "__main__":
    pytest_bazel.main()
