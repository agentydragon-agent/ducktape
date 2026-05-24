from __future__ import annotations

from pydantic import Field, NonNegativeFloat, NonNegativeInt, computed_field

from augur.api.schemas import ApiModel


class ConcentratedHoldingSnapshot(ApiModel):
    """Per-holding metadata + the model's current per-unit mark.

    `fmv_usd_per_unit` is sourced from the exogenous provider (VECM's
    `private_equity_prices_usd[holding_id]` or independent's
    `series['private_equity:<holding_id>'].initial_value`) by the bootstrap
    builder — config files don't repeat it. The computed `value_usd` is
    the snapshot-time mark surfaced to the UI; it doesn't track stochastic
    PE price paths during a sim, which the exogenous provider owns.
    """

    holding_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_\-]*$")
    label: str
    units: NonNegativeInt
    basis_per_unit_usd: NonNegativeFloat = 0.0
    fmv_usd_per_unit: NonNegativeFloat = 0.0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def value_usd(self) -> float:
        return float(self.units) * float(self.fmv_usd_per_unit)


class FinanceSnapshot(ApiModel):
    """Initial balance snapshot surfaced to the UI and used for scenario defaults."""

    as_of_date: str
    cash_usd: float = 0.0
    wealthfront_sp500_usd: float = 0.0
    ibkr_vt_usd: float = 0.0
    sp500_proxy_portfolio_usd: float = 0.0
    concentrated_holdings: tuple[ConcentratedHoldingSnapshot, ...] = ()
    notes: tuple[str, ...] = ()
