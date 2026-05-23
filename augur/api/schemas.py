from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, NonNegativeFloat


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


Percentage = Annotated[NonNegativeFloat, Field(le=100)]

type Frame = dict[str, list[float | int | bool | str | None]]
"""Rectangular, JSON-safe table payload: one column per key, equal-length lists."""


class KnobsConfig(ApiModel):
    down_payment_pct: float
    credit_score: float
    custom_mortgage_rate: float
    custom_mortgage_term_years: float
    starting_portfolio_usd: float
    hold_years: float
    appreciation_rate: float
    sp500_rate: float
    maintenance_pct: float
    owner_occupancy_years: float
    inflation: float
    vacancy_pct: float
    mgmt_pct: float
    leasing_fee_pct: float
    rooms_rented_while_living: float
    room_rent_monthly_usd: float
    room_vacancy_pct: float
    portfolio_liquidation_tax_pct: float
    insurance_annual_usd: float
    closing_cost_buy_pct: float
    closing_cost_sell_pct: float
    depreciable_basis_pct: float
    financing_mode: Literal["cash", "fixed_30", "fixed_15", "custom"]
    occupancy_type: Literal["primary_residence", "second_home", "investment"]
