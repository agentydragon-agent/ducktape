"""Synthetic allowance contract tests; no real account or transaction data."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from finance.plaid.spend.allowance import (
    AllowancePolicy,
    CategoryRule,
    Kind,
    MerchantRule,
    PaceAlert,
    Status,
    Transaction,
    calculate,
    month_anniversary,
)

START = datetime(2026, 1, 31, tzinfo=UTC)


def policy(*, activation_at=START, rules=None):
    return AllowancePolicy(
        monthly_minor_units=10_000,
        spending_account_ids=["card-1"],
        activation_at=activation_at,
        rules=rules if rules is not None else [CategoryRule(field="pfc_primary", value="SHOPPING", kind=Kind.FLEXIBLE)],
    )


def row(
    day: str,
    amount: int,
    *,
    pending: bool = False,
    transaction_id: str | None = None,
    pending_transaction_id: str | None = None,
    pfc_primary: str | None = "SHOPPING",
    pfc_detailed: str | None = "SHOPPING_GENERAL_MERCHANDISE",
) -> Transaction:
    return Transaction(
        account_id="card-1",
        transaction_id=transaction_id or f"tx-{day}-{amount}",
        date=date.fromisoformat(day),
        amount=Decimal(amount),
        pending=pending,
        pending_transaction_id=pending_transaction_id,
        currency="USD",
        name="EXAMPLE SHOP",
        merchant_name=None,
        pfc_primary=pfc_primary,
        pfc_detailed=pfc_detailed,
    )


def view(rows=(), when=START):
    return calculate(policy(), list(rows), now=when, last_synced_at=when)


def test_activation_preview_and_no_double_credit():
    assert calculate(policy(activation_at=None), [], now=START, last_synced_at=START).status == Status.PREVIEW
    assert view([row("2026-01-30", 90)]).available_minor_units == 10_000
    assert view(when=datetime(2026, 2, 1, tzinfo=UTC)).available_minor_units == 10_000
    assert view(when=datetime(2026, 2, 28, tzinfo=UTC)).available_minor_units == 20_000
    assert month_anniversary(START, 2) == datetime(2026, 3, 31, tzinfo=UTC)
    with pytest.raises(ValidationError):
        policy(activation_at=datetime(2026, 1, 31, 12, tzinfo=UTC))


def test_carry_windows_and_early_pace():
    now = datetime(2026, 2, 28, tzinfo=UTC)
    result = view([row("2026-01-31", 20), row("2026-02-28", 30)], when=now)
    assert result.available_minor_units == 15_000
    assert result.prior_carry_minor_units == 8_000
    assert result.windows_minor_units is not None
    assert result.windows_minor_units.current_credit_cycle == 3_000
    assert result.windows_minor_units.calendar_month == 3_000
    assert result.next_credit_at == datetime(2026, 3, 31, tzinfo=UTC)
    fast = view([row("2026-01-31", 70)], when=START)
    assert fast.alert_state == PaceAlert.WARNING
    assert fast.estimated_exhaustion_at == START + (datetime(2026, 2, 1, tzinfo=UTC) - START) * (3 / 7)


def test_pending_posted_transfer_and_unmatched_refund():
    rows = [
        row("2026-01-31", 20, pending=True, transaction_id="pending"),
        row("2026-01-31", 20, transaction_id="posted", pending_transaction_id="pending"),
        row("2026-01-31", 45, transaction_id="payment", pfc_primary="TRANSFER_OUT", pfc_detailed="LOAN_PAYMENTS_CREDIT_CARD_PAYMENT"),
        row("2026-01-31", -8, transaction_id="mystery-refund", pfc_primary=None, pfc_detailed=None),
    ]
    result = calculate(
        policy(rules=[CategoryRule(field="pfc_detailed", value="LOAN_PAYMENTS_CREDIT_CARD_PAYMENT", kind=Kind.EXCLUDED),
                      CategoryRule(field="pfc_primary", value="SHOPPING", kind=Kind.FLEXIBLE)]),
        rows, now=START, last_synced_at=START,
    )
    assert result.posted_minor_units == 2_000
    assert result.pending_minor_units == 0
    assert result.unmatched_refunds_minor_units == 800
    assert result.available_minor_units == 8_000
    inferred_refund = view([row("2026-01-31", -8)])
    assert inferred_refund.unmatched_refunds_minor_units == 800
    assert inferred_refund.available_minor_units == 10_000


def test_private_rule_and_uncertain_purchases():
    result = calculate(
        policy(rules=[MerchantRule(field="name", prefix="EXAMPLE", kind=Kind.FIXED)]),
        [row("2026-01-31", 42)], now=START, last_synced_at=START,
    )
    assert result.available_minor_units == 10_000
    uncertain = view([row("2026-01-31", 12, pfc_primary=None, pfc_detailed=None)])
    assert uncertain.available_minor_units == 8_800
    assert uncertain.review_minor_units == 1_200
    with pytest.raises(ValidationError):
        MerchantRule(field="pfc_primary", prefix="SHOPPING", kind=Kind.EXCLUDED)


if __name__ == "__main__":
    import pytest_bazel

    pytest_bazel.main()
