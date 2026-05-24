from __future__ import annotations

from pydantic import Field, NonNegativeFloat, NonNegativeInt

from augur.api.schemas import ApiModel


class ConcentratedHoldingSnapshot(ApiModel):
    """Per-holding metadata. Per-unit valuation lives in the exogenous
    provider config (the model is the source of truth for prices), so this
    snapshot carries only static position identity and cost-basis facts."""

    holding_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_\-]*$")
    label: str
    units: NonNegativeInt
    basis_per_unit_usd: NonNegativeFloat = 0.0


class FinanceSnapshot(ApiModel):
    """Initial balance snapshot surfaced to the UI and used for scenario defaults."""

    as_of_date: str
    cash_usd: float = 0.0
    wealthfront_sp500_usd: float = 0.0
    ibkr_vt_usd: float = 0.0
    sp500_proxy_portfolio_usd: float = 0.0
    concentrated_holdings: tuple[ConcentratedHoldingSnapshot, ...] = ()
    notes: tuple[str, ...] = ()
