from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, NonNegativeFloat

from finance.augur.sim.fixed_point import validate_currency_amount


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


Percentage = Annotated[NonNegativeFloat, Field(le=100)]
type CurrencyAmount = Annotated[Decimal, BeforeValidator(validate_currency_amount)]
type NonNegativeCurrencyAmount = Annotated[CurrencyAmount, Field(ge=0)]
type PositiveCurrencyAmount = Annotated[CurrencyAmount, Field(gt=0)]

type Frame = dict[str, list[float | int | bool | str | None]]
"""Rectangular, JSON-safe table payload: one column per key, equal-length lists."""
