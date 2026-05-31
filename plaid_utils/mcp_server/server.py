"""Plaid MCP server: read-only transactions, balances, and liabilities.

Auth-oblivious by design — a front proxy (`mcp-oauth-facade`) handles Authentik OAuth;
this server only speaks MCP over HTTP on its configured port. One server holds every
configured item's access token; tools take an `item` selector.

Tools call the plaid-python SDK client directly, run its responses through
`sanitize_for_serialization`, and validate them into the typed `plaid_utils.models` shapes
(the models already cover only the fields we expose). The SDK's `ApiException` propagates
to FastMCP's error boundary, which surfaces Plaid's message (PRODUCT_NOT_READY,
ITEM_LOGIN_REQUIRED, RATE_LIMIT_EXCEEDED, ...) to the agent.
"""

import logging
import sys
from datetime import date, timedelta
from typing import Annotated, Protocol

import uvicorn
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from plaid.model.accounts_balance_get_request import AccountsBalanceGetRequest
from plaid.model.accounts_balance_get_request_options import AccountsBalanceGetRequestOptions
from plaid.model.accounts_get_request import AccountsGetRequest
from plaid.model.liabilities_get_request import LiabilitiesGetRequest
from plaid.model.transactions_get_request import TransactionsGetRequest
from plaid.model.transactions_get_request_options import TransactionsGetRequestOptions
from pydantic import BaseModel, Field

from plaid_utils.client import PlaidCreds, plaid_client
from plaid_utils.mcp_server.config import ResolvedItem, ServerSettings
from plaid_utils.models import (
    Account,
    AccountsGetResponse,
    Liabilities,
    LiabilitiesGetResponse,
    TransactionPage,
    TransactionsGetResponse,
)

logger = logging.getLogger(__name__)


class ItemSummary(BaseModel):
    """list_items output: a configured item without its access token."""

    key: str
    institution: str
    products: list[str]


class ItemHistoryWindow(BaseModel):
    """Probed transaction-history depth for an item."""

    earliest_date: date | None = Field(
        description="Earliest transaction date Plaid has, or null if none in the 730d window."
    )
    latest_date: date | None = Field(
        description="Latest transaction date Plaid has, or null if none in the 730d window."
    )
    total_transactions: int = Field(description="Total transactions Plaid has in the last 730 days.")


class PlaidApiClientLike(Protocol):
    """The generated SDK's nested ApiClient serializer."""

    def sanitize_for_serialization(self, obj: object) -> object: ...


class PlaidApiLike(Protocol):
    """The slice of `plaid_api.PlaidApi` the server uses, so tests can inject a fake."""

    api_client: PlaidApiClientLike

    def accounts_get(self, request: AccountsGetRequest, /) -> object: ...
    def accounts_balance_get(self, request: AccountsBalanceGetRequest, /) -> object: ...
    def transactions_get(self, request: TransactionsGetRequest, /) -> object: ...
    def liabilities_get(self, request: LiabilitiesGetRequest, /) -> object: ...


INSTRUCTIONS = (
    "Read-only access to the owner's Plaid-linked bank accounts: transactions, balances, and "
    "liabilities (credit cards, mortgages, student loans). Call list_items first to discover the "
    "`item` selectors and which products each supports. Transaction amount sign: positive = money "
    "out (charges/debits), negative = money in (payments/refunds/deposits). Each item has a finite "
    "transaction-history depth set at link time (Plaid default 90 days, max 730) — before issuing "
    "wide date-range queries, call get_item_history_window so you don't mistake a short window for "
    "missing data."
)

_ItemArg = Annotated[str, Field(description="Item selector from list_items, e.g. 'chase' or 'bofa'.")]


def build_server(api: PlaidApiLike, items: dict[str, ResolvedItem]) -> FastMCP:
    mcp: FastMCP = FastMCP("Plaid MCP", instructions=INSTRUCTIONS)
    sanitize = api.api_client.sanitize_for_serialization

    def resolve(item: str) -> ResolvedItem:
        resolved = items.get(item)
        if resolved is None:
            raise ToolError(f"Unknown item {item!r}. Valid items: {sorted(items)}.")
        return resolved

    @mcp.tool
    def list_items() -> list[ItemSummary]:
        """List the configured Plaid items.

        Call this first: each `key` is a valid `item` argument for the other tools, and only
        items whose `products` include 'liabilities' accept get_liabilities.
        """
        return [ItemSummary(key=i.key, institution=i.institution, products=i.products) for i in items.values()]

    @mcp.tool
    def list_accounts(item: _ItemArg) -> list[Account]:
        """Accounts for an item with CACHED balances.

        Balances reflect Plaid's last pull (refreshed 1-4x/day); use get_live_balance for a
        real-time figure. The returned account_id values feed the filters on the other tools.
        """
        resp = api.accounts_get(AccountsGetRequest(access_token=resolve(item).access_token))
        return AccountsGetResponse.model_validate(sanitize(resp)).accounts

    @mcp.tool
    def list_transactions(
        item: _ItemArg,
        start_date: Annotated[date, Field(description="Inclusive start date.")],
        end_date: Annotated[date, Field(description="Inclusive end date.")],
        account_id: Annotated[
            str | None, Field(description="Restrict to one account_id (from list_accounts); omit for all accounts.")
        ] = None,
        offset: Annotated[int, Field(description="Pagination offset within the date range.", ge=0)] = 0,
        count: Annotated[int, Field(description="Page size.", ge=1, le=500)] = 50,
    ) -> TransactionPage:
        """Transactions in [start_date, end_date] (inclusive), paged with offset/count.

        Backed by /transactions/get. `total` is the full count in the range before slicing, so
        page until offset+count >= total. Amount sign: positive = money out (charges/debits),
        negative = money in (payments/refunds/deposits). A pending=true row is later replaced by
        a posted row whose pending_transaction_id points back to the pending id (dedupe on it).
        Recently linked/refreshed items can briefly raise PRODUCT_NOT_READY.

        History depth is capped per item at link time (Plaid default 90 days, max 730). Dates
        before that window return empty results — not an error. Call get_item_history_window
        first if you need to know the actual span before issuing wide range queries.
        """
        options = TransactionsGetRequestOptions(offset=offset, count=count)
        if account_id is not None:
            options.account_ids = [account_id]
        resp = api.transactions_get(
            TransactionsGetRequest(
                access_token=resolve(item).access_token, start_date=start_date, end_date=end_date, options=options
            )
        )
        parsed = TransactionsGetResponse.model_validate(sanitize(resp))
        return TransactionPage(total=parsed.total_transactions, transactions=parsed.transactions)

    @mcp.tool
    def get_item_history_window(item: _ItemArg) -> ItemHistoryWindow:
        """Earliest/latest transaction dates Plaid has for this item, probed over 730 days.

        Plaid records transactions.days_requested per item at link time (default 90 days,
        max 730); requesting list_transactions for dates before earliest_date returns empty
        results, not an error. Call this before issuing wide range queries so you don't
        mistake a short history window for missing data. Cost: 2 /transactions/get calls.
        """
        access_token = resolve(item).access_token
        end = date.today()
        start = end - timedelta(days=730)

        def probe(offset: int) -> TransactionsGetResponse:
            resp = api.transactions_get(
                TransactionsGetRequest(
                    access_token=access_token,
                    start_date=start,
                    end_date=end,
                    options=TransactionsGetRequestOptions(offset=offset, count=1),
                )
            )
            return TransactionsGetResponse.model_validate(sanitize(resp))

        latest = probe(0)
        total = latest.total_transactions
        if total == 0:
            return ItemHistoryWindow(earliest_date=None, latest_date=None, total_transactions=0)
        # /transactions/get returns rows sorted by date descending, so offset=total-1 is oldest.
        earliest = probe(total - 1) if total > 1 else latest
        return ItemHistoryWindow(
            earliest_date=date.fromisoformat(earliest.transactions[0].date),
            latest_date=date.fromisoformat(latest.transactions[0].date),
            total_transactions=total,
        )

    @mcp.tool
    def get_liabilities(item: _ItemArg) -> Liabilities:
        """Liabilities for an item: `credit` cards, `mortgage`s, and `student` loans.

        Backed by /liabilities/get. Each array is null when the item has no accounts of that
        type (e.g. a card-only item returns mortgage=null, student=null). Valid only for items
        whose products include 'liabilities' (see list_items). Most fields are nullable and
        issuer-dependent — e.g. a credit card's `aprs` is often empty. Each entry carries an
        account_id; correlate with list_accounts for the account name/mask.
        """
        resolved = resolve(item)
        if "liabilities" not in resolved.products:
            raise ToolError(
                f"Item {resolved.key!r} has no 'liabilities' product (products: {resolved.products}). "
                "Use list_items to see which items support liabilities."
            )
        resp = api.liabilities_get(LiabilitiesGetRequest(access_token=resolved.access_token))
        return LiabilitiesGetResponse.model_validate(sanitize(resp)).liabilities

    @mcp.tool
    def get_live_balance(
        item: _ItemArg,
        account_id: Annotated[
            str | None,
            Field(description="Restrict to one account_id to conserve the per-item rate budget; omit for all."),
        ] = None,
    ) -> list[Account]:
        """Real-time balances via /accounts/balance/get (hits the bank, uncached).

        Heavily rate-limited: 5/min and 30/hour per item. Prefer list_accounts (cached) for
        routine reads; pass account_id to fetch a single account and conserve the budget.
        """
        request = AccountsBalanceGetRequest(access_token=resolve(item).access_token)
        if account_id is not None:
            request.options = AccountsBalanceGetRequestOptions(account_ids=[account_id])
        resp = api.accounts_balance_get(request)
        return AccountsGetResponse.model_validate(sanitize(resp)).accounts

    return mcp


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s", stream=sys.stderr)
    settings = ServerSettings()
    items = settings.resolved_items()
    api = plaid_client(PlaidCreds(client_id=settings.client_id, secret=settings.client_secret, env=settings.plaid_env))
    mcp = build_server(api, items)
    logger.info("plaid-mcp listening on %s:%d (items: %s)", settings.host, settings.port, sorted(items))
    uvicorn.run(mcp.http_app(path="/mcp"), host=settings.host, port=settings.port, log_level="info")


if __name__ == "__main__":
    main()
