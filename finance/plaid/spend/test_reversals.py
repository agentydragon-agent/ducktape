"""Full reversals use unique, durable selectors and never net an isolated credit."""

from datetime import UTC, date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
import pytest_bazel
from pydantic import ValidationError

from finance.plaid.spend.allowance import (
    AllOf,
    AllowancePolicy,
    AmountExact,
    AnalysisCategory,
    DateRange,
    Disposition,
    Kind,
    NamePrefix,
    ReversalPair,
    Rule,
    Transaction,
    TransactionDecision,
    calculate,
    resolve_reversal_pairs,
)
from finance.plaid.spend.portfolio_models import PlaidSourcePolicy, PortfolioPolicy, PortfolioSources, PortfolioView
from finance.plaid.spend.sustainability import SustainabilityPolicy, WithdrawalTax, calculate_sustainability

_ZONE = ZoneInfo("UTC")
_NOW = datetime(2026, 4, 1, tzinfo=UTC)


def pair(*, original_day: date = date(2026, 3, 2)) -> ReversalPair:
    return ReversalPair(
        id="example-return",
        description="Synthetic bank return, confirmed by the owner.",
        original=AllOf(
            conditions=[
                DateRange(start=original_day, end=original_day),
                NamePrefix(field="name", prefix="EXAMPLE DEBIT"),
                AmountExact(value="80.00"),
            ]
        ),
        reversal=AllOf(
            conditions=[
                DateRange(start=date(2026, 3, 5), end=date(2026, 3, 5)),
                NamePrefix(field="name", prefix="EXAMPLE RETURN"),
                AmountExact(value="-80.00"),
            ]
        ),
    )


def policy(pairs: list[ReversalPair]) -> AllowancePolicy:
    return AllowancePolicy(
        monthly_minor_units=100_000,
        activation_at=date(2026, 3, 1),
        spending_account_ids={"card", "other-card"},
        rules=[Rule(condition=NamePrefix(field="name", prefix="EXAMPLE"), kind=Kind.FLEXIBLE)],
        reversal_pairs=pairs,
        analysis_categories={"unclassified": AnalysisCategory(label="Unclassified", color="#777777")},
    )


def transaction(day: date, amount: str, name: str, key: str) -> Transaction:
    return Transaction(
        account_id="card",
        transaction_id=key,
        pending_transaction_id=None,
        date=day,
        amount=Decimal(amount),
        pending=False,
        name=name,
        merchant_name=None,
        pfc_primary=None,
        pfc_detailed=None,
        currency="USD",
    )


def legs() -> list[Transaction]:
    return [
        transaction(date(2026, 3, 2), "80", "EXAMPLE DEBIT", "debit"),
        transaction(date(2026, 3, 5), "-80", "EXAMPLE RETURN", "credit"),
    ]


def test_reversal_removes_both_legs_but_keeps_replacement_and_normal_refunds() -> None:
    decisions: list[TransactionDecision] = []
    result = calculate(
        policy([pair()]),
        [
            *legs(),
            transaction(date(2026, 3, 6), "90", "EXAMPLE DEBIT", "replacement"),
            transaction(date(2026, 3, 7), "-4", "OTHER CREDIT", "unconfirmed"),
        ],
        time_zone=_ZONE,
        now=_NOW,
        last_synced_at=_NOW,
        decisions=decisions,
    )
    assert result.posted_minor_units == 9_000
    assert result.unmatched_refunds_minor_units == 400
    assert result.reversal_pairs[0].issues == []
    for decision in decisions[:2]:
        assert decision.disposition == Disposition.REVERSED
        assert decision.effective_kind == Kind.EXCLUDED
        assert decision.rule is not None
        assert decision.rule.kind == Kind.FLEXIBLE
        assert decision.reversal_pair == pair()
        assert decision.allowance_minor_units == 0
        assert not any(decision.pace_effects_minor_units.values())
    assert decisions[2].disposition == Disposition.COUNTED
    assert decisions[3].disposition == Disposition.HELD_REFUND


@pytest.mark.parametrize("missing_leg", [0, 1])
def test_missing_leg_preserves_conservative_accounting(missing_leg: int) -> None:
    rows = legs()
    rows.pop(missing_leg)
    result = calculate(policy([pair()]), rows, time_zone=_ZONE, now=_NOW, last_synced_at=_NOW)
    assert result.reversal_pairs[0].issues
    assert result.posted_minor_units == (8_000 if missing_leg == 1 else 0)
    assert result.unmatched_refunds_minor_units == (8_000 if missing_leg == 0 else 0)


@pytest.mark.parametrize("ambiguous_leg", [0, 1])
def test_ambiguous_selector_does_not_exclude_any_leg(ambiguous_leg: int) -> None:
    rows = legs()
    rows.append(rows[ambiguous_leg].model_copy(update={"transaction_id": "another-retained-row"}))
    result = resolve_reversal_pairs(policy([pair()]), rows, time_zone=_ZONE, today=_NOW.date())
    assert result.pairs_by_transaction == {}
    assert any("matched 2" in issue for issue in result.resolutions[0].issues)


@pytest.mark.parametrize(
    ("changes", "issue"),
    [
        ({"pending": True}, "pending"),
        ({"account_id": "other-card"}, "same account"),
        ({"currency": "EUR"}, "currency"),
        ({"amount": Decimal(-79)}, "equal and opposite"),
        ({"amount": Decimal(80)}, "positive original"),
    ],
)
def test_inconsistent_pair_is_not_applied(changes: dict[str, object], issue: str) -> None:
    # Omit the amount guard here so ledger consistency, rather than selector matching, is exercised.
    configured = pair()
    configured = configured.model_copy(update={"reversal": AllOf(conditions=configured.reversal.conditions[:2])})
    rows = legs()
    rows[1] = rows[1].model_copy(update=changes)
    result = resolve_reversal_pairs(policy([configured]), rows, time_zone=_ZONE, today=_NOW.date())
    assert not result.pairs_by_transaction
    assert any(issue in problem for problem in result.resolutions[0].issues)


def test_missing_currency_means_policy_currency_and_pending_replacement_is_deduplicated() -> None:
    rows = legs()
    rows[1] = rows[1].model_copy(update={"currency": None, "pending_transaction_id": "pending-credit"})
    rows.append(rows[1].model_copy(update={"pending": True, "transaction_id": "pending-credit"}))
    result = resolve_reversal_pairs(policy([pair()]), rows, time_zone=_ZONE, today=_NOW.date())
    assert len(result.pairs_by_transaction) == 2
    assert result.resolutions[0].issues == []


def test_overlapping_assertions_are_both_unresolved() -> None:
    result = resolve_reversal_pairs(
        policy([pair(), pair().model_copy(update={"id": "another-return"})]), legs(), time_zone=_ZONE, today=_NOW.date()
    )
    assert not result.pairs_by_transaction
    assert all(
        any("another reversal pair" in issue for issue in resolution.issues) for resolution in result.resolutions
    )


def test_future_reversal_does_not_rewrite_history_yet() -> None:
    result = resolve_reversal_pairs(policy([pair()]), legs(), time_zone=_ZONE, today=date(2026, 3, 3))
    assert not result.pairs_by_transaction
    assert any("Reversal selector matched 0" in issue for issue in result.resolutions[0].issues)


@pytest.mark.parametrize("original_day", [date(2026, 1, 1), date(2026, 3, 2)])
def test_reconciled_history_has_no_artificial_credit_dip_or_original_spike(original_day: date) -> None:
    rows = legs()
    rows[0] = rows[0].model_copy(update={"date": original_day})
    rows.append(transaction(date(2026, 1, 1), "0", "HISTORY", "coverage"))
    configured = policy([pair(original_day=original_day)])
    configured = configured.model_copy(update={"spending_account_ids": {"card"}})
    result = calculate_sustainability(
        SustainabilityPolicy(
            portfolio=PortfolioPolicy(sources=PortfolioSources(plaid=PlaidSourcePolicy(asset_account_ids=["assets"]))),
            withdrawal_tax=WithdrawalTax(rate=0.2, assumption_note="Synthetic assumption", as_of=date(2026, 1, 1)),
        ),
        configured,
        rows,
        PortfolioView(
            status="ready",
            assets_minor_units=1_000_000,
            liabilities_minor_units=0,
            excluded_minor_units=0,
            net_minor_units=1_000_000,
            sources=[],
        ),
        time_zone=_ZONE,
        now=_NOW,
        window_days=30,
        source_issues=[],
    )
    assert result.status == "ready"
    assert result.spending_minor_units == 0
    assert result.estimated_annual_draw_minor_units == 0
    assert result.history
    assert all(point.annualized_spending_minor_units == 0 for point in result.history)
    assert not any("unconfirmed" in issue for issue in result.issues)


def test_pair_schema_requires_bounded_identifying_selectors_and_unique_ids() -> None:
    raw = pair().model_dump(mode="json")
    raw["original"]["conditions"] = [
        {"type": "amount_sign", "sign": "positive"},
        {"type": "date_range", "start": "2026-01-01", "end": "2026-01-01"},
    ]
    with pytest.raises(ValidationError, match="name, category, amount"):
        ReversalPair.model_validate(raw)
    raw["original"]["conditions"][0] = {"type": "name_prefix", "field": "name", "prefix": "EXAMPLE"}
    raw["original"]["conditions"][1]["end"] = "2026-03-01"
    with pytest.raises(ValidationError, match="at most"):
        ReversalPair.model_validate(raw)
    raw["original"]["conditions"][1].pop("end")
    with pytest.raises(ValidationError, match="bounded"):
        ReversalPair.model_validate(raw)
    with pytest.raises(ValidationError, match="unique ids"):
        policy([pair(), pair()])
    assert AmountExact(value="-80.00").value == "-80.00"
    assert policy([]).reversal_pairs == []


if __name__ == "__main__":
    pytest_bazel.main()
