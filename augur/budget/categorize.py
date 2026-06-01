"""Transaction -> bucket categorization driven by `BudgetConfig.rules` + defaults."""

from __future__ import annotations

from dataclasses import dataclass

from augur.budget.default_rules import DEFAULT_RULES
from augur.budget.schema import BudgetConfig, MerchantSubstringRule, NameSubstringRule, PfcRule, Rule
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
    return tuple(classified)
