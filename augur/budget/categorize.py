"""Transaction -> bucket categorization driven by `BudgetConfig.rules` + defaults."""

from __future__ import annotations

from dataclasses import dataclass

from augur.budget.default_rules import DEFAULT_RULES
from augur.budget.schema import (
    BucketDef,
    BudgetConfig,
    MerchantSubstringRule,
    NameSubstringRule,
    PfcRule,
    Rule,
    TransferDirection,
)
from plaid_utils.schema import TransactionRow


@dataclass(frozen=True)
class Classified:
    transaction: TransactionRow
    bucket_id: str


def _pattern_matches(rule: Rule, tx: TransactionRow) -> bool:
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


def _direction_matches(direction: TransferDirection, amount: float) -> bool:
    # Plaid signs outflows positive, inflows negative. Zero-amount transactions
    # (waived fees, voided lines) are sign-ambiguous; route them with outflow so they
    # land in the same `default_outflow_bucket_id` that `classify` already picks for
    # them, instead of tripping `assert_bucket_directions`.
    if direction is TransferDirection.OUTFLOW:
        return amount >= 0
    return amount < 0


def effective_rules(config: BudgetConfig) -> tuple[Rule, ...]:
    """User rules first (so they pre-empt defaults), then the public library if enabled."""
    if config.include_default_rules:
        return (*config.rules, *DEFAULT_RULES)
    return config.rules


def classify(transactions: tuple[TransactionRow, ...], *, config: BudgetConfig) -> tuple[Classified, ...]:
    """Assign each transaction to a bucket; unmatched fall to the per-direction default."""
    rules = effective_rules(config)
    bucket_by_id: dict[str, BucketDef] = {bucket.id: bucket for bucket in config.buckets}
    classified: list[Classified] = []
    for tx in transactions:
        # Plaid signs outflows positive, inflows negative. Zero-amount transactions
        # (rare; pending placeholders, voided lines) go to the outflow default by
        # convention so they don't disappear into an inflow refund bucket.
        bucket_id: str = config.default_inflow_bucket_id if tx.amount < 0 else config.default_outflow_bucket_id
        for rule in rules:
            # A rule whose `bucket_id` isn't declared in this config is silently skipped,
            # so a deployment can opt out of a default rule by simply not declaring its
            # bucket (rather than rewriting the whole rule list).
            target = bucket_by_id.get(rule.bucket_id)
            if target is None:
                continue
            # Pattern AND target-bucket direction must both match. The direction filter
            # lives on the bucket so a single-pattern rule routing to transfers_in only
            # fires on inflow legs, even when the same descriptor reappears as an outflow
            # (resolved by the next matching rule).
            if not _pattern_matches(rule, tx):
                continue
            if not _direction_matches(target.direction, tx.amount):
                continue
            bucket_id = rule.bucket_id
            break
        classified.append(Classified(transaction=tx, bucket_id=bucket_id))
    result = tuple(classified)
    assert_bucket_directions(result, config=config)
    return result


def _describe(tx: TransactionRow) -> str:
    return f"{tx.date} {tx.merchant_name or tx.name} {tx.amount:+.2f}"


def assert_bucket_directions(classified: tuple[Classified, ...], *, config: BudgetConfig) -> None:
    """Defense in depth: confirm every classified transaction respects its bucket's `direction`.

    `classify` already routes rule matches by direction and picks the per-direction default for
    unmatched transactions, so violations are unreachable through that path. This guard catches
    callers that hand-build `Classified` tuples (tests, fixture loaders, future code paths) and
    misroute a leg. (Plaid signs outflows positive, inflows negative.)
    """
    bucket_by_id = {bucket.id: bucket for bucket in config.buckets}
    violations: list[tuple[BucketDef, TransactionRow]] = []
    seen: set[str] = set()
    for entry in classified:
        bucket = bucket_by_id[entry.bucket_id]
        if _direction_matches(bucket.direction, entry.transaction.amount):
            continue
        if bucket.id in seen:
            continue
        seen.add(bucket.id)
        violations.append((bucket, entry.transaction))
    if violations:
        detail = "; ".join(
            f"{bucket.id} (direction={bucket.direction.value}, wrong-sign e.g. {_describe(tx)})"
            for bucket, tx in violations
        )
        raise ValueError(
            f"transactions classified into a direction-gated bucket with the wrong sign: {detail}. "
            "Add a rule routing the opposing leg to its own bucket (e.g. transfers_out / transfers_in)."
        )
