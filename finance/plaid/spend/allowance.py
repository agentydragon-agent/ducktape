"""Generic, read-only flexible allowance accounting. Personal policy comes from a private Secret."""

from __future__ import annotations

import calendar
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Kind(StrEnum):
    FLEXIBLE = "flexible"
    FIXED = "fixed"
    EXCLUDED = "excluded"


class MerchantRule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    field: str  # raw name or inferred merchant_name; name is preferred
    prefix: str = Field(min_length=2)
    kind: Kind

    @field_validator("field")
    @classmethod
    def _field(cls, value: str) -> str:
        if value not in ("name", "merchant_name"):
            raise ValueError("field must be name or merchant_name")
        return value


class AllowancePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    monthly_minor_units: int = Field(gt=0)
    activation_at: datetime | None = None
    spending_account_ids: list[str] = Field(min_length=1)
    currency: str = "USD"
    rules: list[MerchantRule] = Field(default_factory=list)
    max_sync_age_hours: int = Field(default=72, ge=1, le=720)

    @model_validator(mode="after")
    def _validate_policy(self) -> AllowancePolicy:
        if self.currency != "USD" or len(self.spending_account_ids) != len(set(self.spending_account_ids)):
            raise ValueError("USD and unique spending account IDs are required")
        if self.activation_at is not None:
            # Plaid provides a date, not a reliable purchase timestamp. Avoid partial-day accounting.
            if self.activation_at.utcoffset() is None or self.activation_at.astimezone(UTC).time() != datetime.min.time():
                raise ValueError("activation_at must be midnight UTC (Plaid transactions are date-only)")
        return self


class AllowanceView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    status: str  # preview, active, unavailable
    currency: str
    monthly_minor_units: int
    activation_at: datetime | None
    available_minor_units: int | None
    next_credit_at: datetime | None
    posted_minor_units: int
    pending_minor_units: int
    review_minor_units: int
    unmatched_refunds_minor_units: int
    windows_minor_units: dict[str, int]
    trailing_7_daily_minor_units: int | None
    estimated_days_to_exhaustion: int | None
    alert_state: str
    last_synced_at: datetime | None
    note: str | None = None
    credited_minor_units: int = 0
    cycle_credited_minor_units: int = 0
    prior_carry_minor_units: int = 0
    days_until_next_credit: int | None = None
    projected_cycle_end_minor_units: int | None = None



def month_anniversary(start: datetime, months: int) -> datetime:
    year, month = divmod(start.year * 12 + start.month - 1 + months, 12)
    month += 1
    return start.replace(year=year, month=month, day=min(start.day, calendar.monthrange(year, month)[1]))


def classify(row: dict[str, Any], rules: list[MerchantRule]) -> tuple[Kind, bool]:
    """Return (kind, needs-review). Overrides precede unreliable Plaid categories."""
    for rule in rules:
        name = str(row.get(rule.field) or "").casefold()
        if name.startswith(rule.prefix.casefold()):
            return rule.kind, False
    primary = str(row.get("pfc_primary") or "")
    detail = str(row.get("pfc_detailed") or "")
    if primary in ("TRANSFER_IN", "TRANSFER_OUT", "INCOME", "LOAN_DISBURSEMENTS"):
        return Kind.EXCLUDED, False
    if detail == "LOAN_PAYMENTS_CREDIT_CARD_PAYMENT":
        return Kind.EXCLUDED, False
    if primary in ("MEDICAL", "RENT_AND_UTILITIES", "GOVERNMENT_AND_NON_PROFIT"):
        return Kind.FIXED, False
    if primary in ("FOOD_AND_DRINK", "ENTERTAINMENT", "TRAVEL", "SHOPPING") or detail in (
        "TRANSPORTATION_TAXIS_AND_RIDE_SHARES", "GENERAL_SERVICES_STORAGE"
    ):
        return Kind.FLEXIBLE, False
    # An unrecognized positive purchase reduces room provisionally rather than vanishing.
    return Kind.FLEXIBLE, True


def _window_start(now: datetime, days: int) -> date:
    return (now - timedelta(days=days)).date()


def calculate(
    policy: AllowancePolicy, rows: list[dict[str, Any]], *, now: datetime, last_synced_at: datetime | None
) -> AllowanceView:
    if now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    now = now.astimezone(UTC)
    start = policy.activation_at.astimezone(UTC) if policy.activation_at else None
    base = dict(
        status="preview", currency=policy.currency, monthly_minor_units=policy.monthly_minor_units,
        activation_at=start, available_minor_units=None, next_credit_at=None,
        posted_minor_units=0, pending_minor_units=0, review_minor_units=0,
        unmatched_refunds_minor_units=0, windows_minor_units={}, trailing_7_daily_minor_units=None,
        estimated_days_to_exhaustion=None, alert_state="unavailable", last_synced_at=last_synced_at,
    )
    if start is None or start > now:
        return AllowanceView(**base, note="Not activated; no pre-launch debt or credit is imported")
    credits = 0
    while month_anniversary(start, credits) <= now:
        credits += 1
    next_credit = month_anniversary(start, credits)
    pending_replaced = {
        (r["account_id"], r["pending_transaction_id"])
        for r in rows if not r["pending"] and r.get("pending_transaction_id")
    }
    posted = pending = review = unmatched = 0
    windows: dict[str, int] = {
        k: 0 for k in ("current_credit_cycle", "calendar_month", "year_to_date", "trailing_7_days", "trailing_30_days")
    }
    trailing7 = 0
    cycle_start = month_anniversary(start, credits - 1).date()
    for r in rows:
        day = r["date"]
        if isinstance(day, str):
            day = date.fromisoformat(day)
        if not (start.date() <= day <= now.date()):
            continue
        if r["pending"] and (r["account_id"], r["transaction_id"]) in pending_replaced:
            continue
        if r.get("currency") not in (None, policy.currency):
            continue
        kind, uncertain = classify(r, policy.rules)
        if kind != Kind.FLEXIBLE:
            continue
        amount = int((Decimal(str(r["amount"])) * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))
        if amount < 0 and not any(
            rule.kind == Kind.FLEXIBLE and str(r.get(rule.field) or "").casefold().startswith(rule.prefix.casefold())
            for rule in policy.rules
        ):
            unmatched += -amount
            continue  # Never automatically credit unrelated refunds based on inferred categories.
        if r["pending"]:
            pending += amount
        else:
            posted += amount
        if uncertain and amount > 0:
            review += amount
        if day >= cycle_start:
            windows["current_credit_cycle"] += amount
        if day >= now.date().replace(day=1):
            windows["calendar_month"] += amount
        if day >= date(now.year, 1, 1):
            windows["year_to_date"] += amount
        if day >= _window_start(now, 7):
            windows["trailing_7_days"] += amount
            trailing7 += max(0, amount)
        if day >= _window_start(now, 30):
            windows["trailing_30_days"] += amount
    available = credits * policy.monthly_minor_units - posted - pending
    prior_carry = (credits - 1) * policy.monthly_minor_units - (posted + pending - windows["current_credit_cycle"])
    days_observed = max(1, min(7, (now.date() - start.date()).days + 1))
    daily = trailing7 // days_observed
    days_left = max(1, (next_credit.date() - now.date()).days)
    projected_burn = daily * days_left
    if available <= 0:
        alert = "exceeded"
    elif projected_burn > available:
        alert = "warning"
    else:
        alert = "normal"
    runway = max(0, available // daily) if daily > 0 else None
    return AllowanceView(
        **(base | dict(status="active", available_minor_units=available, next_credit_at=next_credit,
                      posted_minor_units=posted, pending_minor_units=pending,
                      review_minor_units=review, unmatched_refunds_minor_units=unmatched,
                      windows_minor_units=dict(windows), trailing_7_daily_minor_units=daily,
                      estimated_days_to_exhaustion=runway, alert_state=alert, note=None,
                      credited_minor_units=credits * policy.monthly_minor_units,
                      cycle_credited_minor_units=policy.monthly_minor_units, prior_carry_minor_units=prior_carry,
                      days_until_next_credit=days_left, projected_cycle_end_minor_units=available - projected_burn))
    )
