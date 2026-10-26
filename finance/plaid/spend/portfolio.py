"""Read a current USD portfolio from the Plaid mirror and optional Coinbase."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

import asyncpg
import httpx
import jwt
from pydantic import BaseModel, ConfigDict, SecretStr, ValidationError

from finance.plaid.spend.portfolio_models import PortfolioPolicy, PortfolioView, SourceValuation

_ACCOUNT_BALANCES_SQL = """
WITH selected_accounts AS (
    SELECT a.account_id, a.item_id, a.type, a.iso_currency_code AS account_currency
    FROM accounts AS a
    JOIN links AS l ON l.item_id = a.item_id
    WHERE a.account_id = ANY($1::text[])
      AND a.detached_at IS NULL
      AND l.status = 'active'
), latest_balances AS (
    SELECT DISTINCT ON (b.account_id)
           b.account_id, b.item_id, b.current, b.iso_currency_code AS balance_currency, b.captured_at
    FROM balance_snapshots AS b
    JOIN selected_accounts AS a ON a.account_id = b.account_id AND a.item_id = b.item_id
    ORDER BY b.account_id, b.captured_at DESC, b.id DESC
)
SELECT a.account_id, a.type AS account_type, a.account_currency,
       b.current, b.balance_currency, b.captured_at
FROM selected_accounts AS a
LEFT JOIN latest_balances AS b ON b.account_id = a.account_id
"""

_EXCLUDED_HOLDINGS_SQL = """
WITH latest_holding_batches AS (
    SELECT h.account_id, MAX(h.captured_at) AS captured_at
    FROM holding_snapshots AS h
    JOIN accounts AS a ON a.account_id = h.account_id
    JOIN links AS l ON l.item_id = h.item_id
    WHERE h.account_id = ANY($1::text[])
      AND a.detached_at IS NULL
      AND l.status = 'active'
    GROUP BY h.account_id
)
SELECT h.account_id, h.security_id, h.captured_at, h.institution_value,
       h.iso_currency_code AS holding_currency
FROM holding_snapshots AS h
JOIN latest_holding_batches AS b
  ON b.account_id = h.account_id
 AND b.captured_at = h.captured_at
WHERE h.account_id = ANY($1::text[])
ORDER BY h.account_id, h.security_id, h.id DESC
"""

_COINBASE_HOST = "api.coinbase.com"
_COINBASE_ACCOUNTS_PATH = "/api/v3/brokerage/accounts"
_COINBASE_ACCOUNTS_URL = f"https://{_COINBASE_HOST}{_COINBASE_ACCOUNTS_PATH}"
_COINBASE_PRICE_URL = "https://api.coinbase.com/v2/prices/{asset}-USD/spot"
_USD_MINOR_UNITS = Decimal(100)
_ASSET_CODE = re.compile(r"^[A-Z0-9]{2,20}$")


class _CoinbaseMoney(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    value: str
    currency: str


class _CoinbaseAccount(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    uuid: str
    currency: str
    available_balance: _CoinbaseMoney
    hold: _CoinbaseMoney


class _CoinbaseAccountsPage(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    accounts: list[_CoinbaseAccount]
    has_next: bool
    cursor: str = ""


class _CoinbaseSpotPriceData(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    base: str
    currency: str
    amount: str


class _CoinbaseSpotPrice(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    data: _CoinbaseSpotPriceData


def _decimal(value: object) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, int | float | Decimal | str):
        return None
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        return None
    return result if result.is_finite() else None


def _minor_units(amount: Decimal) -> int:
    return int((amount * _USD_MINOR_UNITS).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _age_issue(as_of: datetime, now: datetime, max_age_hours: int) -> str | None:
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        return "A source observation has no timezone."
    if as_of > now:
        return "A source observation is newer than the valuation time."
    if now - as_of > timedelta(hours=max_age_hours):
        return "A source observation is stale."
    return None


def _unavailable(name: str, issue: str) -> SourceValuation:
    return SourceValuation(name=name, status="unavailable", amount_minor_units=None, as_of=None, issues=[issue])


async def _read_plaid(
    pool: asyncpg.Pool, policy: PortfolioPolicy, *, now: datetime
) -> tuple[SourceValuation, int, int, int]:
    plaid = policy.sources.plaid
    selected_ids = [*plaid.asset_account_ids, *plaid.liability_account_ids]
    expected_types = dict.fromkeys(plaid.asset_account_ids, "asset")
    expected_types.update(dict.fromkeys(plaid.liability_account_ids, "liability"))
    if not selected_ids:
        return _unavailable("plaid", "No Plaid accounts are selected."), 0, 0, 0

    try:
        async with pool.acquire() as connection:
            account_rows = await connection.fetch(_ACCOUNT_BALANCES_SQL, selected_ids)
            holding_rows: list[asyncpg.Record] = []
            if policy.excluded_securities:
                account_ids = sorted({exclusion.account_id for exclusion in policy.excluded_securities})
                holding_rows = await connection.fetch(_EXCLUDED_HOLDINGS_SQL, account_ids)
    except asyncpg.PostgresError, OSError, TimeoutError:
        return _unavailable("plaid", "The Plaid mirror could not be read."), 0, 0, 0

    rows_by_id = {str(row["account_id"]): row for row in account_rows}
    if len(rows_by_id) != len(account_rows) or set(rows_by_id) != set(selected_ids):
        return _unavailable("plaid", "One or more selected Plaid accounts are missing or inactive."), 0, 0, 0

    balances: dict[str, Decimal] = {}
    balance_times: dict[str, datetime] = {}
    for account_id, row in rows_by_id.items():
        account_type = row["account_type"]
        expected = expected_types[account_id]
        valid_types = {"depository", "investment"} if expected == "asset" else {"credit", "loan"}
        if account_type not in valid_types:
            return _unavailable("plaid", "A selected Plaid account has an incompatible type."), 0, 0, 0
        if row["account_currency"] != "USD" or row["balance_currency"] != "USD":
            return _unavailable("plaid", "A selected Plaid account does not have a confirmed USD balance."), 0, 0, 0
        amount = _decimal(row["current"])
        captured_at = row["captured_at"]
        if amount is None or not isinstance(captured_at, datetime):
            return _unavailable("plaid", "A selected Plaid account has no usable balance observation."), 0, 0, 0
        issue = _age_issue(captured_at, now, plaid.max_age_hours)
        if issue is not None:
            return _unavailable("plaid", issue), 0, 0, 0
        balances[account_id] = amount
        balance_times[account_id] = captured_at

    requested_positions = {
        (exclusion.account_id, security_id): exclusion
        for exclusion in policy.excluded_securities
        for security_id in exclusion.security_ids
    }
    holding_by_position: dict[tuple[str, str], asyncpg.Record] = {}
    holdings_by_account: dict[str, list[asyncpg.Record]] = {}
    for row in holding_rows:
        position = (str(row["account_id"]), str(row["security_id"]))
        if position in holding_by_position:
            return _unavailable("plaid", "An excluded holding has an ambiguous observation."), 0, 0, 0
        holding_by_position[position] = row
        holdings_by_account.setdefault(position[0], []).append(row)

    for account_id in {exclusion.account_id for exclusion in policy.excluded_securities}:
        account_holdings = holdings_by_account.get(account_id)
        if not account_holdings:
            return _unavailable("plaid", "An excluded holding has no complete observation batch."), 0, 0, 0
        capture_times = {row["captured_at"] for row in account_holdings}
        if len(capture_times) != 1:
            return _unavailable("plaid", "An excluded holding batch has inconsistent observation times."), 0, 0, 0
        holding_as_of = next(iter(capture_times))
        if not isinstance(holding_as_of, datetime):
            return _unavailable("plaid", "An excluded holding has no usable USD value observation."), 0, 0, 0
        issue = _age_issue(holding_as_of, now, plaid.max_age_hours)
        if issue is not None:
            return _unavailable("plaid", issue), 0, 0, 0
        if abs(balance_times[account_id] - holding_as_of) > timedelta(hours=min(plaid.max_age_hours, 24)):
            return _unavailable("plaid", "Account balances and holdings are too far apart to reconcile."), 0, 0, 0

    excluded_amount = Decimal(0)
    observation_times = list(balance_times.values())
    excluded_by_account: dict[str, Decimal] = {}
    for account_id, account_holdings in holdings_by_account.items():
        adjusted_total = Decimal(0)
        multipliers: list[Decimal] = []
        for row in account_holdings:
            position = (account_id, str(row["security_id"]))
            holding_value = _decimal(row["institution_value"])
            if holding_value is None:
                return _unavailable("plaid", "An excluded holding batch has an unusable value."), 0, 0, 0
            if row["holding_currency"] != "USD":
                return _unavailable("plaid", "An excluded holding does not have a confirmed USD value."), 0, 0, 0
            exclusion = requested_positions.get(position)
            multiplier = exclusion.value_multiplier if exclusion is not None else Decimal(1)
            adjusted_total += holding_value * multiplier
            multipliers.append(multiplier)
            if exclusion is not None:
                excluded_amount += holding_value * multiplier
                excluded_by_account[account_id] = (
                    excluded_by_account.get(account_id, Decimal(0)) + holding_value * multiplier
                )
        if any(multiplier != Decimal(1) for multiplier in multipliers):
            balance = balances[account_id]
            tolerance = max(Decimal(1), abs(balance) * Decimal("0.01"))
            if abs(adjusted_total - balance) > tolerance:
                return (
                    _unavailable("plaid", "Corrected holdings do not reconcile to the selected account balance."),
                    0,
                    0,
                    0,
                )
        holding_as_of = account_holdings[0]["captured_at"]
        observation_times.append(holding_as_of)

    for account_id, excluded_value in excluded_by_account.items():
        if excluded_value > balances[account_id] + Decimal("0.01"):
            return _unavailable("plaid", "Excluded holdings exceed the selected account balance."), 0, 0, 0

    assets = sum((balances[account_id] for account_id in plaid.asset_account_ids), Decimal(0))
    liabilities = sum((balances[account_id] for account_id in plaid.liability_account_ids), Decimal(0))
    as_of = min(observation_times)
    issues = (
        ["Plaid account and holding observations were captured at meaningfully different times."]
        if max(observation_times) - min(observation_times) > timedelta(minutes=5)
        else []
    )
    return (
        SourceValuation(
            name="plaid", status="ready", amount_minor_units=_minor_units(assets), as_of=as_of, issues=issues
        ),
        _minor_units(assets),
        _minor_units(liabilities),
        _minor_units(excluded_amount),
    )


def _coinbase_jwt(api_key: SecretStr, api_secret: SecretStr, *, now: datetime, method: str, path: str) -> str:
    issued_at = int(now.timestamp())
    uri = f"{method} {_COINBASE_HOST}{path}"
    token = jwt.encode(
        {"iss": "cdp", "sub": api_key.get_secret_value(), "nbf": issued_at, "exp": issued_at + 120, "uri": uri},
        api_secret.get_secret_value(),
        algorithm="ES256",
        headers={"kid": api_key.get_secret_value(), "nonce": str(uuid.uuid4())},
    )
    return token.decode("ascii") if isinstance(token, bytes) else token


async def _read_coinbase(
    *, now: datetime, api_key: SecretStr | None, api_secret: SecretStr | None
) -> tuple[SourceValuation, int]:
    if api_key is None or api_secret is None:
        return _unavailable("coinbase", "Coinbase is enabled but its view-only credentials are unavailable."), 0
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
            accounts: list[_CoinbaseAccount] = []
            cursors: set[str] = set()
            cursor = ""
            while True:
                params = {"limit": "250"}
                if cursor:
                    params["cursor"] = cursor
                token = _coinbase_jwt(api_key, api_secret, now=now, method="GET", path=_COINBASE_ACCOUNTS_PATH)
                response = await client.get(_COINBASE_ACCOUNTS_URL, params=params, headers={"Authorization": f"Bearer {token}"})
                response.raise_for_status()
                page = _CoinbaseAccountsPage.model_validate(response.json())
                accounts.extend(page.accounts)
                if not page.has_next:
                    break
                if not page.cursor or page.cursor in cursors:
                    return _unavailable("coinbase", "Coinbase account pagination was incomplete."), 0
                cursors.add(page.cursor)
                cursor = page.cursor

            account_ids = [account.uuid for account in accounts]
            if len(account_ids) != len(set(account_ids)):
                return _unavailable("coinbase", "Coinbase returned an ambiguous account set."), 0
            currencies: set[str] = set()
            account_values: list[tuple[str, Decimal]] = []
            for account in accounts:
                currency = account.currency
                if not _ASSET_CODE.fullmatch(currency):
                    return _unavailable("coinbase", "Coinbase returned an unsupported asset code."), 0
                if account.available_balance.currency != currency or account.hold.currency != currency:
                    return _unavailable("coinbase", "Coinbase balance currencies did not match the account."), 0
                available = _decimal(account.available_balance.value)
                hold = _decimal(account.hold.value)
                if available is None or hold is None:
                    return _unavailable("coinbase", "Coinbase returned a malformed balance."), 0
                value = available + hold
                account_values.append((currency, value))
                if currency != "USD" and value != 0:
                    currencies.add(currency)

            prices: dict[str, Decimal] = {"USD": Decimal(1)}
            for currency in sorted(currencies):
                response = await client.get(_COINBASE_PRICE_URL.format(asset=currency))
                response.raise_for_status()
                price = _CoinbaseSpotPrice.model_validate(response.json()).data
                amount = _decimal(price.amount)
                if price.base != currency or price.currency != "USD" or amount is None or amount <= 0:
                    return _unavailable("coinbase", "Coinbase returned a malformed USD spot quote."), 0
                prices[currency] = amount
    except httpx.HTTPError, InvalidOperation, TypeError, ValueError, ValidationError, jwt.PyJWTError:
        return _unavailable("coinbase", "Coinbase could not provide a complete current valuation."), 0

    total_usd = sum((value * prices[currency] for currency, value in account_values if value != 0), Decimal(0))
    return (
        SourceValuation(
            name="coinbase",
            status="ready",
            amount_minor_units=_minor_units(total_usd),
            as_of=None,
            issues=[
                "Coinbase values use fetched balances and request-time spot prices where needed; "
                "provider quote timestamps are unavailable."
            ],
        ),
        _minor_units(total_usd),
    )


async def read_portfolio(
    pool: asyncpg.Pool,
    policy: PortfolioPolicy,
    *,
    now: datetime,
    coinbase_api_key: SecretStr | None = None,
    coinbase_api_secret: SecretStr | None = None,
) -> PortfolioView:
    """Read selected holdings and return a fail-closed USD portfolio view."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")

    sources: list[SourceValuation] = []
    assets_minor_units = 0
    liabilities_minor_units = 0
    excluded_minor_units = 0
    sources_ready = True
    selected = bool(policy.sources.plaid.asset_account_ids or policy.sources.plaid.liability_account_ids)
    if selected:
        plaid_source, plaid_assets, plaid_liabilities, plaid_excluded = await _read_plaid(pool, policy, now=now)
        sources.append(plaid_source)
        if plaid_source.status == "unavailable":
            sources_ready = False
        else:
            assets_minor_units += plaid_assets
            liabilities_minor_units += plaid_liabilities
            excluded_minor_units += plaid_excluded

    if policy.sources.coinbase.enabled:
        coinbase_source, coinbase_assets = await _read_coinbase(
            now=now, api_key=coinbase_api_key, api_secret=coinbase_api_secret
        )
        sources.append(coinbase_source)
        if coinbase_source.status == "unavailable":
            sources_ready = False
        if selected and coinbase_source.status == "ready":
            coinbase_source = coinbase_source.model_copy(
                update={
                    "issues": [
                        *coinbase_source.issues,
                        "Coinbase balances were fetched during this valuation while Plaid balances are cached "
                        "institution observations.",
                    ]
                }
            )
            sources[-1] = coinbase_source
        if coinbase_source.status == "ready":
            assets_minor_units += coinbase_assets

    if not sources or not sources_ready:
        return PortfolioView(
            status="unavailable",
            net_minor_units=None,
            assets_minor_units=None,
            liabilities_minor_units=None,
            excluded_minor_units=None,
            sources=sources,
        )
    return PortfolioView(
        status="ready",
        net_minor_units=assets_minor_units - liabilities_minor_units - excluded_minor_units,
        assets_minor_units=assets_minor_units,
        liabilities_minor_units=liabilities_minor_units,
        excluded_minor_units=excluded_minor_units,
        sources=sources,
    )
