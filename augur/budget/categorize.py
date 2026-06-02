"""Transaction -> bucket categorization driven by `BudgetConfig.rules` + defaults."""

from __future__ import annotations

from dataclasses import dataclass

from augur.budget.default_rules import DEFAULT_RULES
from augur.budget.schema import BucketKind, BudgetConfig, MerchantSubstringRule, NameSubstringRule, PfcRule, Rule
from plaid_utils.schema import TransactionRow


@dataclass(frozen=True)
class Classified:
    transaction: TransactionRow
    bucket_id: str


def _rule_matches(rule: Rule, tx: TransactionRow) -> bool:
    if isinstance(rule, MerchantSubstringRule):
        merchant = (tx.merchant_name or "").lower()
        return rule.pattern.lower() in merchant
    if isinstance(rule, NameSubstringRule):
        return rule.pattern.lower() in tx.name.lower()
    if isinstance(rule, PfcRule):
        if tx.pfc_primary != rule.primary:
            return False
        return rule.detailed is None or tx.pfc_detailed == rule.detailed
    raise TypeError(f"unknown rule type: {type(rule).__name__}")


def effective_rules(config: BudgetConfig) -> tuple[Rule, ...]:
    """User rules first (so they pre-empt defaults), then the public library if enabled."""
    if config.include_default_rules:
        return (*config.rules, *DEFAULT_RULES)
    return config.rules


def classify(transactions: tuple[TransactionRow, ...], *, config: BudgetConfig) -> tuple[Classified, ...]:
    """Assign each transaction to a bucket; unmatched fall to `config.default_bucket_id`."""
    rules = effective_rules(config)
    bucket_ids = {bucket.id for bucket in config.buckets}
    classified: list[Classified] = []
    for tx in transactions:
        matched_bucket: str | None = None
        for rule in rules:
            # A rule whose `bucket_id` isn't declared in this config is silently skipped,
            # so a deployment can opt out of a default rule by simply not declaring its
            # bucket (rather than rewriting the whole rule list).
            if _rule_matches(rule, tx) and rule.bucket_id in bucket_ids:
                matched_bucket = rule.bucket_id
                break
        classified.append(Classified(transaction=tx, bucket_id=matched_bucket or config.default_bucket_id))
    result = tuple(classified)
    assert_transfer_directions(result, config=config)
    return result


def _describe(tx: TransactionRow) -> str:
    return f"{tx.date} {tx.merchant_name or tx.name} {tx.amount:+.2f}"


def assert_transfer_directions(classified: tuple[Classified, ...], *, config: BudgetConfig) -> None:
    """A `kind=transfer` bucket must stay single-direction (all outflow or all inflow).

    Transfers are internal account movements; the snapshot splits them into an outflow-side and an
    inflow-side bucket (transfers_out / transfers_in) so each reads as a clean expense-like or
    income-like figure instead of a net that hides the gross legs. A transfer bucket carrying both
    signs means a rule routed opposing flows into one bucket -- raise so the miscategorization
    surfaces instead of silently netting to a meaningless number. (Plaid signs outflows positive,
    inflows negative.)
    """
    kind_by_bucket = {bucket.id: bucket.kind for bucket in config.buckets}
    outflow: dict[str, TransactionRow] = {}
    inflow: dict[str, TransactionRow] = {}
    for entry in classified:
        if kind_by_bucket[entry.bucket_id] != BucketKind.TRANSFER:
            continue
        if entry.transaction.amount > 0:
            outflow.setdefault(entry.bucket_id, entry.transaction)
        elif entry.transaction.amount < 0:
            inflow.setdefault(entry.bucket_id, entry.transaction)
    if mixed := sorted(outflow.keys() & inflow.keys()):
        detail = "; ".join(
            f"{bucket_id} (out e.g. {_describe(outflow[bucket_id])}, in e.g. {_describe(inflow[bucket_id])})"
            for bucket_id in mixed
        )
        raise ValueError(
            "transfer bucket(s) mix outflow and inflow, netting opposing legs into a misleading "
            f"figure: {detail}. Route each direction to its own bucket (e.g. transfers_out / "
            "transfers_in) or add a rule."
        )
