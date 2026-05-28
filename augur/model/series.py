"""Typed identifiers for exogenous level series and PE protocol codes.

The augur sim<->model boundary used to encode the *kind* of a series in a
magic prefix on its string id (`"home_value:..."`, `"crypto:..."`,
`"private_equity_regime_code:..."`, etc.) and have every consumer dispatch on
`series_id.startswith(...)`. That dispatch is now typed: every non-PE level
series is identified by a `LevelSeriesKey` variant (a Pydantic discriminated
union with an `IntEnum` `kind` discriminator), and the PE protocol bundle
lives in its own typed `PrivateEquityBundle` indexed by `IssuerId`.

The wire string format is preserved for serialization and human-readable
logs/IDs; producers and consumers obtain it via `LevelSeriesKey.wire_id` and
recover the typed key via `parse_level_series_key`. Outside of those two
boundary functions, no augur code should be matching prefixes.
"""

from __future__ import annotations

from enum import IntEnum
from typing import Annotated, Literal, NewType

from pydantic import Field

from augur.model.schemas import FrozenModel

IssuerId = NewType("IssuerId", str)
LocationId = NewType("LocationId", str)
CryptoSymbol = NewType("CryptoSymbol", str)


class LevelSeriesKind(IntEnum):
    """Discriminator for `LevelSeriesKey` variants."""

    INFLATION = 1
    SP500 = 2
    HOME_VALUE = 3
    RENT = 4
    CRYPTO = 5


class _LevelKeyBase(FrozenModel):
    @property
    def wire_id(self) -> str:
        raise NotImplementedError


class InflationKey(_LevelKeyBase):
    kind: Literal[LevelSeriesKind.INFLATION] = LevelSeriesKind.INFLATION

    @property
    def wire_id(self) -> str:
        return "inflation"


class SP500Key(_LevelKeyBase):
    kind: Literal[LevelSeriesKind.SP500] = LevelSeriesKind.SP500

    @property
    def wire_id(self) -> str:
        return "sp500"


class HomeValueKey(_LevelKeyBase):
    kind: Literal[LevelSeriesKind.HOME_VALUE] = LevelSeriesKind.HOME_VALUE
    location_id: LocationId

    @property
    def wire_id(self) -> str:
        return f"home_value:{self.location_id}"


class RentKey(_LevelKeyBase):
    kind: Literal[LevelSeriesKind.RENT] = LevelSeriesKind.RENT
    location_id: LocationId

    @property
    def wire_id(self) -> str:
        return f"rent:{self.location_id}"


class CryptoKey(_LevelKeyBase):
    kind: Literal[LevelSeriesKind.CRYPTO] = LevelSeriesKind.CRYPTO
    symbol: CryptoSymbol

    @property
    def wire_id(self) -> str:
        return f"crypto:{self.symbol}"


type LevelSeriesKey = Annotated[
    InflationKey | SP500Key | HomeValueKey | RentKey | CryptoKey, Field(discriminator="kind")
]


class PrivateEquityRegimeCode(IntEnum):
    """Sim-facing issuer operating modes.

    Keep this enum to states that change holder-visible liquidity or accounting behavior.
    Model-internal latent states such as business distress should stay in the model and
    affect the emitted protocol channels instead of being exposed directly to the simulator.
    Liquidity suspension is represented by the separate `liquidity_blocked` protocol channel.
    """

    PRIVATE_OPERATING = 1
    PUBLIC_MARKET = 2
    ACQUIRED = 3
    COLLAPSED = 4


class PrivateEquityEventKindCode(IntEnum):
    NONE = 0
    TENDER = 1
    ADMIN_MARK_UPDATE = 2
    PUBLIC_MARKET_OPEN = 3
    ACQUISITION_CASHOUT = 4
    LEGAL_IMPAIRMENT = 5
    FORCED_RECOVERY = 6
    COLLAPSE = 7


def parse_level_series_key(wire_id: str) -> LevelSeriesKey:
    """Recover a typed `LevelSeriesKey` from its wire form.

    The only place in augur that decodes the prefix-encoded series-id string.
    Raises `ValueError` for unrecognized wire ids (including private-equity
    wire ids — PE is not a level series and is carried in the typed PE bundle).
    """

    match wire_id:
        case "inflation":
            return InflationKey()
        case "sp500":
            return SP500Key()
    prefix, sep, suffix = wire_id.partition(":")
    if not sep:
        raise ValueError(f"unrecognized level-series wire id {wire_id!r}")
    match prefix:
        case "home_value":
            return HomeValueKey(location_id=LocationId(suffix))
        case "rent":
            return RentKey(location_id=LocationId(suffix))
        case "crypto":
            return CryptoKey(symbol=CryptoSymbol(suffix))
    raise ValueError(f"unrecognized level-series wire id {wire_id!r}")


def try_parse_level_series_key(wire_id: str) -> LevelSeriesKey | None:
    """Return a typed key or `None` if the wire id is not a known level series.

    Useful for filters that need to skip private-equity series (which are
    carried in the typed PE bundle and have no `LevelSeriesKey` representation).
    """

    try:
        return parse_level_series_key(wire_id)
    except ValueError:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Private-equity wire identifiers.
#
# PE protocol series do not have a `LevelSeriesKey` representation: they are
# carried as typed columns in `augur.model.private_equity_bundle.PrivateEquityBundle`
# keyed by `IssuerId`. The wire-id strings below exist only as historical
# names for trace/log output and YAML fixtures; no dispatch site should
# match on them.
# ─────────────────────────────────────────────────────────────────────────────


def private_equity_mark_wire_id(issuer_id: IssuerId | str) -> str:
    """Wire id for the per-unit mark series of one issuer."""

    return f"private_equity:{issuer_id}"


def private_equity_sale_opportunity_wire_id(issuer_id: IssuerId | str) -> str:
    """Wire id for the sale-opportunity (tender) event of one issuer."""

    return f"private_equity_sale_opportunity:{issuer_id}"


def issuer_id_from_private_equity_mark_wire_id(wire_id: str) -> IssuerId | None:
    """Recover the issuer id from a `"private_equity:..."` wire id (or `None`)."""

    prefix = "private_equity:"
    if not wire_id.startswith(prefix):
        return None
    return IssuerId(wire_id[len(prefix) :])


def issuer_id_from_private_equity_sale_opportunity_wire_id(wire_id: str) -> IssuerId | None:
    """Recover the issuer id from a `"private_equity_sale_opportunity:..."` wire id."""

    prefix = "private_equity_sale_opportunity:"
    if not wire_id.startswith(prefix):
        return None
    return IssuerId(wire_id[len(prefix) :])


# CLEANUP(2026-05-28): Temporary scaffolding while consumers migrate to
# LevelSeriesKey + PrivateEquityBundle. Every symbol below MUST be deleted —
# along with every remaining importer of it — before declaring the typed-
# boundary refactor done. Search for "CLEANUP(2026-05-28)" to find related
# migration work elsewhere.

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


def home_value_series_id(location_id: str) -> str:
    return HomeValueKey(location_id=LocationId(location_id)).wire_id


def rent_series_id(location_id: str) -> str:
    return RentKey(location_id=LocationId(location_id)).wire_id


def crypto_series_id(symbol: str) -> str:
    return CryptoKey(symbol=CryptoSymbol(symbol)).wire_id


def private_equity_series_id(issuer_id: str) -> str:
    return private_equity_mark_wire_id(issuer_id)


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


def private_equity_sale_event_id(issuer_id: str) -> str:
    return private_equity_sale_opportunity_wire_id(issuer_id)
