"""HTTP wire types for the budget planner endpoints."""

from __future__ import annotations

from datetime import date

from pydantic import Field, NonNegativeInt, PositiveInt

from augur.api.schemas import ApiModel
from augur.budget.schema import BucketKind


class BucketView(ApiModel):
    id: str
    label: str
    kind: BucketKind
    reimbursed_by: str | None


class BucketMonthly(ApiModel):
    """One bucket's monthly trend (and a 3-month average to anchor the trim UI)."""

    bucket_id: str
    monthly_amounts: tuple[float, ...] = Field(description="Signed totals per month; + outflow, - inflow.")
    current_monthly_avg: float = Field(description="Trailing 3-month average (or fewer if the window is shorter).")
    transaction_count: NonNegativeInt


class LumpyView(ApiModel):
    transaction_id: str
    date: date
    amount: float
    name: str
    merchant_name: str | None
    bucket_id: str


class BudgetSnapshotRequest(ApiModel):
    """Window selector: trailing N calendar months ending in the latest data month."""

    months: PositiveInt = Field(default=12, le=36)


class BudgetSnapshotResponse(ApiModel):
    months: tuple[date, ...]
    buckets: tuple[BucketView, ...]
    monthly_by_bucket: tuple[BucketMonthly, ...]
    lumpy: tuple[LumpyView, ...]
    lumpy_threshold_usd: float
    reimbursement_window_months: int
    data_window_start: date
    data_window_end: date


class TransactionView(ApiModel):
    transaction_id: str
    date: date
    amount: float
    name: str
    merchant_name: str | None
    pfc_primary: str | None
    pfc_detailed: str | None
    account_name: str
    institution_name: str | None
    bucket_id: str


class BudgetTransactionsRequest(ApiModel):
    bucket_id: str
    months: PositiveInt = Field(default=12, le=36)


class BudgetTransactionsResponse(ApiModel):
    bucket_id: str
    transactions: tuple[TransactionView, ...]
