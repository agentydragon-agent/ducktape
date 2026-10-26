"""Annual funding draw implied by observed consumption and current eligible assets."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date as date_type, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, model_validator

from finance.plaid.spend.allowance import AllowancePolicy, Kind, Transaction, matching_rule, superseded_pending_keys
from finance.plaid.spend.portfolio_models import PortfolioPolicy, PortfolioView

_YEAR_DAYS = Decimal("365.2425")


class SustainabilityDisplay(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    windows_days: list[int] = Field(default_factory=lambda: [30, 90, 365], min_length=1)
    default_window_days: int = 90
    reference_draw_rates: list[FiniteFloat] = Field(default_factory=lambda: [0.03, 0.04])

    @model_validator(mode="after")
    def _valid_windows(self) -> SustainabilityDisplay:
        if any(not 1 <= days <= 730 for days in self.windows_days) or len(set(self.windows_days)) != len(
            self.windows_days
        ):
            raise ValueError("windows must be distinct day counts between 1 and 730")
        if self.default_window_days not in self.windows_days:
            raise ValueError("default window must be configured")
        if any(not 0 < rate < 1 for rate in self.reference_draw_rates):
            raise ValueError("reference draw rates must be finite fractions between zero and one")
        return self


class WithdrawalTax(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    model: Literal["effective_rate"] = "effective_rate"
    rate: FiniteFloat | None = Field(default=None, ge=0, lt=1)
    assumption_note: str | None = None
    as_of: date_type | None = None

    @model_validator(mode="after")
    def _documented_assumption(self) -> WithdrawalTax:
        if self.rate is not None and (
            not self.assumption_note or not self.assumption_note.strip() or self.as_of is None
        ):
            raise ValueError("a tax rate requires a dated assumption note")
        if self.rate is None and (self.assumption_note is not None or self.as_of is not None):
            raise ValueError("tax provenance requires a tax rate")
        return self


class SustainabilityPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    currency: Literal["USD"] = "USD"
    display: SustainabilityDisplay = Field(default_factory=SustainabilityDisplay)
    portfolio: PortfolioPolicy
    withdrawal_tax: WithdrawalTax = Field(default_factory=WithdrawalTax)
    include_excluded_categories: list[str] = Field(default_factory=list)
    confirmed_refund_rule_ids: list[str] = Field(default_factory=list)
    known_issues: list[str] = Field(default_factory=list)


class SustainabilityHistoryPoint(BaseModel):
    date: date_type
    covered_days: int
    annualized_spending_minor_units: int | None
    spending_draw_rate: float | None
    tax_adjusted_draw_rate: float | None


class SustainabilityView(BaseModel):
    generated_at: datetime
    status: Literal["disabled", "ready", "unavailable"]
    currency: Literal["USD"] = "USD"
    time_zone: str
    window_days: int
    available_windows_days: list[int]
    period_start: date_type
    period_end: date_type
    covered_days: int
    mandatory_minor_units: int
    flexible_minor_units: int
    provisional_minor_units: int
    spending_minor_units: int
    annualized_spending_minor_units: int | None
    estimated_annual_draw_minor_units: int | None
    spending_draw_rate: float | None
    tax_adjusted_draw_rate: float | None
    effective_tax_rate: float | None
    tax_assumption_note: str | None = None
    tax_assumption_as_of: date_type | None = None
    reference_draw_rates: list[float]
    portfolio: PortfolioView
    history: list[SustainabilityHistoryPoint]
    issues: list[str]
    known_issues: list[str]


@dataclass(frozen=True)
class Consumption:
    mandatory: int = 0
    flexible: int = 0
    provisional: int = 0

    @property
    def total(self) -> int:
        return self.mandatory + self.flexible + self.provisional


def empty_portfolio() -> PortfolioView:
    return PortfolioView(
        status="unavailable",
        net_minor_units=None,
        assets_minor_units=None,
        liabilities_minor_units=None,
        excluded_minor_units=None,
        sources=[],
    )


def disabled_view(now: datetime, time_zone: str, today: date_type) -> SustainabilityView:
    return SustainabilityView(
        generated_at=now,
        status="disabled",
        time_zone=time_zone,
        window_days=90,
        available_windows_days=[30, 90, 365],
        period_start=today - timedelta(days=90),
        period_end=today - timedelta(days=1),
        covered_days=0,
        mandatory_minor_units=0,
        flexible_minor_units=0,
        provisional_minor_units=0,
        spending_minor_units=0,
        annualized_spending_minor_units=None,
        estimated_annual_draw_minor_units=None,
        spending_draw_rate=None,
        tax_adjusted_draw_rate=None,
        effective_tax_rate=None,
        reference_draw_rates=[0.03, 0.04],
        portfolio=empty_portfolio(),
        history=[],
        issues=["Sustainability is not configured."],
        known_issues=[],
    )


def calculate_sustainability(
    policy: SustainabilityPolicy,
    allowance: AllowancePolicy,
    transactions: list[Transaction],
    portfolio: PortfolioView,
    *,
    now: datetime,
    window_days: int,
    source_issues: list[str],
) -> SustainabilityView:
    if now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    if window_days not in policy.display.windows_days:
        raise ValueError("window must be configured")
    today = now.astimezone(allowance.time_zone).date()
    end = today - timedelta(days=1)
    requested_start = today - timedelta(days=window_days)
    issues = list(source_issues)
    superseded = superseded_pending_keys(transactions)
    days_by_account: dict[str, list[date_type]] = defaultdict(list)
    daily: dict[date_type, list[int]] = defaultdict(lambda: [0, 0, 0])
    held_refunds = other_currency = 0
    for transaction in transactions:
        if transaction.account_id not in allowance.spending_account_ids:
            continue
        day = transaction.report_day(allowance.time_zone)
        if day > end:
            continue
        if transaction.pending and (transaction.account_id, transaction.transaction_id) in superseded:
            continue
        # Even a transfer establishes that a source has some recorded history.
        days_by_account[transaction.account_id].append(day)
        if transaction.currency not in (None, policy.currency):
            other_currency += int(requested_start <= day <= end)
            continue
        rule = matching_rule(transaction, allowance.rules)
        if (
            rule is not None
            and rule.kind == Kind.EXCLUDED
            and rule.analysis_category not in policy.include_excluded_categories
        ):
            continue
        amount = int((transaction.amount * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))
        if amount < 0 and (rule is None or rule.id not in policy.confirmed_refund_rule_ids):
            held_refunds += int(requested_start <= day <= end)
            continue
        bucket = (
            0 if rule is not None and rule.kind == Kind.FIXED else 2 if rule is None or rule.kind == Kind.REVIEW else 1
        )
        daily[day][bucket] += amount

    covered_starts = [
        min(days_by_account[account]) for account in allowance.spending_account_ids if days_by_account[account]
    ]
    if len(covered_starts) != len(allowance.spending_account_ids):
        issues.append("Some spending accounts have no recorded history before the cutoff; coverage is unknown.")
    coverage_start = max(covered_starts) if covered_starts else today
    start = max(requested_start, coverage_start)
    covered_days = max(0, (end - start).days + 1)
    if covered_days < window_days:
        issues.append(
            f"Only {covered_days} of {window_days} days have common recorded history; annualization uses those days."
        )
    if held_refunds:
        issues.append(
            f"{held_refunds} unconfirmed incoming credits are held outside spending; refunds may overstate net spending."
        )
    if other_currency:
        issues.append(
            f"{other_currency} transactions in other currencies are not converted; spending coverage is incomplete."
        )
    if policy.withdrawal_tax.rate is None:
        issues.append(
            "Withdrawal taxes are not modeled; the displayed spending-only rate understates tax-inclusive funding needs."
        )
    source_ready = (
        not source_issues and len(covered_starts) == len(allowance.spending_account_ids) and other_currency == 0
    )
    net = portfolio.net_minor_units if portfolio.status == "ready" else None
    if portfolio.status != "ready":
        issues.append("Portfolio coverage or freshness is unavailable; see source details.")
    ready = source_ready and covered_days > 0 and net is not None and net > 0
    if net is not None and net <= 0:
        issues.append("Eligible funding assets are not positive; a withdrawal percentage is unavailable.")
    totals = [sum(values[i] for day, values in daily.items() if start <= day <= end) for i in range(3)]
    consumption = Consumption(*totals)
    annual = _annualize(consumption.total, covered_days) if source_ready and covered_days else None
    draw = _tax_adjust(annual, policy.withdrawal_tax.rate)
    if annual is not None and annual < 0:
        issues.append(
            "Net refunds exceed purchases in this window; do not interpret a negative pace as sustainable income."
        )
    history = []
    # Reuse the same complete-day bounds and rounding as the headline. Every
    # historical point uses today's eligible assets, never reconstructed holdings.
    chart_start = max(coverage_start, today - timedelta(days=365))
    chart_day = chart_start
    while chart_day <= end:
        point_start = max(coverage_start, chart_day - timedelta(days=window_days - 1))
        point_days = (chart_day - point_start).days + 1
        point_total = sum(sum(values) for day, values in daily.items() if point_start <= day <= chart_day)
        point_annual = _annualize(point_total, point_days) if source_ready else None
        point_draw = _tax_adjust(point_annual, policy.withdrawal_tax.rate)
        history.append(
            SustainabilityHistoryPoint(
                date=chart_day,
                covered_days=point_days,
                annualized_spending_minor_units=point_annual,
                spending_draw_rate=point_annual / net if ready and point_annual is not None and net else None,
                tax_adjusted_draw_rate=point_draw / net if ready and point_draw is not None and net else None,
            )
        )
        chart_day += timedelta(days=1)
    return SustainabilityView(
        generated_at=now,
        status="ready" if ready else "unavailable",
        time_zone=allowance.time_zone.key,
        window_days=window_days,
        available_windows_days=policy.display.windows_days,
        period_start=start,
        period_end=end,
        covered_days=covered_days,
        mandatory_minor_units=consumption.mandatory,
        flexible_minor_units=consumption.flexible,
        provisional_minor_units=consumption.provisional,
        spending_minor_units=consumption.total,
        annualized_spending_minor_units=annual,
        estimated_annual_draw_minor_units=draw,
        spending_draw_rate=annual / net if ready and annual is not None and net else None,
        tax_adjusted_draw_rate=draw / net if ready and draw is not None and net else None,
        effective_tax_rate=policy.withdrawal_tax.rate,
        tax_assumption_note=policy.withdrawal_tax.assumption_note,
        tax_assumption_as_of=policy.withdrawal_tax.as_of,
        reference_draw_rates=policy.display.reference_draw_rates,
        portfolio=portfolio,
        history=history,
        issues=issues,
        known_issues=policy.known_issues,
    )


def _annualize(amount: int, days: int) -> int:
    return int((Decimal(amount) * _YEAR_DAYS / days).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _tax_adjust(annual: int | None, rate: float | None) -> int | None:
    if annual is None or rate is None:
        return None
    return int((Decimal(annual) / (1 - Decimal(str(rate)))).quantize(Decimal(1), rounding=ROUND_HALF_UP))
