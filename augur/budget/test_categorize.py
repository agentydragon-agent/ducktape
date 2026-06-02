"""Categorization tests: transfer-direction split and the single-direction invariant."""

from __future__ import annotations

from datetime import date

import pytest
import pytest_bazel

from augur.budget.categorize import Classified, assert_transfer_directions, classify
from augur.budget.schema import BucketDef, BucketKind, BudgetConfig, BudgetSourceConfig
from plaid_utils.schema import TransactionRow

# Plaid signs outflows positive, inflows negative.
_TRANSFER_BUCKETS = (
    BucketDef(id="transfers_out", label="Transfers out", kind=BucketKind.TRANSFER),
    BucketDef(id="transfers_in", label="Transfers in", kind=BucketKind.TRANSFER),
)


def _tx(transaction_id: str, *, amount: float, pfc_primary: str | None = None) -> TransactionRow:
    return TransactionRow(
        transaction_id=transaction_id,
        account_id="acct",
        item_id="item",
        date=date(2026, 1, 15),
        amount=amount,
        name=transaction_id,
        merchant_name=None,
        pending=False,
        pfc_primary=pfc_primary,
        pfc_detailed=None,
        raw_json={},
    )


def _config(*buckets: BucketDef, include_default_rules: bool = False) -> BudgetConfig:
    return BudgetConfig(
        source=BudgetSourceConfig(),
        buckets=(*buckets, BucketDef(id="other", label="Other", kind=BucketKind.EXPENSE)),
        default_bucket_id="other",
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


def test_single_direction_transfer_buckets_pass() -> None:
    config = _config(*_TRANSFER_BUCKETS)
    classified = (
        Classified(transaction=_tx("a", amount=500.0), bucket_id="transfers_out"),
        Classified(transaction=_tx("b", amount=-700.0), bucket_id="transfers_in"),
    )
    assert_transfer_directions(classified, config=config)  # does not raise


def test_mixed_direction_transfer_bucket_raises() -> None:
    # A single transfer bucket holding both an outflow and an inflow nets opposing legs.
    config = _config(BucketDef(id="transfers", label="Transfers", kind=BucketKind.TRANSFER))
    classified = (
        Classified(transaction=_tx("out", amount=500.0), bucket_id="transfers"),
        Classified(transaction=_tx("in", amount=-500.0), bucket_id="transfers"),
    )
    with pytest.raises(ValueError, match="transfers"):
        assert_transfer_directions(classified, config=config)


def test_expense_bucket_may_mix_signs() -> None:
    # Refunds make an expense bucket legitimately two-signed; the invariant is transfer-only.
    config = _config(BucketDef(id="taxes", label="Taxes", kind=BucketKind.EXPENSE))
    classified = (
        Classified(transaction=_tx("pay", amount=4000.0), bucket_id="taxes"),
        Classified(transaction=_tx("refund", amount=-1500.0), bucket_id="taxes"),
    )
    assert_transfer_directions(classified, config=config)  # does not raise


if __name__ == "__main__":
    pytest_bazel.main()
