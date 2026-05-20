from __future__ import annotations

from pydantic import Field, NonNegativeFloat, NonNegativeInt, computed_field

from augur.api.schemas import ApiModel


class ConcentratedHoldingSnapshot(ApiModel):
    holding_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_\-]*$")
    label: str
    units: NonNegativeInt
    fmv_usd_per_unit: NonNegativeFloat
    basis_per_unit_usd: NonNegativeFloat = 0.0
    valuation_source: str = ""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def value_usd(self) -> float:
        return self.units * self.fmv_usd_per_unit


class FinanceSnapshot(ApiModel):
    """Initial balance snapshot surfaced to the UI and used for scenario defaults."""

    as_of_date: str
    cash_usd: float = 0.0
    wealthfront_sp500_usd: float = 0.0
    ibkr_vt_usd: float = 0.0
    sp500_proxy_portfolio_usd: float = 0.0
    concentrated_holdings: tuple[ConcentratedHoldingSnapshot, ...] = ()
    notes: tuple[str, ...] = ()
