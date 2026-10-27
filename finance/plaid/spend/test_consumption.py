"""Shared report decisions, with synthetic purchases only."""

from datetime import UTC, date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
import pytest_bazel

from finance.plaid.spend.allowance import (
    AllowancePolicy,
    AnalysisCategory,
    Kind,
    NamePrefix,
    ReversalPair,
    Rule,
    Transaction,
)
from finance.plaid.spend.consumption import ConsumptionDisposition, ConsumptionMode, prepare_consumption

_TODAY = date(2026, 4, 1)
_ZONE = ZoneInfo("America/Los_Angeles")


def transaction(name: str, amount: str = "10.00", **changes: object) -> Transaction:
    return Transaction.model_validate(
        {
            "account_id": "card",
            "transaction_id": name,
            "pending_transaction_id": None,
            "date": date(2026, 3, 10),
            "amount": Decimal(amount),
            "pending": False,
            "name": name,
            "merchant_name": None,
            "pfc_primary": None,
            "pfc_detailed": None,
            "currency": "USD",
            **changes,
        }
    )


def policy() -> AllowancePolicy:
    return AllowancePolicy(
        monthly_minor_units=10_000,
        activation_at=date(2026, 3, 1),
        spending_account_ids={"card"},
        rules=[
            Rule(condition=NamePrefix(field="name", prefix="RENT"), kind=Kind.FIXED),
            Rule(condition=NamePrefix(field="name", prefix="SHOP"), kind=Kind.FLEXIBLE),
            Rule(condition=NamePrefix(field="name", prefix="TRANSFER"), kind=Kind.EXCLUDED),
            Rule(condition=NamePrefix(field="name", prefix="TAX"), kind=Kind.EXCLUDED, analysis_category="tax"),
        ],
        analysis_categories={
            "unclassified": AnalysisCategory(label="Unclassified", color="#777777"),
            "tax": AnalysisCategory(label="Tax", color="#777777"),
        },
    )


@pytest.mark.parametrize("mode", list(ConsumptionMode))
def test_scope_purchase_day_supersession_and_coverage(mode: ConsumptionMode) -> None:
    result = prepare_consumption(
        policy(),
        [
            transaction("RENT", authorized_datetime=datetime(2026, 3, 11, 2, tzinfo=UTC)),
            transaction("SHOP pending", pending=True),
            transaction("SHOP posted", pending_transaction_id="SHOP pending"),
            transaction("SHOP future", authorized_date=date(2026, 4, 2)),
            transaction("SHOP unrelated", account_id="other"),
            transaction("TRANSFER"),
            transaction("TAX"),
            transaction("Unknown"),
            transaction("Foreign", currency="EUR"),
        ],
        time_zone=_ZONE,
        today=_TODAY,
        currency="USD",
        include_excluded_categories={"tax"},
        confirmed_refund_rule_ids=set(),
        mode=mode,
    )
    entries = {entry.transaction.name: entry for entry in result.entries}
    assert set(entries) == {"RENT", "SHOP posted", "TRANSFER", "TAX", "Unknown", "Foreign"}
    assert entries["RENT"].report_day == date(2026, 3, 10)
    assert entries["RENT"].kind == Kind.FIXED
    assert entries["SHOP posted"].amount_minor_units == 1_000
    assert entries["TRANSFER"].disposition == ConsumptionDisposition.EXCLUDED
    assert entries["TAX"].amount_minor_units == 1_000
    assert entries["Unknown"].kind == Kind.REVIEW
    assert entries["Unknown"].amount_minor_units == 1_000
    assert entries["Foreign"].disposition == ConsumptionDisposition.OTHER_CURRENCY
    assert entries["Foreign"].amount_minor_units == 0
    assert not result.issues


@pytest.mark.parametrize("mode", list(ConsumptionMode))
def test_full_history_reversals_and_isolated_credits(mode: ConsumptionMode) -> None:
    allowance = policy().model_copy(
        update={
            "reversal_pairs": [
                ReversalPair(
                    id="synthetic-return",
                    description="Synthetic confirmed full reversal.",
                    original=NamePrefix(field="name", prefix="SHOP original"),
                    reversal=NamePrefix(field="name", prefix="SHOP return"),
                )
            ]
        }
    )
    result = prepare_consumption(
        allowance,
        [
            transaction("SHOP original", date=date(2026, 1, 1)),
            transaction("SHOP return", "-10.00"),
            transaction("SHOP credit", "-5.00"),
        ],
        time_zone=_ZONE,
        today=_TODAY,
        currency="USD",
        include_excluded_categories=set(),
        confirmed_refund_rule_ids=set(),
        mode=mode,
    )
    assert [entry.disposition for entry in result.entries[:2]] == [ConsumptionDisposition.REVERSAL] * 2
    assert result.entries[2].disposition == (
        ConsumptionDisposition.HELD_REFUND if mode == ConsumptionMode.NET else ConsumptionDisposition.GROSS_CREDIT
    )
    assert sum(entry.amount_minor_units for entry in result.entries) == 0
    assert not result.issues


def test_ambiguous_reversal_reports_issue_and_keeps_purchase() -> None:
    allowance = policy().model_copy(
        update={
            "reversal_pairs": [
                ReversalPair(
                    id="synthetic-return",
                    description="Synthetic incomplete full reversal.",
                    original=NamePrefix(field="name", prefix="SHOP original"),
                    reversal=NamePrefix(field="name", prefix="SHOP return"),
                )
            ]
        }
    )
    result = prepare_consumption(
        allowance,
        [transaction("SHOP original")],
        time_zone=_ZONE,
        today=_TODAY,
        currency="USD",
        include_excluded_categories=set(),
        confirmed_refund_rule_ids=set(),
        mode=ConsumptionMode.GROSS_PURCHASES,
    )
    assert result.entries[0].amount_minor_units == 1_000
    assert result.issues


if __name__ == "__main__":
    pytest_bazel.main()
