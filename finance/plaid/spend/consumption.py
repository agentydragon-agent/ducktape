"""Pure, policy-driven consumption decisions shared by reports and funding estimates."""

from collections.abc import Collection
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from zoneinfo import ZoneInfo

from finance.plaid.spend.allowance import (
    AllowancePolicy,
    Kind,
    Rule,
    Transaction,
    matching_rule,
    resolve_reversal_pairs,
    superseded_pending_keys,
)


class ConsumptionMode(StrEnum):
    NET = "net"
    GROSS_PURCHASES = "gross_purchases"


class ConsumptionDisposition(StrEnum):
    COUNTED = "counted"
    EXCLUDED = "excluded"
    REVERSAL = "reversal"
    HELD_REFUND = "held_refund"
    GROSS_CREDIT = "gross_credit"
    OTHER_CURRENCY = "other_currency"


@dataclass(frozen=True)
class ConsumptionEntry:
    transaction: Transaction
    report_day: date
    rule: Rule | None
    disposition: ConsumptionDisposition
    amount_minor_units: int

    @property
    def kind(self) -> Kind:
        return self.rule.kind if self.rule is not None else Kind.REVIEW


@dataclass(frozen=True)
class PreparedConsumption:
    entries: list[ConsumptionEntry]
    issues: list[str]


def _consumption_disposition(
    transaction: Transaction,
    *,
    rule: Rule | None,
    amount_minor_units: int,
    currency: str,
    is_reversal: bool,
    include_excluded_categories: Collection[str],
    confirmed_refund_rule_ids: Collection[str],
    mode: ConsumptionMode,
) -> ConsumptionDisposition:
    """Decide whether a prepared transaction contributes to consumption."""
    if transaction.currency not in (None, currency):
        return ConsumptionDisposition.OTHER_CURRENCY
    if is_reversal:
        return ConsumptionDisposition.REVERSAL
    if rule is not None and rule.kind == Kind.EXCLUDED and rule.analysis_category not in include_excluded_categories:
        return ConsumptionDisposition.EXCLUDED
    if amount_minor_units < 0 and mode == ConsumptionMode.GROSS_PURCHASES:
        return ConsumptionDisposition.GROSS_CREDIT
    if amount_minor_units < 0 and (rule is None or rule.id not in confirmed_refund_rule_ids):
        return ConsumptionDisposition.HELD_REFUND
    return ConsumptionDisposition.COUNTED


def prepare_consumption(
    allowance: AllowancePolicy,
    transactions: list[Transaction],
    *,
    time_zone: ZoneInfo,
    today: date,
    currency: str,
    include_excluded_categories: Collection[str],
    confirmed_refund_rule_ids: Collection[str],
    mode: ConsumptionMode,
) -> PreparedConsumption:
    """Resolve full-history reversals before callers select their reporting window.

    Retain excluded, foreign-currency and held-credit entries for coverage and audit
    reporting. Out-of-scope accounts, future purchase days and superseded pending
    rows are omitted entirely. Today and pending purchases remain eligible; callers
    choose whether their report needs only completed days or posted transactions.
    Unclassified/review purchases count conservatively. Negative amounts only net
    against spending with an explicitly confirmed refund rule; gross mode counts
    no credits. A validated reversal removes both legs in either mode.
    """
    reversals = resolve_reversal_pairs(allowance, transactions, time_zone=time_zone, today=today)
    superseded = superseded_pending_keys(transactions)
    entries = []
    for transaction in transactions:
        if transaction.account_id not in allowance.spending_account_ids:
            continue
        day = transaction.report_day(time_zone)
        key = (transaction.account_id, transaction.transaction_id)
        if day > today or (transaction.pending and key in superseded):
            continue
        rule = matching_rule(transaction, allowance.rules)
        amount = int((transaction.amount * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))
        disposition = _consumption_disposition(
            transaction,
            rule=rule,
            amount_minor_units=amount,
            currency=currency,
            is_reversal=key in reversals.pairs_by_transaction,
            include_excluded_categories=include_excluded_categories,
            confirmed_refund_rule_ids=confirmed_refund_rule_ids,
            mode=mode,
        )
        entries.append(
            ConsumptionEntry(
                transaction=transaction,
                report_day=day,
                rule=rule,
                disposition=disposition,
                amount_minor_units=amount if disposition == ConsumptionDisposition.COUNTED else 0,
            )
        )
    return PreparedConsumption(entries=entries, issues=reversals.issues)
