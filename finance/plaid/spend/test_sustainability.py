"""Funding-rate accounting boundaries using synthetic purchases and portfolios."""

from datetime import UTC, date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
import pytest_bazel
from pydantic import ValidationError

from finance.plaid.spend.allowance import (
    AllOf,
    AllowancePolicy,
    AnalysisCategory,
    DateRange,
    Kind,
    NamePrefix,
    Rule,
    RuleScope,
    Transaction,
)
from finance.plaid.spend.models import SpendConfiguration
from finance.plaid.spend.portfolio_models import PlaidSourcePolicy, PortfolioPolicy, PortfolioSources, PortfolioView
from finance.plaid.spend.sustainability import (
    SustainabilityDisplay,
    SustainabilityPolicy,
    WithdrawalTax,
    calculate_sustainability,
)

_NOW = datetime(2026, 4, 1, 7, tzinfo=UTC)  # April 1 midnight in Pacific.


def policy(*, tax_rate: float | None = None) -> SustainabilityPolicy:
    return SustainabilityPolicy(
        display=SustainabilityDisplay(windows_days=[30, 90, 365], default_window_days=90),
        portfolio=PortfolioPolicy(sources=PortfolioSources(plaid=PlaidSourcePolicy(asset_account_ids=["assets"]))),
        withdrawal_tax=WithdrawalTax()
        if tax_rate is None
        else WithdrawalTax(rate=tax_rate, assumption_note="Synthetic effective-tax scenario.", as_of=date(2026, 1, 1)),
        confirmed_refund_rule_ids=["confirmed-refund"],
    )


def allowance() -> AllowancePolicy:
    return AllowancePolicy(
        monthly_minor_units=10_000,
        activation_at=date(2026, 3, 20),
        time_zone=ZoneInfo("America/Los_Angeles"),
        spending_account_ids={"card"},
        rules=[
            Rule(
                condition=AllOf(
                    conditions=[
                        NamePrefix(field="name", prefix="CONFIRMED REFUND"),
                        DateRange(start=date(2026, 3, 6), end=date(2026, 3, 6)),
                    ]
                ),
                kind=Kind.FLEXIBLE,
                scope=RuleScope.ONE_OFF,
                id="confirmed-refund",
                description="Synthetic fixture confirms this refund on 2026-03-06.",
            ),
            Rule(condition=NamePrefix(field="name", prefix="RENT"), kind=Kind.FIXED),
            Rule(condition=NamePrefix(field="name", prefix="TRANSFER"), kind=Kind.EXCLUDED),
            Rule(condition=NamePrefix(field="name", prefix="SHOP"), kind=Kind.FLEXIBLE),
        ],
        analysis_categories={"unclassified": AnalysisCategory(label="Unclassified", color="#777777")},
    )


def transaction(
    day: date,
    amount: str,
    name: str = "SHOP",
    *,
    key: str = "purchase",
    pending: bool = False,
    replacement: str | None = None,
    instant: datetime | None = None,
) -> Transaction:
    return Transaction(
        account_id="card",
        transaction_id=key,
        pending_transaction_id=replacement,
        date=day,
        authorized_datetime=instant,
        amount=Decimal(amount),
        pending=pending,
        name=name,
        merchant_name=None,
        pfc_primary=None,
        pfc_detailed=None,
        currency="USD",
    )


def portfolio(*, ready: bool = True) -> PortfolioView:
    return PortfolioView(
        status="ready" if ready else "unavailable",
        net_minor_units=1_000_000 if ready else None,
        assets_minor_units=1_200_000 if ready else None,
        liabilities_minor_units=100_000 if ready else None,
        excluded_minor_units=100_000 if ready else None,
        sources=[],
    )


def test_total_consumption_includes_precommitment_mandatory_and_pending_once() -> None:
    result = calculate_sustainability(
        policy(tax_rate=0.2),
        allowance(),
        [
            transaction(date(2026, 1, 1), "0", "TRANSFER", key="history"),
            transaction(date(2026, 3, 1), "100", "RENT", key="rent"),
            transaction(date(2026, 3, 2), "20", pending=True, key="pending"),
            transaction(date(2026, 3, 3), "25", replacement="pending", key="posted"),
            transaction(date(2026, 3, 4), "10", "UNKNOWN", key="unknown"),
            transaction(date(2026, 3, 5), "5000", "TRANSFER", key="transfer"),
            transaction(date(2026, 3, 6), "-5", "CONFIRMED REFUND", key="refund"),
            transaction(date(2026, 3, 7), "-50", key="held-credit"),
            transaction(date(2026, 4, 1), "900", key="today"),
        ],
        portfolio(),
        now=_NOW,
        window_days=90,
        source_issues=[],
    )
    assert result.status == "ready"
    assert result.covered_days == 90
    assert (result.mandatory_minor_units, result.flexible_minor_units, result.provisional_minor_units) == (
        10_000,
        2000,
        1000,
    )
    assert result.spending_minor_units == 13_000
    assert result.annualized_spending_minor_units == 52_757
    assert result.estimated_annual_draw_minor_units == 65_946
    assert result.tax_adjusted_draw_rate == pytest.approx(0.065946)
    assert result.history[-1].annualized_spending_minor_units == result.annualized_spending_minor_units
    assert result.history[-1].tax_adjusted_draw_rate == result.tax_adjusted_draw_rate
    assert any("unconfirmed" in issue for issue in result.issues)


def test_partial_window_uses_actual_covered_days_and_pacific_instant() -> None:
    result = calculate_sustainability(
        policy(),
        allowance(),
        [
            transaction(date(2026, 3, 22), "10", key="start"),
            transaction(date(2026, 4, 1), "10", key="cross-midnight", instant=datetime(2026, 4, 1, 6, tzinfo=UTC)),
        ],
        portfolio(),
        now=_NOW,
        window_days=90,
        source_issues=[],
    )
    assert result.covered_days == 10
    assert result.period_end == date(2026, 3, 31)
    assert result.spending_minor_units == 2000
    assert result.annualized_spending_minor_units == 73_049
    assert result.tax_adjusted_draw_rate is None
    assert any("Only 10 of 90" in issue for issue in result.issues)


def test_missing_portfolio_preserves_observed_spending_without_showing_rate() -> None:
    result = calculate_sustainability(
        policy(),
        allowance(),
        [transaction(date(2026, 1, 1), "10")],
        portfolio(ready=False),
        now=_NOW,
        window_days=90,
        source_issues=[],
    )
    assert result.status == "unavailable"
    assert result.annualized_spending_minor_units == 4058
    assert result.spending_draw_rate is None
    assert all(point.spending_draw_rate is None for point in result.history)


def test_stale_spending_does_not_produce_a_funding_estimate() -> None:
    result = calculate_sustainability(
        policy(),
        allowance(),
        [transaction(date(2026, 1, 1), "10")],
        portfolio(),
        now=_NOW,
        window_days=90,
        source_issues=["Spending source is stale."],
    )
    assert result.status == "unavailable"
    assert result.annualized_spending_minor_units is None
    assert result.spending_draw_rate is None


@pytest.mark.parametrize("rate", [-0.1, 1.0, float("nan"), float("inf")])
def test_tax_fraction_must_be_finite_and_below_one(rate: float) -> None:
    with pytest.raises(ValidationError):
        WithdrawalTax(rate=rate, assumption_note="Synthetic", as_of=date(2026, 1, 1))


def test_tax_fraction_requires_provenance_and_shared_classification() -> None:
    with pytest.raises(ValidationError, match="dated assumption"):
        WithdrawalTax(rate=0.2)
    with pytest.raises(ValidationError, match="requires shared"):
        SpendConfiguration(cards=[], sustainability=policy())


if __name__ == "__main__":
    pytest_bazel.main()
