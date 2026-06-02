"""Budget planner configuration: bucket taxonomy and merchant-classification rules.

The augur framework knows nothing about specific user merchants. Generic rules
(major chains: DoorDash, Anthropic, Lyft, ...) ship in `default_rules.py`;
user-specific rules (medical providers, therapist, landlord, account IDs) live
in the deployment's augur `Config` YAML, which augur loads at startup. This
file just defines the schemas both layers populate.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from augur.api.schemas import ApiModel

_ID_PATTERN = r"^[a-z0-9][a-z0-9_]*$"


class BucketKind(StrEnum):
    EXPENSE = "expense"
    REIMBURSABLE = "reimbursable"
    REIMBURSEMENT = "reimbursement"
    TRANSFER = "transfer"
    INCOME = "income"


class BucketDef(ApiModel):
    """One named spending bucket. Rules route transactions to a `bucket_id`."""

    id: str = Field(pattern=_ID_PATTERN)
    label: str
    kind: BucketKind
    # For REIMBURSABLE buckets, the paired REIMBURSEMENT bucket whose inflows offset
    # this bucket's outflows on a rolling-window basis (e.g. Numa charges paired with
    # Anthem HCCLAIMPMT deposits). Other kinds must leave this null.
    reimbursed_by: str | None = Field(default=None, pattern=_ID_PATTERN)

    @model_validator(mode="after")
    def _validate_reimbursed_by(self) -> BucketDef:
        if self.kind == BucketKind.REIMBURSABLE and self.reimbursed_by is None:
            raise ValueError(f"bucket {self.id!r}: kind=reimbursable requires reimbursed_by")
        if self.kind != BucketKind.REIMBURSABLE and self.reimbursed_by is not None:
            raise ValueError(f"bucket {self.id!r}: reimbursed_by only valid on kind=reimbursable")
        return self


class _RuleBase(ApiModel):
    bucket_id: str = Field(pattern=_ID_PATTERN)


class MerchantSubstringRule(_RuleBase):
    """Case-insensitive substring match against `transactions.merchant_name`."""

    kind: Literal["merchant_substring"] = "merchant_substring"
    pattern: str = Field(min_length=1)


class NameSubstringRule(_RuleBase):
    """Case-insensitive substring match against `transactions.name` (the raw descriptor).

    Use this for ACH descriptors where Plaid hasn't promoted a clean merchant name
    (e.g. "ANTHEM BLUE CA5C DES:HCCLAIMPMT" reimbursements, "DD *DOORDASH ..." pass-through)."""

    kind: Literal["name_substring"] = "name_substring"
    pattern: str = Field(min_length=1)


class PfcRule(_RuleBase):
    """Plaid `personal_finance_category` match. `detailed` is optional; if omitted, primary suffices."""

    kind: Literal["pfc"] = "pfc"
    primary: str
    detailed: str | None = None


Rule = MerchantSubstringRule | NameSubstringRule | PfcRule


class BudgetSourceConfig(ApiModel):
    """Where to pull transactions from, scoped to a user's accounts."""

    database_url_env: str = "AUGUR_PLAID_DATABASE_URL"
    # Account IDs from `plaid_utils.schema.accounts.account_id`. Empty = all accounts the
    # connection can see (fine for single-user deployments; explicit for shared ones).
    plaid_account_ids: tuple[str, ...] = ()
    iso_currency_code: str = "USD"
    # Earliest date for which the linked accounts provide complete coverage. When set, the
    # snapshot's window start is clamped to this date so historical comparisons aren't
    # skewed by accounts that joined the dataset later (e.g. a Plaid item with a tighter
    # institution-side transaction-history limit than its peers). The wire response carries
    # this date through so the UI can label early months as partial.
    coverage_starts: date | None = None


class BudgetConfig(ApiModel):
    """Top-level budget planner config (optional; absent = budget endpoints return 400)."""

    source: BudgetSourceConfig
    buckets: tuple[BucketDef, ...] = Field(min_length=1)
    # Default bucket id for transactions no rule matched. Must reference a bucket in `buckets`.
    default_bucket_id: str = Field(pattern=_ID_PATTERN)
    # User-specific overrides applied BEFORE the generic defaults. First match wins, so listing
    # a private merchant rule here pre-empts the public defaults.
    rules: tuple[Rule, ...] = ()
    # When True, ship `default_rules.DEFAULT_RULES` after the user's rules. Set False to
    # opt out of the public rule library entirely (rare; useful for testing).
    include_default_rules: bool = True
    # Rolling window (months) used to net REIMBURSABLE expenses against their paired
    # REIMBURSEMENT inflows. Insurance reimbursements arrive 1-4 weeks after the charge,
    # sometimes batched -- a 3-month window smooths the lumpiness without burying it.
    reimbursement_window_months: int = Field(default=3, ge=1, le=24)
    # Transactions with abs(amount) >= this threshold are flagged as "lumpy" (in addition to
    # appearing in their natural bucket). User can re-classify them as one-off vs recurring.
    lumpy_threshold_usd: float = Field(default=500.0, gt=0.0)

    @model_validator(mode="after")
    def _validate_references(self) -> BudgetConfig:
        bucket_ids = {bucket.id for bucket in self.buckets}
        if self.default_bucket_id not in bucket_ids:
            raise ValueError(f"default_bucket_id {self.default_bucket_id!r} not in buckets ({sorted(bucket_ids)})")
        for bucket in self.buckets:
            if bucket.reimbursed_by is not None and bucket.reimbursed_by not in bucket_ids:
                raise ValueError(f"bucket {bucket.id!r} reimbursed_by {bucket.reimbursed_by!r} not in buckets")
        for rule in self.rules:
            if rule.bucket_id not in bucket_ids:
                raise ValueError(f"rule references unknown bucket_id {rule.bucket_id!r}")
        return self
