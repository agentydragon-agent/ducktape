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

# Asset sales -----------------------------------------------------------------
#
# Each `ASSET_SALE` kind is a 2-leg journal entry: cash (or replacement asset)
# on the debit side, the sold asset on the credit side, with the same sale
# amount on both legs. The private-equity path has two variants because the
# sale proceeds can flow to either CHECKING_CASH or PUBLIC_SECURITY depending
# on the policy's `proceeds_destination`.

ASSET_SALE_PUBLIC_SECURITY = JournalEntrySchema(
    journal_entry_type=JournalEntryType.ASSET_SALE,
    cause_type=AccountingCauseType.POLICY_DECISION,
    legs=(
        PostingLegSchema(role=ChartAccountRole.CHECKING_CASH, side=PostingSide.DEBIT, amount_binding="amount"),
        PostingLegSchema(role=ChartAccountRole.PUBLIC_SECURITY, side=PostingSide.CREDIT, amount_binding="amount"),
    ),
)

ASSET_SALE_CRYPTO = JournalEntrySchema(
    journal_entry_type=JournalEntryType.ASSET_SALE,
    cause_type=AccountingCauseType.POLICY_DECISION,
    legs=(
        PostingLegSchema(role=ChartAccountRole.CHECKING_CASH, side=PostingSide.DEBIT, amount_binding="amount"),
        PostingLegSchema(role=ChartAccountRole.CRYPTO_ASSET, side=PostingSide.CREDIT, amount_binding="amount"),
    ),
)

ASSET_SALE_PRIVATE_EQUITY_TO_CASH = JournalEntrySchema(
    journal_entry_type=JournalEntryType.ASSET_SALE,
    cause_type=AccountingCauseType.POLICY_DECISION,
    legs=(
        PostingLegSchema(role=ChartAccountRole.CHECKING_CASH, side=PostingSide.DEBIT, amount_binding="amount"),
        PostingLegSchema(role=ChartAccountRole.PRIVATE_EQUITY, side=PostingSide.CREDIT, amount_binding="amount"),
    ),
)

ASSET_SALE_PRIVATE_EQUITY_TO_PUBLIC_SECURITY = JournalEntrySchema(
    journal_entry_type=JournalEntryType.ASSET_SALE,
    cause_type=AccountingCauseType.POLICY_DECISION,
    legs=(
        PostingLegSchema(role=ChartAccountRole.PUBLIC_SECURITY, side=PostingSide.DEBIT, amount_binding="amount"),
        PostingLegSchema(role=ChartAccountRole.PRIVATE_EQUITY, side=PostingSide.CREDIT, amount_binding="amount"),
    ),
)

# Property sale --------------------------------------------------------------
#
# `PROPERTY_SALE` is a 5-leg settlement: the sale proceeds (gross) clear
# selling costs, mortgage debt payoff, and the property carrying value;
# remaining cash flows in (or out) via two cash legs split on the sign of
# `net_proceeds` so both stay non-negative. The caller supplies
# `cash_in = np.maximum(0, net_proceeds)` and `cash_out = np.maximum(0,
# -net_proceeds)`; future work can derive these from existing
# `ScenarioRunArrays` columns.

PROPERTY_SALE = JournalEntrySchema(
    journal_entry_type=JournalEntryType.PROPERTY_SALE,
    cause_type=AccountingCauseType.SCHEDULED_EVENT,
    legs=(
        PostingLegSchema(role=ChartAccountRole.CHECKING_CASH, side=PostingSide.DEBIT, amount_binding="cash_in"),
        PostingLegSchema(
            role=ChartAccountRole.PROPERTY_SALE_CLOSING_EXPENSE, side=PostingSide.DEBIT, amount_binding="selling_cost"
        ),
        PostingLegSchema(role=ChartAccountRole.MORTGAGE_PAYABLE, side=PostingSide.DEBIT, amount_binding="debt_payoff"),
        PostingLegSchema(role=ChartAccountRole.PROPERTY, side=PostingSide.CREDIT, amount_binding="gross"),
        PostingLegSchema(role=ChartAccountRole.CHECKING_CASH, side=PostingSide.CREDIT, amount_binding="cash_out"),
    ),
)

# Tax accrual + settlement ---------------------------------------------------
#
# `TAX_ACCRUAL` debits the expense and credits the corresponding payable.
# `TAX_PAYMENT_SETTLEMENT` debits the payable and credits cash, paying off
# the accrued balance. Estimated tax payments reuse `TAX_PAYMENT_SETTLEMENT`;
# the only difference is the liability_id on the TAX_PAYABLE leg, which the
# caller supplies via `leg_chart_account_keys`.

TAX_ACCRUAL = JournalEntrySchema(
    journal_entry_type=JournalEntryType.TAX_ACCRUAL,
    cause_type=AccountingCauseType.ACCOUNTING_PROCESS,
    legs=(
        PostingLegSchema(role=ChartAccountRole.TAX_EXPENSE, side=PostingSide.DEBIT, amount_binding="amount"),
        PostingLegSchema(role=ChartAccountRole.TAX_PAYABLE, side=PostingSide.CREDIT, amount_binding="amount"),
    ),
)

TAX_PAYMENT_SETTLEMENT = JournalEntrySchema(
    journal_entry_type=JournalEntryType.OBLIGATION_SETTLEMENT,
    cause_type=AccountingCauseType.OBLIGATION_SETTLEMENT,
    legs=(
        PostingLegSchema(role=ChartAccountRole.TAX_PAYABLE, side=PostingSide.DEBIT, amount_binding="amount"),
        PostingLegSchema(role=ChartAccountRole.CHECKING_CASH, side=PostingSide.CREDIT, amount_binding="amount"),
    ),
)

# Partner contribution -------------------------------------------------------
#
# Balanced cross-actor cash transfer: contributing actor's cash is credited
# (cash leaves) and recipient owner's cash is debited (cash arrives). Each
# posting carries a counterparty actor and the property id so the ledger
# explains the transfer.

PARTNER_CONTRIBUTION_TRANSFER = JournalEntrySchema(
    journal_entry_type=JournalEntryType.PARTNER_CONTRIBUTION,
    cause_type=AccountingCauseType.OBLIGATION_SETTLEMENT,
    legs=(
        PostingLegSchema(role=ChartAccountRole.CHECKING_CASH, side=PostingSide.DEBIT, amount_binding="amount"),
        PostingLegSchema(role=ChartAccountRole.CHECKING_CASH, side=PostingSide.CREDIT, amount_binding="amount"),
    ),
)

# Mortgage payment -----------------------------------------------------------
#
# Three-leg settlement: debit interest expense + debit mortgage principal,
# credit checking_cash. Caller supplies the per-rollout split between interest
# and principal as separate bindings plus the total cash amount.

MORTGAGE_PAYMENT = JournalEntrySchema(
    journal_entry_type=JournalEntryType.MORTGAGE_PAYMENT,
    cause_type=AccountingCauseType.OBLIGATION_SETTLEMENT,
    legs=(
        PostingLegSchema(
            role=ChartAccountRole.MORTGAGE_INTEREST_EXPENSE, side=PostingSide.DEBIT, amount_binding="interest_paid"
        ),
        PostingLegSchema(
            role=ChartAccountRole.MORTGAGE_PAYABLE, side=PostingSide.DEBIT, amount_binding="principal_paid"
        ),
        PostingLegSchema(role=ChartAccountRole.CHECKING_CASH, side=PostingSide.CREDIT, amount_binding="amount_paid"),
    ),
)

# Cash-debit obligation settlements ------------------------------------------
#
# Property tax / HOA dues / insurance / maintenance / outside rent / special
# assessment all settle the same way: one expense debit + a cash credit. They
# differ only in the expense `ChartAccountRole`, so each gets a schema keyed
# by that role and `CASH_DEBIT_SETTLEMENT_BY_EXPENSE_ROLE` dispatches by the
# `_CashDebitObligationKind.expense_role` selected at the engine call site.


def _cash_debit_settlement(expense_role: ChartAccountRole) -> JournalEntrySchema:
    return JournalEntrySchema(
        journal_entry_type=JournalEntryType.OBLIGATION_SETTLEMENT,
        cause_type=AccountingCauseType.OBLIGATION_SETTLEMENT,
        legs=(
            PostingLegSchema(role=expense_role, side=PostingSide.DEBIT, amount_binding="amount"),
            PostingLegSchema(role=ChartAccountRole.CHECKING_CASH, side=PostingSide.CREDIT, amount_binding="amount"),
        ),
    )


PROPERTY_TAX_SETTLEMENT = _cash_debit_settlement(ChartAccountRole.PROPERTY_TAX_EXPENSE)
HOA_SETTLEMENT = _cash_debit_settlement(ChartAccountRole.HOA_EXPENSE)
INSURANCE_SETTLEMENT = _cash_debit_settlement(ChartAccountRole.INSURANCE_EXPENSE)
MAINTENANCE_SETTLEMENT = _cash_debit_settlement(ChartAccountRole.MAINTENANCE_EXPENSE)
OUTSIDE_RENT_SETTLEMENT = _cash_debit_settlement(ChartAccountRole.OUTSIDE_RENT_EXPENSE)

CASH_DEBIT_SETTLEMENT_BY_EXPENSE_ROLE: dict[ChartAccountRole, JournalEntrySchema] = {
    ChartAccountRole.PROPERTY_TAX_EXPENSE: PROPERTY_TAX_SETTLEMENT,
    ChartAccountRole.HOA_EXPENSE: HOA_SETTLEMENT,
    ChartAccountRole.INSURANCE_EXPENSE: INSURANCE_SETTLEMENT,
    ChartAccountRole.MAINTENANCE_EXPENSE: MAINTENANCE_SETTLEMENT,
    ChartAccountRole.OUTSIDE_RENT_EXPENSE: OUTSIDE_RENT_SETTLEMENT,
}

# Monthly spend (cash expense) -----------------------------------------------
#
# Debit monthly_living_expense, credit checking_cash. Emitted by the monthly
# spend policy applier in `policy_runtime`.

MONTHLY_SPEND = JournalEntrySchema(
    journal_entry_type=JournalEntryType.CASH_EXPENSE,
    cause_type=AccountingCauseType.POLICY_DECISION,
    legs=(
        PostingLegSchema(role=ChartAccountRole.MONTHLY_LIVING_EXPENSE, side=PostingSide.DEBIT, amount_binding="amount"),
        PostingLegSchema(role=ChartAccountRole.CHECKING_CASH, side=PostingSide.CREDIT, amount_binding="amount"),
    ),
)

# Partner equity / principal credit ------------------------------------------
#
# Partner contribution allocation splits a contribution into a "used"
# portion (paid into shared house costs) and an "unallocated excess"
# portion (banked as a future partner equity claim). The credit leg
# represents the cross-actor cash transfer.

PARTNER_CONTRIBUTION_ALLOCATION = JournalEntrySchema(
    journal_entry_type=JournalEntryType.OWNERSHIP_CLAIM_ACCRUAL,
    cause_type=AccountingCauseType.ACCOUNTING_PROCESS,
    legs=(
        PostingLegSchema(
            role=ChartAccountRole.PARTNER_CONTRIBUTION_USED, side=PostingSide.DEBIT, amount_binding="contribution_used"
        ),
        PostingLegSchema(
            role=ChartAccountRole.PARTNER_UNALLOCATED_CLAIM, side=PostingSide.DEBIT, amount_binding="unallocated_excess"
        ),
        PostingLegSchema(
            role=ChartAccountRole.PARTNER_CONTRIBUTION_TRANSFER, side=PostingSide.CREDIT, amount_binding="contribution"
        ),
    ),
)

PARTNER_PRINCIPAL_CREDIT_ALLOCATION = JournalEntrySchema(
    journal_entry_type=JournalEntryType.OWNERSHIP_CLAIM_ACCRUAL,
    cause_type=AccountingCauseType.ACCOUNTING_PROCESS,
    legs=(
        PostingLegSchema(
            role=ChartAccountRole.PARTNER_PRINCIPAL_CREDIT, side=PostingSide.DEBIT, amount_binding="amount"
        ),
        PostingLegSchema(
            role=ChartAccountRole.PRINCIPAL_CREDIT_ALLOCATION, side=PostingSide.CREDIT, amount_binding="amount"
        ),
    ),
)

OWNER_PRINCIPAL_CREDIT_ALLOCATION = JournalEntrySchema(
    journal_entry_type=JournalEntryType.OWNERSHIP_CLAIM_ACCRUAL,
    cause_type=AccountingCauseType.ACCOUNTING_PROCESS,
    legs=(
        PostingLegSchema(role=ChartAccountRole.OWNER_PRINCIPAL_CREDIT, side=PostingSide.DEBIT, amount_binding="amount"),
        PostingLegSchema(
            role=ChartAccountRole.PRINCIPAL_CREDIT_ALLOCATION, side=PostingSide.CREDIT, amount_binding="amount"
        ),
    ),
)

# Property operating cash flow -----------------------------------------------
#
# Combined rental income + rental management/leasing fees, settled in one
# entry: cash debit on rental income, expense debits on the two fee lines,
# cash credit on the fee total (rental_management + rental_leasing). Property
# tax / HOA / insurance / maintenance settle separately via the obligation
# pipeline.

PROPERTY_OPERATING = JournalEntrySchema(
    journal_entry_type=JournalEntryType.PROPERTY_OPERATING,
    cause_type=AccountingCauseType.ACCOUNTING_PROCESS,
    legs=(
        PostingLegSchema(role=ChartAccountRole.CHECKING_CASH, side=PostingSide.DEBIT, amount_binding="rental_income"),
        PostingLegSchema(role=ChartAccountRole.RENTAL_INCOME, side=PostingSide.CREDIT, amount_binding="rental_income"),
        PostingLegSchema(
            role=ChartAccountRole.RENTAL_MANAGEMENT_FEE_EXPENSE,
            side=PostingSide.DEBIT,
            amount_binding="rental_management_fee",
        ),
        PostingLegSchema(
            role=ChartAccountRole.RENTAL_LEASING_FEE_EXPENSE,
            side=PostingSide.DEBIT,
            amount_binding="rental_leasing_fee",
        ),
        PostingLegSchema(
            role=ChartAccountRole.CHECKING_CASH, side=PostingSide.CREDIT, amount_binding="direct_carrying_cost"
        ),
    ),
)
