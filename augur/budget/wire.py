"""HTTP wire types for the budget planner endpoints."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from pydantic import Field, NonNegativeInt, PositiveInt

from augur.api.schemas import ApiModel
from augur.budget.schema import BucketKind


class TrailingMonthsWindow(ApiModel):
    """Trailing N calendar months ending in the month containing today."""

    kind: Literal["trailing_months"] = "trailing_months"
    months: PositiveInt = Field(le=60)


class CoverageWindow(ApiModel):
    """Full available history without gaps -- from `BudgetSourceConfig.coverage_starts` to today.

    The server rejects this with 400 when no coverage_starts is configured on the deployment.
    """

    kind: Literal["since_coverage_start"] = "since_coverage_start"


WindowSpec = Annotated[TrailingMonthsWindow | CoverageWindow, Field(discriminator="kind")]


class BucketView(ApiModel):
    id: str
    label: str
    kind: BucketKind
    # Optional grouping key. Buckets sharing a `family` render together in the UI as
    # one panel (e.g. "medical" groups esketamine + therapy + supplements + insurance
    # premiums + medical reimbursements). The server doesn't compute family-level
    # totals; the frontend rolls them up from these per-bucket series.
    family: str | None


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
    window: WindowSpec


class BudgetSnapshotResponse(ApiModel):
    months: tuple[date, ...]
    buckets: tuple[BucketView, ...]
    monthly_by_bucket: tuple[BucketMonthly, ...]
    lumpy: tuple[LumpyView, ...]
    lumpy_threshold_usd: float
    data_window_start: date
    data_window_end: date
    coverage_starts: date | None = Field(
        default=None,
        description=(
            "Earliest date with complete cross-account coverage, copied from "
            "BudgetSourceConfig.coverage_starts. Months before this date are partial -- some "
            "linked accounts contributed less history than others (typically a Plaid item "
            "with a tighter institution-side transaction-history limit). The UI uses this "
            "to label early months; when null, no clamp is in effect."
        ),
    )


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
    window: WindowSpec


class BudgetTransactionsResponse(ApiModel):
    bucket_id: str
    transactions: tuple[TransactionView, ...]
