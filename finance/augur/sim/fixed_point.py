"""Exact money and fixed-point helpers for Augur.

The simulator's money contract is a currency-specific integer quantum count.
``Decimal`` is used only at an explicitly declared boundary: parsing an exact
human/API decimal or quantizing a model-owned sampled price path before that
path enters the simulator.  The JAX engine must receive and produce integer
money values only.

The legacy USD helpers remain temporarily while the scenario and product
contracts are migrated.  New code must use the currency-generic helpers
below; keeping the conversion policy here gives the migration one auditable
definition rather than several subtly different ``round(value * 100)`` calls.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

import numpy as np
from numpy.typing import NDArray

from finance.augur.product.asset_key import AssetKey, PrivateEquityAssetKey

USD_CENTS = 100
BTC_SATOSHIS = 100_000_000
ETH_GWEI = 1_000_000_000
DEFAULT_UNIT_QUANTA = 1_000_000


def _exact_decimal(value: Any, *, field: str = "value") -> Decimal:
    """Parse an exact external decimal without silently accepting a float.

    Floats are deliberately rejected for scenario/API money inputs: converting
    a binary float through ``str`` merely hides the lossy boundary.  Model
    sampling has a separate, named quantization entrypoint below because it is
    the one intended float-to-money boundary.
    """

    if isinstance(value, float):
        raise TypeError(f"{field} must be an integer quantum count, Decimal, or decimal string; floats are not exact")
    try:
        decimal = value if isinstance(value, Decimal) else Decimal(value)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be an exact decimal value") from exc
    if not decimal.is_finite():
        raise ValueError(f"{field} must be finite")
    return decimal


def validate_currency_quantum(value: Any) -> Decimal:
    """Return a positive finite currency quantum from an exact value."""

    quantum = _exact_decimal(value, field="currency quantum")
    if quantum <= 0:
        raise ValueError(f"currency quantum must be positive; got {quantum}")
    return quantum


def decimal_to_currency_quanta(value: Any, *, quantum: Any) -> np.int64:
    """Convert an exact currency decimal to an integer count of ``quantum``.

    Unlike the old USD helper, this is validation rather than rounding: a
    scenario value that cannot be represented by its declared currency is a
    malformed contract input, not a request to silently change the amount.
    """

    amount = _exact_decimal(value)
    currency_quantum = validate_currency_quantum(quantum)
    count = amount / currency_quantum
    if count != count.to_integral_value():
        raise ValueError(f"{amount} is not an integer multiple of currency quantum {currency_quantum}")
    try:
        return np.int64(int(count))
    except OverflowError as exc:
        raise ValueError(f"currency quantum count {count} does not fit in int64") from exc


def currency_quanta_to_decimal(value: int | np.integer[Any], *, quantum: Any) -> Decimal:
    """Convert an authoritative integer quantum count to an exact display decimal."""

    return Decimal(int(value)) * validate_currency_quantum(quantum)


def currency_quanta_to_decimal_string(value: int | np.integer[Any], *, quantum: Any) -> str:
    """JSON-safe exact display form for an authoritative money count."""

    return format(currency_quanta_to_decimal(value, quantum=quantum), "f")


def currency_amount_to_quanta(value: Any, *, quantum: Any) -> np.int64:
    """Quantize a configured currency amount to its scenario's quantum.

    Scenario and product configuration models still accept JSON numbers for
    user-entered amounts. This is their single, explicit conversion into the
    integer simulator representation. Exact decimal strings and ``Decimal``
    values retain their spelling; numeric values use the same declared
    half-up policy as sampled model paths.
    """

    return sampled_decimal_to_currency_quanta(value, quantum=quantum)


def sampled_decimal_to_currency_quanta(value: Any, *, quantum: Any) -> np.int64:
    """Quantize one model-produced sampled monetary value at the sim boundary.

    This is intentionally the *only* helper in this module that accepts a
    float.  It uses decimal half-up rounding, matching the previous cents
    conversion semantics, and makes the boundary explicit in call sites.
    """

    currency_quantum = validate_currency_quantum(quantum)
    try:
        sampled = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("sampled monetary value must be numeric") from exc
    if not sampled.is_finite():
        raise ValueError("sampled monetary value must be finite")
    count = (sampled / currency_quantum).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    try:
        return np.int64(int(count))
    except OverflowError as exc:
        raise ValueError(f"sampled currency quantum count {count} does not fit in int64") from exc


def sampled_array_to_currency_quanta(values: Any, *, quantum: Any) -> NDArray[np.int64]:
    """Vectorized model→sim monetary-path quantization with exact int64 output."""

    arr = np.asarray(values)
    out = np.empty(arr.shape, dtype=np.int64)
    for idx in np.ndindex(arr.shape):
        out[idx] = sampled_decimal_to_currency_quanta(arr[idx], quantum=quantum)
    return out


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value))


def usd_to_cents(value: Any) -> np.int64:
    cents = (_decimal(value) * USD_CENTS).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    return np.int64(cents)


def cents_to_usd(value: Any) -> float:
    return float(np.asarray(value, dtype=np.float64) / float(USD_CENTS))


def usd_array_to_cents(values: Any) -> NDArray[np.int64]:
    arr = np.asarray(values)
    out = np.empty(arr.shape, dtype=np.int64)
    for idx in np.ndindex(arr.shape):
        out[idx] = usd_to_cents(arr[idx])
    return out


def cents_array_to_usd(values: Any) -> NDArray[np.float64]:
    return np.asarray(values, dtype=np.float64) / float(USD_CENTS)


# Quantity quanta by symbol: the smallest fraction of a unit the ledger tracks. BTC and ETH
# are held in fractions far below a whole coin, so they get their native subdivision; everything
# else settles at the default. Per-symbol data, not per-asset-class: two crypto symbols already
# disagree here, and a fractional-share equity would join this table without needing a new type.
QUANTITY_SCALE_BY_SYMBOL: Mapping[str, int] = {"btc": BTC_SATOSHIS, "eth": ETH_GWEI}


def quantity_scale_for_asset(asset: AssetKey) -> int:
    if isinstance(asset, PrivateEquityAssetKey):
        return DEFAULT_UNIT_QUANTA
    return QUANTITY_SCALE_BY_SYMBOL.get(str(asset.symbol).lower(), DEFAULT_UNIT_QUANTA)


def quantity_to_quanta(value: Any, *, scale: int) -> np.int64:
    quanta = (_decimal(value) * scale).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    return np.int64(quanta)


def quantity_array_to_quanta(values: Any, *, scale: int) -> NDArray[np.int64]:
    arr = np.asarray(values)
    out = np.empty(arr.shape, dtype=np.int64)
    for idx in np.ndindex(arr.shape):
        out[idx] = quantity_to_quanta(arr[idx], scale=scale)
    return out


def quanta_array_to_quantity(values: Any, *, scale: int) -> NDArray[np.float64]:
    return np.asarray(values, dtype=np.float64) / float(scale)
