"""Declarative posting schemas for the augur accounting trace.

The shape of a journal entry — the sequence of postings it produces, their
roles, sides, and where each leg's `amount_usd` comes from — is static per
kind. Today this shape is rebuilt inline at every engine call site as a
`JournalEntryBatch(postings=(PostingBatch(...), PostingBatch(...), ...))`,
which is verbose and hides the structural commonalities between kinds.

This module declares each kind's shape as a `JournalEntrySchema` constant.
Engine code calls `accounting.record_entry_firings(schema=..., ...)` and
supplies only the *varying* parts (per-call cause_id_prefix / actor_id /
amount arrays / chart-account key bindings). The schema fixes the legs.

The schemas are also the natural authoring surface for the future
amount-derivation work: once each leg's amount is expressed as a named
binding, replacing the binding with a reference to a `ScenarioRunArrays`
column is a one-line schema edit.
"""

from __future__ import annotations

from dataclasses import dataclass

from augur.core.accounting import AccountingCauseType, ChartAccountRole, JournalEntryType, PostingSide


@dataclass(frozen=True)
class PostingLegSchema:
    """One leg of a journal entry. Role and side are constants per leg;
    `amount_binding` names the `(rollouts, months)` numpy array the engine
    will pass in `amount_bindings` at record time."""

    role: ChartAccountRole
    side: PostingSide
    amount_binding: str


@dataclass(frozen=True)
class JournalEntrySchema:
    """Static shape of a journal entry kind.

    `journal_entry_type` / `cause_type` match the fields on
    `JournalEntryBatch`. `legs` is the fixed posting sequence. Per-call
    metadata (`cause_id_prefix`, `actor_id`, `policy_id`, `event_id`,
    `obligation_id_prefix`, `description`), amount values, and chart-account
    key bindings are passed at record time alongside the schema.
    """

    journal_entry_type: JournalEntryType
    cause_type: AccountingCauseType
    legs: tuple[PostingLegSchema, ...]


# Opening balances ------------------------------------------------------------
#
# Each opening kind is a 2-leg `OPENING_BALANCE` journal entry: a debit on
# the asset account being opened and a credit on `OPENING_EQUITY`, with the
# same `amount` array on both legs. The property-opening shape is the
# exception (4 legs) because it splits the cash outlay across purchase price,
# closing costs, and the mortgage balance.

OPENING_CHECKING_CASH = JournalEntrySchema(
    journal_entry_type=JournalEntryType.OPENING_BALANCE,
    cause_type=AccountingCauseType.OPENING_BALANCE,
    legs=(
        PostingLegSchema(role=ChartAccountRole.CHECKING_CASH, side=PostingSide.DEBIT, amount_binding="amount"),
        PostingLegSchema(role=ChartAccountRole.OPENING_EQUITY, side=PostingSide.CREDIT, amount_binding="amount"),
    ),
)

OPENING_PUBLIC_SECURITY = JournalEntrySchema(
    journal_entry_type=JournalEntryType.OPENING_BALANCE,
    cause_type=AccountingCauseType.OPENING_BALANCE,
    legs=(
        PostingLegSchema(role=ChartAccountRole.PUBLIC_SECURITY, side=PostingSide.DEBIT, amount_binding="amount"),
        PostingLegSchema(role=ChartAccountRole.OPENING_EQUITY, side=PostingSide.CREDIT, amount_binding="amount"),
    ),
)

OPENING_CRYPTO_ASSET = JournalEntrySchema(
    journal_entry_type=JournalEntryType.OPENING_BALANCE,
    cause_type=AccountingCauseType.OPENING_BALANCE,
    legs=(
        PostingLegSchema(role=ChartAccountRole.CRYPTO_ASSET, side=PostingSide.DEBIT, amount_binding="amount"),
        PostingLegSchema(role=ChartAccountRole.OPENING_EQUITY, side=PostingSide.CREDIT, amount_binding="amount"),
    ),
)

OPENING_PRIVATE_EQUITY = JournalEntrySchema(
    journal_entry_type=JournalEntryType.OPENING_BALANCE,
    cause_type=AccountingCauseType.OPENING_BALANCE,
    legs=(
        PostingLegSchema(role=ChartAccountRole.PRIVATE_EQUITY, side=PostingSide.DEBIT, amount_binding="amount"),
        PostingLegSchema(role=ChartAccountRole.OPENING_EQUITY, side=PostingSide.CREDIT, amount_binding="amount"),
    ),
)

OPENING_PROPERTY = JournalEntrySchema(
    journal_entry_type=JournalEntryType.OPENING_BALANCE,
    cause_type=AccountingCauseType.OPENING_BALANCE,
    legs=(
        PostingLegSchema(role=ChartAccountRole.PROPERTY, side=PostingSide.DEBIT, amount_binding="purchase"),
        PostingLegSchema(
            role=ChartAccountRole.PROPERTY_PURCHASE_CLOSING_EXPENSE, side=PostingSide.DEBIT, amount_binding="closing"
        ),
        PostingLegSchema(role=ChartAccountRole.CHECKING_CASH, side=PostingSide.CREDIT, amount_binding="cash_outlay"),
        PostingLegSchema(role=ChartAccountRole.MORTGAGE_PAYABLE, side=PostingSide.CREDIT, amount_binding="mortgage"),
    ),
)


__all__ = [
    "OPENING_CHECKING_CASH",
    "OPENING_CRYPTO_ASSET",
    "OPENING_PRIVATE_EQUITY",
    "OPENING_PROPERTY",
    "OPENING_PUBLIC_SECURITY",
    "JournalEntrySchema",
    "PostingLegSchema",
]
