"""Account for a configurable flexible allowance using dated Plaid purchases."""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Kind(StrEnum):
    FLEXIBLE = "flexible"
    FIXED = "fixed"
    EXCLUDED = "excluded"


class Status(StrEnum):
    PREVIEW = "preview"
    ACTIVE = "active"
    UNAVAILABLE = "unavailable"


class PaceAlert(StrEnum):
    NORMAL = "normal"
    WARNING = "warning"
    EXCEEDED = "exceeded"
    UNAVAILABLE = "unavailable"


class MerchantRule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    field: Literal["name", "merchant_name"]
    prefix: str = Field(min_length=2)
    kind: Kind


class CategoryRule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    field: Literal["pfc_primary", "pfc_detailed"]
    value: str = Field(min_length=2)
    kind: Kind


class AllowancePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    monthly_minor_units: int = Field(gt=0)
    activation_at: datetime | None = None
    spending_account_ids: list[str] = Field(min_length=1)
    currency: Literal["USD"] = "USD"
    rules: list[MerchantRule | CategoryRule] = Field(min_length=1)
    max_sync_age_hours: int = Field(default=72, ge=1, le=720)

    @model_validator(mode="after")
    def _validate_policy(self) -> AllowancePolicy:
        if len(self.spending_account_ids) != len(set(self.spending_account_ids)):
            raise ValueError("spending account IDs must be unique")
        return self

    @field_validator("activation_at")
    @classmethod
    def _date_only_boundary(cls, value: datetime | None) -> datetime | None:
        # Plaid purchase timestamps are unavailable; a partial-day boundary would import earlier charges.
        if value is not None and (value.utcoffset() is None or value.astimezone(UTC).time() != datetime.min.time()):
            raise ValueError("activation_at must be midnight UTC (Plaid transactions are date-only)")
        return value


class Transaction(BaseModel):
    """Plaid mirror transaction fields needed by the allowance calculator."""

    account_id: str
    transaction_id: str
    pending_transaction_id: str | None
    date: date
    amount: Decimal
    pending: bool
    name: str
    merchant_name: str | None
    pfc_primary: str | None
    pfc_detailed: str | None
    currency: str | None


@dataclass(frozen=True)
class Purchase:
    transaction: Transaction
    minor_units: int
    needs_review: bool


class Windows(BaseModel):
    current_credit_cycle: int
    calendar_month: int
    year_to_date: int
    trailing_7_days: int
    trailing_30_days: int


class AllowanceView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    status: Status
    currency: str
    monthly_minor_units: int
    activation_at: datetime | None
    available_minor_units: int | None
    next_credit_at: datetime | None
    posted_minor_units: int
    pending_minor_units: int
    review_minor_units: int
    unmatched_refunds_minor_units: int
    windows_minor_units: Windows | None = Field(
        description="Spend after activation in each reporting window; null until active."
    )
    trailing_7_daily_minor_units: int | None
    estimated_exhaustion_at: datetime | None = Field(
        description="Projected at trailing seven-day positive purchase pace, ignoring future credits; null if no recent spend."
    )
    alert_state: PaceAlert
    last_synced_at: datetime | None
    note: str | None = None
    prior_carry_minor_units: int = 0
    projected_cycle_end_minor_units: int | None = None


def month_anniversary(start: datetime, months: int) -> datetime:
    year, month = divmod(start.year * 12 + start.month - 1 + months, 12)
    month += 1
    return start.replace(year=year, month=month, day=min(start.day, calendar.monthrange(year, month)[1]))


def matching_rule(
    transaction: Transaction, rules: list[MerchantRule | CategoryRule]
) -> MerchantRule | CategoryRule | None:
    for rule in rules:
        if isinstance(rule, MerchantRule):
            name = transaction.name if rule.field == "name" else transaction.merchant_name
            if name is not None and name.casefold().startswith(rule.prefix.casefold()):
                return rule
        else:
            category = transaction.pfc_primary if rule.field == "pfc_primary" else transaction.pfc_detailed
            if category == rule.value:
                return rule
    return None


def calculate(
    policy: AllowancePolicy, transactions: list[Transaction], *, now: datetime, last_synced_at: datetime | None
) -> AllowanceView:
    if now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    now = now.astimezone(UTC)
    start = policy.activation_at.astimezone(UTC) if policy.activation_at else None
    if start is None or start > now:
        return AllowanceView(
            status=Status.PREVIEW,
            currency=policy.currency,
            monthly_minor_units=policy.monthly_minor_units,
            activation_at=start,
            available_minor_units=None,
            next_credit_at=None,
            posted_minor_units=0,
            pending_minor_units=0,
            review_minor_units=0,
            unmatched_refunds_minor_units=0,
            windows_minor_units=None,
            trailing_7_daily_minor_units=None,
            estimated_exhaustion_at=None,
            alert_state=PaceAlert.UNAVAILABLE,
            last_synced_at=last_synced_at,
            note="Not activated; no pre-launch debt or credit is imported",
        )

    credits = 0
    while month_anniversary(start, credits) <= now:
        credits += 1
    next_credit = month_anniversary(start, credits)
    superseded = {
        (transaction.account_id, transaction.pending_transaction_id)
        for transaction in transactions
        if not transaction.pending and transaction.pending_transaction_id is not None
    }
    # Keep each included purchase once, with its category and posting state.
    included: list[Purchase] = []
    unmatched = 0
    for transaction in transactions:
        if not start.date() <= transaction.date <= now.date():
            continue
        if transaction.pending and (transaction.account_id, transaction.transaction_id) in superseded:
            continue
        if transaction.currency not in (None, policy.currency):
            continue
        rule = matching_rule(transaction, policy.rules)
        if rule is not None and rule.kind != Kind.FLEXIBLE:
            continue
        amount = int((transaction.amount * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))
        # An inferred category alone cannot associate a refund with an actual discretionary purchase.
        if amount < 0 and not isinstance(rule, MerchantRule):
            unmatched += -amount
            continue
        included.append(Purchase(transaction=transaction, minor_units=amount, needs_review=rule is None))

    posted = sum(p.minor_units for p in included if not p.transaction.pending)
    pending = sum(p.minor_units for p in included if p.transaction.pending)
    review = sum(p.minor_units for p in included if p.needs_review and p.minor_units > 0)
    cycle_start = month_anniversary(start, credits - 1).date()
    windows = Windows(
        current_credit_cycle=sum(p.minor_units for p in included if p.transaction.date >= cycle_start),
        calendar_month=sum(p.minor_units for p in included if p.transaction.date >= now.date().replace(day=1)),
        year_to_date=sum(p.minor_units for p in included if p.transaction.date >= date(now.year, 1, 1)),
        trailing_7_days=sum(p.minor_units for p in included if p.transaction.date >= (now - timedelta(days=6)).date()),
        trailing_30_days=sum(
            p.minor_units for p in included if p.transaction.date >= (now - timedelta(days=29)).date()
        ),
    )
    trailing_positive = sum(
        max(0, p.minor_units) for p in included if p.transaction.date >= (now - timedelta(days=6)).date()
    )
    daily = trailing_positive // max(1, min(7, (now.date() - start.date()).days + 1))
    available = credits * policy.monthly_minor_units - posted - pending
    projected_end = available - daily * max(1, (next_credit.date() - now.date()).days)
    alert = PaceAlert.EXCEEDED if available <= 0 else PaceAlert.WARNING if projected_end < 0 else PaceAlert.NORMAL
    return AllowanceView(
        status=Status.ACTIVE,
        currency=policy.currency,
        monthly_minor_units=policy.monthly_minor_units,
        activation_at=start,
        available_minor_units=available,
        next_credit_at=next_credit,
        posted_minor_units=posted,
        pending_minor_units=pending,
        review_minor_units=review,
        unmatched_refunds_minor_units=unmatched,
        windows_minor_units=windows,
        trailing_7_daily_minor_units=daily,
        estimated_exhaustion_at=now + timedelta(days=max(0, available) / daily) if daily else None,
        alert_state=alert,
        last_synced_at=last_synced_at,
        prior_carry_minor_units=(credits - 1) * policy.monthly_minor_units
        - (posted + pending - windows.current_credit_cycle),
        projected_cycle_end_minor_units=projected_end,
    )
