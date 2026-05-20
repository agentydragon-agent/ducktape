"""Shared market-series identifiers for sampled market bundles."""

from __future__ import annotations

INFLATION_SERIES_ID = "inflation"
SP500_SERIES_ID = "sp500"
HOME_VALUE_SERIES_PREFIX = "home_value:"
RENT_SERIES_PREFIX = "rent:"
PRIVATE_EQUITY_SERIES_PREFIX = "private_equity:"
CRYPTO_SERIES_PREFIX = "crypto:"
PRIVATE_EQUITY_SALE_EVENT_PREFIX = "private_equity_sale_opportunity:"


def home_value_series_id(location_id: str) -> str:
    return f"{HOME_VALUE_SERIES_PREFIX}{location_id}"


def rent_series_id(location_id: str) -> str:
    return f"{RENT_SERIES_PREFIX}{location_id}"


def private_equity_series_id(issuer_id: str) -> str:
    return f"{PRIVATE_EQUITY_SERIES_PREFIX}{issuer_id}"


def crypto_series_id(symbol: str) -> str:
    return f"{CRYPTO_SERIES_PREFIX}{symbol}"


def private_equity_sale_event_id(issuer_id: str) -> str:
    return f"{PRIVATE_EQUITY_SALE_EVENT_PREFIX}{issuer_id}"


def series_suffix(value: str, prefix: str) -> str | None:
    if not value.startswith(prefix):
        return None
    return value[len(prefix) :]
