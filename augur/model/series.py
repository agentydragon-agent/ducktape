"""Shared external-series identifiers for sampled exogenous bundles."""

from __future__ import annotations

from enum import IntEnum

INFLATION_SERIES_ID = "inflation"
SP500_SERIES_ID = "sp500"
HOME_VALUE_SERIES_PREFIX = "home_value:"
RENT_SERIES_PREFIX = "rent:"
PRIVATE_EQUITY_SERIES_PREFIX = "private_equity:"
CRYPTO_SERIES_PREFIX = "crypto:"
PRIVATE_EQUITY_SALE_EVENT_PREFIX = "private_equity_sale_opportunity:"
PRIVATE_EQUITY_REGIME_CODE_SERIES_PREFIX = "private_equity_regime_code:"
PRIVATE_EQUITY_EVENT_KIND_CODE_SERIES_PREFIX = "private_equity_event_kind_code:"
PRIVATE_EQUITY_SALE_CAPACITY_FRACTION_SERIES_PREFIX = "private_equity_sale_capacity_fraction:"
PRIVATE_EQUITY_ELIGIBLE_FRACTION_SERIES_PREFIX = "private_equity_eligible_fraction:"
PRIVATE_EQUITY_FORCED_SALE_FRACTION_SERIES_PREFIX = "private_equity_forced_sale_fraction:"
PRIVATE_EQUITY_LIQUIDITY_BLOCKED_SERIES_PREFIX = "private_equity_liquidity_blocked:"
PRIVATE_EQUITY_FORCED_RECOVERY_CASHOUT_USD_SERIES_PREFIX = "private_equity_forced_recovery_cashout_usd:"


class PrivateEquityRegimeCode(IntEnum):
    PRIVATE_OPERATING = 1
    LIQUIDITY_SUSPENDED = 2
    DISTRESSED = 3
    PUBLIC_MARKET = 4
    ACQUISITION_CASHOUT = 5
    COLLAPSED = 6


class PrivateEquityEventKindCode(IntEnum):
    NONE = 0
    TENDER = 1
    ADMIN_MARK_UPDATE = 2
    PUBLIC_MARKET_OPEN = 3
    ACQUISITION_CASHOUT = 4
    LEGAL_IMPAIRMENT = 5
    FORCED_RECOVERY = 6
    COLLAPSE = 7


PRIVATE_EQUITY_LEVEL_SERIES_PREFIXES = frozenset(
    {
        PRIVATE_EQUITY_SERIES_PREFIX,
        PRIVATE_EQUITY_REGIME_CODE_SERIES_PREFIX,
        PRIVATE_EQUITY_EVENT_KIND_CODE_SERIES_PREFIX,
        PRIVATE_EQUITY_SALE_CAPACITY_FRACTION_SERIES_PREFIX,
        PRIVATE_EQUITY_ELIGIBLE_FRACTION_SERIES_PREFIX,
        PRIVATE_EQUITY_FORCED_SALE_FRACTION_SERIES_PREFIX,
        PRIVATE_EQUITY_LIQUIDITY_BLOCKED_SERIES_PREFIX,
        PRIVATE_EQUITY_FORCED_RECOVERY_CASHOUT_USD_SERIES_PREFIX,
    }
)
PRIVATE_EQUITY_EVENT_SERIES_PREFIXES = frozenset({PRIVATE_EQUITY_SALE_EVENT_PREFIX})


def home_value_series_id(location_id: str) -> str:
    return f"{HOME_VALUE_SERIES_PREFIX}{location_id}"


def rent_series_id(location_id: str) -> str:
    return f"{RENT_SERIES_PREFIX}{location_id}"


def private_equity_series_id(issuer_id: str) -> str:
    return f"{PRIVATE_EQUITY_SERIES_PREFIX}{issuer_id}"


def private_equity_regime_code_series_id(issuer_id: str) -> str:
    return f"{PRIVATE_EQUITY_REGIME_CODE_SERIES_PREFIX}{issuer_id}"


def private_equity_event_kind_code_series_id(issuer_id: str) -> str:
    return f"{PRIVATE_EQUITY_EVENT_KIND_CODE_SERIES_PREFIX}{issuer_id}"


def private_equity_sale_capacity_fraction_series_id(issuer_id: str) -> str:
    return f"{PRIVATE_EQUITY_SALE_CAPACITY_FRACTION_SERIES_PREFIX}{issuer_id}"


def private_equity_eligible_fraction_series_id(issuer_id: str) -> str:
    return f"{PRIVATE_EQUITY_ELIGIBLE_FRACTION_SERIES_PREFIX}{issuer_id}"


def private_equity_forced_sale_fraction_series_id(issuer_id: str) -> str:
    return f"{PRIVATE_EQUITY_FORCED_SALE_FRACTION_SERIES_PREFIX}{issuer_id}"


def private_equity_liquidity_blocked_series_id(issuer_id: str) -> str:
    return f"{PRIVATE_EQUITY_LIQUIDITY_BLOCKED_SERIES_PREFIX}{issuer_id}"


def private_equity_forced_recovery_cashout_usd_series_id(issuer_id: str) -> str:
    return f"{PRIVATE_EQUITY_FORCED_RECOVERY_CASHOUT_USD_SERIES_PREFIX}{issuer_id}"


def private_equity_auxiliary_level_series_ids(issuer_id: str) -> frozenset[str]:
    return frozenset(
        {
            private_equity_regime_code_series_id(issuer_id),
            private_equity_event_kind_code_series_id(issuer_id),
            private_equity_sale_capacity_fraction_series_id(issuer_id),
            private_equity_eligible_fraction_series_id(issuer_id),
            private_equity_forced_sale_fraction_series_id(issuer_id),
            private_equity_liquidity_blocked_series_id(issuer_id),
            private_equity_forced_recovery_cashout_usd_series_id(issuer_id),
        }
    )


def private_equity_level_series_ids(issuer_id: str) -> frozenset[str]:
    return frozenset({private_equity_series_id(issuer_id), *private_equity_auxiliary_level_series_ids(issuer_id)})


def crypto_series_id(symbol: str) -> str:
    return f"{CRYPTO_SERIES_PREFIX}{symbol}"


def private_equity_sale_event_id(issuer_id: str) -> str:
    return f"{PRIVATE_EQUITY_SALE_EVENT_PREFIX}{issuer_id}"


def private_equity_issuer_id_from_price_series_id(series_id: str) -> str | None:
    return series_suffix(series_id, PRIVATE_EQUITY_SERIES_PREFIX)


def private_equity_issuer_id_from_level_series_id(series_id: str) -> str | None:
    for prefix in PRIVATE_EQUITY_LEVEL_SERIES_PREFIXES:
        issuer_id = series_suffix(series_id, prefix)
        if issuer_id is not None:
            return issuer_id
    return None


def private_equity_issuer_id_from_event_series_id(event_id: str) -> str | None:
    for prefix in PRIVATE_EQUITY_EVENT_SERIES_PREFIXES:
        issuer_id = series_suffix(event_id, prefix)
        if issuer_id is not None:
            return issuer_id
    return None


def is_private_equity_level_series_id(series_id: str) -> bool:
    return private_equity_issuer_id_from_level_series_id(series_id) is not None


def is_private_equity_event_series_id(event_id: str) -> bool:
    return private_equity_issuer_id_from_event_series_id(event_id) is not None


def series_suffix(value: str, prefix: str) -> str | None:
    if not value.startswith(prefix):
        return None
    return value[len(prefix) :]
