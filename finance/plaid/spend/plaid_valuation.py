"""Transport-independent USD valuation of selected Plaid snapshot rows.

Queries bind $1 to a text array. Holding rows must come from each account's
latest complete capture batch, never the latest row of each individual security.
"""

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from finance.plaid.spend.portfolio_models import PlaidSourcePolicy, PortfolioPolicy, SourceValuation

_USD_MINOR_UNITS = Decimal(100)

ACCOUNT_BALANCES_SQL = """
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

HOLDING_BATCHES_SQL = """
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


def decimal_amount(value: object) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, int | float | Decimal | str):
        return None
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        return None
    return result if result.is_finite() else None


def usd_minor_units(amount: Decimal) -> int:
    return int((amount * _USD_MINOR_UNITS).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def observation_age_issue(as_of: datetime, now: datetime, max_age_hours: int) -> str | None:
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        return "A source observation has no timezone."
    if as_of > now:
        return "A source observation is newer than the valuation time."
    if now - as_of > timedelta(hours=max_age_hours):
        return "A source observation is stale."
    return None


def unavailable_source(name: str, issue: str) -> SourceValuation:
    return SourceValuation(name=name, status="unavailable", amount_minor_units=None, as_of=None, issues=[issue])


def corrected_holding_value(policy: PlaidSourcePolicy, *, account_id: str, security_id: str, value: Decimal) -> Decimal:
    """Apply only the policy's exact position correction, leaving other positions unchanged."""
    for correction in policy.holding_value_corrections:
        if correction.account_id == account_id and security_id in correction.security_ids:
            return value * correction.value_multiplier
    return value


def value_plaid_rows(
    policy: PortfolioPolicy,
    *,
    account_rows: Sequence[Mapping[str, object]],
    holding_rows: Sequence[Mapping[str, object]],
    now: datetime,
) -> tuple[SourceValuation, int, int, int]:
    """Return source, gross assets, signed liabilities and exclusions in USD cents.

    Account keys follow ACCOUNT_BALANCES_SQL; holding keys follow HOLDING_BATCHES_SQL.
    Amounts accept finite numeric values or numeric strings. Convert transport date
    strings to datetime before calling. Extra metadata columns are ignored. Supply
    holdings only for accounts with configured corrections/exclusions. Incomplete,
    stale, inconsistent or unreconciled observations produce an unavailable source
    with zero totals; callers must check source.status before using totals.
    """
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    plaid = policy.sources.plaid
    selected_ids = [*plaid.asset_account_ids, *plaid.liability_account_ids]
    expected_types = dict.fromkeys(plaid.asset_account_ids, "asset")
    expected_types.update(dict.fromkeys(plaid.liability_account_ids, "liability"))
    required_holding_accounts = {exclusion.account_id for exclusion in policy.excluded_securities} | {
        correction.account_id for correction in plaid.holding_value_corrections
    }
    if not selected_ids:
        return unavailable_source("plaid", "No Plaid accounts are selected."), 0, 0, 0

    rows_by_id = {str(row["account_id"]): row for row in account_rows}
    if len(rows_by_id) != len(account_rows) or set(rows_by_id) != set(selected_ids):
        return unavailable_source("plaid", "One or more selected Plaid accounts are missing or inactive."), 0, 0, 0

    balances: dict[str, Decimal] = {}
    balance_times: dict[str, datetime] = {}
    for account_id, row in rows_by_id.items():
        account_type = row["account_type"]
        expected = expected_types[account_id]
        valid_types = {"depository", "investment"} if expected == "asset" else {"credit", "loan"}
        if account_type not in valid_types:
            return unavailable_source("plaid", "A selected Plaid account has an incompatible type."), 0, 0, 0
        if row["account_currency"] != "USD" or row["balance_currency"] != "USD":
            return (
                unavailable_source("plaid", "A selected Plaid account does not have a confirmed USD balance."),
                0,
                0,
                0,
            )
        amount = decimal_amount(row["current"])
        captured_at = row["captured_at"]
        if amount is None or not isinstance(captured_at, datetime):
            return unavailable_source("plaid", "A selected Plaid account has no usable balance observation."), 0, 0, 0
        issue = observation_age_issue(captured_at, now, plaid.max_age_hours)
        if issue is not None:
            return unavailable_source("plaid", issue), 0, 0, 0
        balances[account_id] = amount
        balance_times[account_id] = captured_at

    excluded_positions = {
        (exclusion.account_id, security_id)
        for exclusion in policy.excluded_securities
        for security_id in exclusion.security_ids
    }
    correction_by_position = {
        (correction.account_id, security_id): correction
        for correction in plaid.holding_value_corrections
        for security_id in correction.security_ids
    }
    holding_by_position: dict[tuple[str, str], Mapping[str, object]] = {}
    holdings_by_account: dict[str, list[Mapping[str, object]]] = {}
    for row in holding_rows:
        position = (str(row["account_id"]), str(row["security_id"]))
        if position in holding_by_position:
            return unavailable_source("plaid", "A selected holding has an ambiguous observation."), 0, 0, 0
        holding_by_position[position] = row
        holdings_by_account.setdefault(position[0], []).append(row)

    for account_id in required_holding_accounts:
        account_holdings = holdings_by_account.get(account_id)
        if not account_holdings:
            return unavailable_source("plaid", "A selected account has no complete holding observation batch."), 0, 0, 0
        capture_times = {row["captured_at"] for row in account_holdings}
        if len(capture_times) != 1:
            return unavailable_source("plaid", "A holding batch has inconsistent observation times."), 0, 0, 0
        holding_as_of = next(iter(capture_times))
        if not isinstance(holding_as_of, datetime):
            return unavailable_source("plaid", "A holding has no usable value observation."), 0, 0, 0
        issue = observation_age_issue(holding_as_of, now, plaid.max_age_hours)
        if issue is not None:
            return unavailable_source("plaid", issue), 0, 0, 0
        if abs(balance_times[account_id] - holding_as_of) > timedelta(hours=min(plaid.max_age_hours, 24)):
            return unavailable_source("plaid", "Account balances and holdings are too far apart to reconcile."), 0, 0, 0

    configured_positions = excluded_positions | set(correction_by_position)
    if configured_positions.difference(holding_by_position):
        return (
            unavailable_source(
                "plaid",
                "A configured holding selector is absent from the latest observation; its current value is unknown.",
            ),
            0,
            0,
            0,
        )

    excluded_amount = Decimal(0)
    observation_times = list(balance_times.values())
    excluded_by_account: dict[str, Decimal] = {}
    correction_account_ids = {correction.account_id for correction in plaid.holding_value_corrections}
    for account_id, account_holdings in holdings_by_account.items():
        adjusted_total = Decimal(0)
        for row in account_holdings:
            position = (account_id, str(row["security_id"]))
            holding_value = decimal_amount(row["institution_value"])
            if holding_value is None:
                return unavailable_source("plaid", "A holding batch has an unusable value."), 0, 0, 0
            if row["holding_currency"] != "USD":
                return unavailable_source("plaid", "A holding does not have a confirmed USD value."), 0, 0, 0
            adjusted_value = corrected_holding_value(
                plaid, account_id=account_id, security_id=position[1], value=holding_value
            )
            adjusted_total += adjusted_value
            if position in excluded_positions:
                excluded_amount += adjusted_value
                excluded_by_account[account_id] = excluded_by_account.get(account_id, Decimal(0)) + adjusted_value
        if account_id in correction_account_ids:
            balance = balances[account_id]
            tolerance = max(Decimal(1), abs(balance) * Decimal("0.01"))
            if abs(adjusted_total - balance) > tolerance:
                return (
                    unavailable_source("plaid", "Corrected holdings do not reconcile to the selected account balance."),
                    0,
                    0,
                    0,
                )
        holding_as_of = account_holdings[0]["captured_at"]
        assert isinstance(holding_as_of, datetime)  # Validated above for every required holding account.
        observation_times.append(holding_as_of)

    for account_id, excluded_value in excluded_by_account.items():
        if excluded_value > balances[account_id] + Decimal("0.01"):
            return unavailable_source("plaid", "Excluded holdings exceed the selected account balance."), 0, 0, 0

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
            name="plaid", status="ready", amount_minor_units=usd_minor_units(assets), as_of=as_of, issues=issues
        ),
        usd_minor_units(assets),
        usd_minor_units(liabilities),
        usd_minor_units(excluded_amount),
    )
