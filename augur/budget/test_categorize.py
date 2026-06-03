"""Categorization tests: per-bucket direction split, dual default fallback, single-direction invariant."""

from __future__ import annotations

from datetime import date

import pytest
import pytest_bazel
from pydantic import ValidationError

from augur.budget.categorize import Classified, assert_bucket_directions, classify
from augur.budget.schema import (
    BucketDef,
    BucketKind,
    BudgetConfig,
    BudgetSourceConfig,
    MerchantSubstringRule,
    NameSubstringRule,
    TransferDirection,
)
from plaid_utils.schema import TransactionRow

# Plaid signs outflows positive, inflows negative.
_OTHER_OUTFLOW = BucketDef(id="other", label="Other", kind=BucketKind.EXPENSE, direction=TransferDirection.OUTFLOW)
_OTHER_INFLOW = BucketDef(id="other_in", label="Other (in)", kind=BucketKind.INFLOW, direction=TransferDirection.INFLOW)
_TRANSFER_BUCKETS = (
    BucketDef(id="transfers_out", label="Transfers out", kind=BucketKind.TRANSFER, direction=TransferDirection.OUTFLOW),
    BucketDef(id="transfers_in", label="Transfers in", kind=BucketKind.TRANSFER, direction=TransferDirection.INFLOW),
)


def _tx(
    transaction_id: str,
    *,
    amount: float,
    name: str | None = None,
    merchant_name: str | None = None,
    pfc_primary: str | None = None,
    pfc_detailed: str | None = None,
) -> TransactionRow:
    return TransactionRow(
        transaction_id=transaction_id,
        account_id="acct",
        item_id="item",
        date=date(2026, 1, 15),
        amount=amount,
        name=name or transaction_id,
        merchant_name=merchant_name,
        pending=False,
        pfc_primary=pfc_primary,
        pfc_detailed=pfc_detailed,
        raw_json={},
    )


def _config(*buckets: BucketDef, rules: tuple = (), include_default_rules: bool = False) -> BudgetConfig:
    return BudgetConfig(
        source=BudgetSourceConfig(),
        buckets=(*buckets, _OTHER_OUTFLOW, _OTHER_INFLOW),
        default_outflow_bucket_id="other",
        default_inflow_bucket_id="other_in",
        rules=rules,
        include_default_rules=include_default_rules,
    )


def test_default_rules_split_transfers_by_direction() -> None:
    config = _config(*_TRANSFER_BUCKETS, include_default_rules=True)
    txns = (
        _tx("out", amount=500.0, pfc_primary="TRANSFER_OUT"),
        _tx("loan_pay", amount=300.0, pfc_primary="LOAN_PAYMENTS"),
        _tx("in", amount=-700.0, pfc_primary="TRANSFER_IN"),
        _tx("loan_disb", amount=-900.0, pfc_primary="LOAN_DISBURSEMENTS"),
    )
    routed = {entry.transaction.transaction_id: entry.bucket_id for entry in classify(txns, config=config)}
    assert routed == {
        "out": "transfers_out",
        "loan_pay": "transfers_out",
        "in": "transfers_in",
        "loan_disb": "transfers_in",
    }


def test_bucket_direction_gates_pattern_rule() -> None:
    # A single descriptor that appears on both legs (e.g. brokerage ACH showing up as both a
    # TRANSFER_OUT deposit AND a Plaid-mistagged INCOME_CONTRACTOR withdrawal) is routed by
    # *bucket* direction: the inflow-side rule fires only on the negative-amount leg.
    config = _config(
        *_TRANSFER_BUCKETS,
        rules=(NameSubstringRule(pattern="Wealthfront", bucket_id="transfers_in"),),
        include_default_rules=True,
    )
    txns = (
        _tx("deposit", amount=30000.0, name="Wealthfront", pfc_primary="TRANSFER_OUT"),
        _tx("withdraw", amount=-12000.0, name="Wealthfront", pfc_primary="INCOME", pfc_detailed="INCOME_OTHER_INCOME"),
    )
    routed = {entry.transaction.transaction_id: entry.bucket_id for entry in classify(txns, config=config)}
    assert routed == {"deposit": "transfers_out", "withdraw": "transfers_in"}


def test_unmatched_transactions_split_by_sign_to_per_direction_defaults() -> None:
    config = _config()  # only the two defaults; no rules
    txns = (_tx("spent", amount=120.0), _tx("refunded", amount=-40.0))
    routed = {entry.transaction.transaction_id: entry.bucket_id for entry in classify(txns, config=config)}
    assert routed == {"spent": "other", "refunded": "other_in"}


def test_zero_amount_transaction_lands_in_outflow_default_without_tripping_guard() -> None:
    # Waived fees and voided lines arrive as `amount == 0` -- the convention is to route them to
    # the outflow default bucket. `_direction_matches` treats $0 as outflow-compatible so that
    # `assert_bucket_directions` doesn't reject the result; the guard would previously raise on
    # any zero-amount line.
    config = _config()
    classified = classify((_tx("waiver", amount=0.0),), config=config)
    assert {entry.transaction.transaction_id: entry.bucket_id for entry in classified} == {"waiver": "other"}
    # The defense-in-depth guard accepts $0 against an outflow bucket.
    assert_bucket_directions(classified, config=config)  # does not raise


def test_transfer_bucket_without_direction_rejected() -> None:
    # Direction is a required field on every BucketDef; pydantic surfaces the missing-field error.
    with pytest.raises(ValidationError):
        BucketDef(id="transfers", label="Transfers", kind=BucketKind.TRANSFER)  # type: ignore[call-arg]


def test_expense_bucket_with_inflow_direction_rejected() -> None:
    with pytest.raises(ValidationError, match="requires direction=outflow"):
        BucketDef(id="rent", label="Rent", kind=BucketKind.EXPENSE, direction=TransferDirection.INFLOW)


def test_income_bucket_with_outflow_direction_rejected() -> None:
    with pytest.raises(ValidationError, match="requires direction=inflow"):
        BucketDef(id="paycheck", label="Paycheck", kind=BucketKind.INCOME, direction=TransferDirection.OUTFLOW)


def test_default_bucket_direction_mismatch_rejected() -> None:
    with pytest.raises(ValidationError, match="default_outflow_bucket_id"):
        BudgetConfig(
            source=BudgetSourceConfig(),
            buckets=(_OTHER_OUTFLOW, _OTHER_INFLOW),
            default_outflow_bucket_id="other_in",  # wrong direction
            default_inflow_bucket_id="other_in",
            include_default_rules=False,
        )


def test_assert_bucket_directions_passes_when_signs_match() -> None:
    config = _config(*_TRANSFER_BUCKETS)
    classified = (
        Classified(transaction=_tx("a", amount=500.0), bucket_id="transfers_out"),
        Classified(transaction=_tx("b", amount=-700.0), bucket_id="transfers_in"),
    )
    assert_bucket_directions(classified, config=config)  # does not raise


def test_assert_bucket_directions_raises_on_hand_built_misroute() -> None:
    # Guard catches hand-built Classified tuples (tests, fixture loaders) that misroute a leg.
    config = _config(*_TRANSFER_BUCKETS)
    classified = (Classified(transaction=_tx("inflow", amount=-500.0), bucket_id="transfers_out"),)
    with pytest.raises(ValueError, match="transfers_out"):
        assert_bucket_directions(classified, config=config)


def test_income_tax_refund_routes_to_tax_refunds_bucket() -> None:
    # Tax refunds are an inflow leg and can't share the outflow-only `taxes` transfer bucket.
    # The default rule routes INCOME_TAX_REFUND to `tax_refunds` when the deployment declares it.
    config = _config(
        BucketDef(id="taxes", label="Taxes", kind=BucketKind.TRANSFER, direction=TransferDirection.OUTFLOW),
        BucketDef(id="tax_refunds", label="Tax refunds", kind=BucketKind.TRANSFER, direction=TransferDirection.INFLOW),
        rules=(MerchantSubstringRule(pattern="Internal Revenue Service", bucket_id="taxes"),),
        include_default_rules=True,
    )
    txns = (
        _tx(
            "payment",
            amount=165000.0,
            merchant_name="Internal Revenue Service",
            pfc_primary="GOVERNMENT_AND_NON_PROFIT",
        ),
        _tx(
            "refund",
            amount=-1246.0,
            name="FRANCHISE TAX BD DES:CASTTAXRFD",
            pfc_primary="INCOME",
            pfc_detailed="INCOME_TAX_REFUND",
        ),
    )
    routed = {entry.transaction.transaction_id: entry.bucket_id for entry in classify(txns, config=config)}
    assert routed == {"payment": "taxes", "refund": "tax_refunds"}


if __name__ == "__main__":
    pytest_bazel.main()
