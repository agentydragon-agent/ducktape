"""User-friendly portfolio schema for Augur runtime configuration.

This is intentionally not the simulator's executable scenario schema. The
deployment YAML should read like a portfolio statement: accounts contain
positions, and positions contain actual tax lots. The API/runtime layer expands
this shape into lower-level sim objects at the runtime boundary.
"""

from __future__ import annotations

from collections import Counter
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, NonNegativeFloat, NonNegativeInt, PositiveFloat, model_validator

from augur.sim.scenario import InitialLot

_ID_PATTERN = r"^[a-z0-9][a-z0-9_\-]*$"
_SERIES_ID_PATTERN = r"^[a-z0-9][a-z0-9_:\-]*$"


class PortfolioConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PortfolioAccountType(StrEnum):
    TAXABLE_BROKERAGE = "taxable_brokerage"


class PublicSecurityKind(StrEnum):
    ETF = "etf"
    STOCK = "stock"
    MUTUAL_FUND = "mutual_fund"
    # Crypto holdings (BTC, ETH, …) flow through the same position/lot machinery as stocks —
    # FIFO cost basis, cap-gains treatment, sampled price series via the VECM `crypto:*`
    # factors. Calling them "public securities" is a slight misnomer for crypto, but the
    # sim doesn't distinguish, so we lean on this enum value for display routing only.
    CRYPTOCURRENCY = "cryptocurrency"
    OTHER = "other"


class PortfolioAccountConfig(PortfolioConfigModel):
    account_id: str = Field(pattern=_ID_PATTERN)
    owner_agent_id: str = Field(pattern=_ID_PATTERN)
    account_type: PortfolioAccountType = PortfolioAccountType.TAXABLE_BROKERAGE
    label: str | None = None


class PublicSecurityTaxLotConfig(PortfolioConfigModel):
    lot_id: str = Field(pattern=_ID_PATTERN)
    holding_period_months_at_start: NonNegativeInt
    quantity: PositiveFloat
    cost_basis_usd: NonNegativeFloat

    @property
    def cost_basis_per_unit_usd(self) -> float:
        return float(self.cost_basis_usd / self.quantity)


class PublicSecurityPositionConfig(PortfolioConfigModel):
    position_id: str = Field(pattern=_ID_PATTERN)
    account_id: str = Field(pattern=_ID_PATTERN)
    label: str | None = None
    symbol: str
    security_kind: PublicSecurityKind
    value_series_id: str = Field(
        pattern=_SERIES_ID_PATTERN,
        description=(
            "Sim/model unit-value series used to value this security. This should be the held "
            "security's unit series, e.g. voo or goog; the model can map that to broader factors."
        ),
    )
    unit_value_usd: PositiveFloat
    lots: tuple[PublicSecurityTaxLotConfig, ...] = Field(min_length=1)

    @property
    def total_quantity(self) -> float:
        return sum(float(lot.quantity) for lot in self.lots)

    @property
    def current_value_usd(self) -> float:
        return self.total_quantity * float(self.unit_value_usd)

    @property
    def total_cost_basis_usd(self) -> float:
        return sum(float(lot.cost_basis_usd) for lot in self.lots)


class PortfolioConfig(PortfolioConfigModel):
    """Deployment-authored portfolio facts.

    Month 0 is the start of the simulated scenario. Tax lots express their
    holding period relative to month 0, avoiding a mix of calendar dates and
    sim-relative month indexes.
    """

    accounts: tuple[PortfolioAccountConfig, ...] = ()
    public_securities: tuple[PublicSecurityPositionConfig, ...] = ()

    @model_validator(mode="after")
    def _validate_references(self) -> PortfolioConfig:
        duplicate_accounts = _duplicates(account.account_id for account in self.accounts)
        if duplicate_accounts:
            raise ValueError(f"portfolio accounts must have unique account_id values: {duplicate_accounts}")

        known_accounts = {account.account_id for account in self.accounts}
        missing_accounts = sorted(
            {position.account_id for position in self.public_securities if position.account_id not in known_accounts}
        )
        if missing_accounts:
            raise ValueError(f"portfolio positions reference unknown account_id values: {missing_accounts}")

        duplicate_positions = _duplicates(position.position_id for position in self.public_securities)
        if duplicate_positions:
            raise ValueError(f"public securities must have unique position_id values: {duplicate_positions}")

        duplicate_lots = _duplicates(lot.lot_id for position in self.public_securities for lot in position.lots)
        if duplicate_lots:
            raise ValueError(f"public security tax lots must have unique lot_id values: {duplicate_lots}")

        series_unit_values: dict[str, float] = {}
        for position in self.public_securities:
            unit_value = float(position.unit_value_usd)
            if (
                position.value_series_id in series_unit_values
                and series_unit_values[position.value_series_id] != unit_value
            ):
                raise ValueError(
                    f"public security positions sharing value_series_id {position.value_series_id!r} "
                    "must share unit_value_usd"
                )
            series_unit_values[position.value_series_id] = unit_value

        return self

    @property
    def total_public_security_value_usd(self) -> float:
        return sum(position.current_value_usd for position in self.public_securities)

    @property
    def level_anchors(self) -> dict[str, float]:
        return {position.value_series_id: float(position.unit_value_usd) for position in self.public_securities}

    def to_initial_lots(self) -> tuple[InitialLot, ...]:
        account_by_id = {account.account_id: account for account in self.accounts}
        return tuple(
            InitialLot(
                lot_id=lot.lot_id,
                agent_id=account_by_id[position.account_id].owner_agent_id,
                asset_id=position.value_series_id,
                purchase_month_index=-int(lot.holding_period_months_at_start),
                quantity=float(lot.quantity),
                cost_basis_per_unit_usd=lot.cost_basis_per_unit_usd,
            )
            for position in self.public_securities
            for lot in position.lots
        )


def _duplicates(values) -> list[str]:
    counts = Counter(values)
    return sorted(value for value, count in counts.items() if count > 1)
