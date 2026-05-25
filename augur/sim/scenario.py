"""Scenario configuration — Pydantic models for the user-facing
config of a simulation run.

At spike 1, the scenario carries the agents, their initial cash
balances, a list of scheduled transfer events, and the horizon in
months. Later layers extend `Scenario` with positions (asset
holdings), liabilities (mortgages), properties, policies, the
external-series bundle reference, and tax profiles per agent.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, Field, NonNegativeInt, PositiveInt, model_validator

from augur.model.series_model import SeriesModelBundle


class Agent(BaseModel):
    """An agent in the simulation. Identified by a stable id used
    on every frame keyed by agent_id."""

    agent_id: str


class InitialAccountBalance(BaseModel):
    """Starting cash for one (agent, account) pair at month 0."""

    agent_id: str
    account_id: str
    balance_usd: float


class FixedAmount(BaseModel):
    """A scalar dollar amount that does not vary by rollout or month."""

    kind: Literal["fixed"] = "fixed"
    amount_usd: float


class SeriesIndexedAmount(BaseModel):
    """A dollar amount pegged to a sampled external level series.

    The amount is `base_amount_usd` at `base_month_index`. For a
    payment due in month `m`, the simulator first snaps to the current
    adjustment period and then scales linearly by the model level ratio:

    `base_amount_usd * series[reset_month] / series[base_month_index]`.

    With `adjustment_period_months=12`, a rent obligation stays flat for
    the first lease year, resets at month 12, stays flat through month 23,
    and so on.
    """

    kind: Literal["series_indexed"] = "series_indexed"
    base_amount_usd: float
    series_id: str
    base_month_index: NonNegativeInt = 0
    adjustment_period_months: PositiveInt = 1

    def _reset_month(self, month: int) -> int:
        elapsed = month - self.base_month_index
        return self.base_month_index + (elapsed // self.adjustment_period_months) * self.adjustment_period_months


type AmountSchedule = Annotated[FixedAmount | SeriesIndexedAmount, Field(discriminator="kind")]
type AmountSpec = float | AmountSchedule
type TransferIncomeCategory = Literal["ordinary", "ordinary_deduction"]


class ScheduledTransfer(BaseModel):
    """A cash transfer between two agents scheduled at a fixed
    month. Emitted by the engine as a Transfer event at that month;
    the amount may be fixed or derived from a series-indexed schedule.

    `income_category` tags the transfer for downstream tax classification:

    - `"ordinary"` — W-2-style wages, rental income, etc.: the `to_agent_id`'s
      `ordinary_income_ytd` increments by the transferred amount.
    - `"ordinary_deduction"` — Schedule-E-style deductible expense (e.g. property
      management fee paid by the owner): the `from_agent_id`'s
      `ordinary_income_ytd` decrements by the transferred amount. Used for
      deductible expenses paid via transfer flows (not the obligation/settlement
      pipeline). §469 passive-activity loss limitations are not modeled."""

    month: int
    cause_id: str
    from_agent_id: str
    from_account_id: str
    to_agent_id: str
    to_account_id: str
    amount_usd: AmountSpec
    income_category: TransferIncomeCategory | None = None


class RecurringTransfer(BaseModel):
    """A cash transfer that fires every month within a window. The
    canonical use is a recurring paycheck (income arriving monthly)
    or recurring rent / utilities. The engine emits one Transfer
    event per active month per rollout; series-indexed amounts may
    vary by rollout and adjustment period.

    `start_month` is inclusive. `end_month` is inclusive when
    supplied; when `None`, the transfer fires through the scenario's
    horizon end. The `cause_id` is reused on every emitted event row
    so a user can group_by it to see "every paycheck Alice
    received"."""

    start_month: int
    end_month: int | None = None
    cause_id: str
    from_agent_id: str
    from_account_id: str
    to_agent_id: str
    to_account_id: str
    amount_usd: AmountSpec
    income_category: TransferIncomeCategory | None = None

    def is_active_at(self, month: int) -> bool:
        return self.start_month <= month and (self.end_month is None or month <= self.end_month)


class ObligationType(StrEnum):
    """Closed set of `obligation_type` values that flow through dense engine event tables.

    Sim and product callers should use these enum members at construction sites and at
    filter sites in decoded `obligation_settlements` / `obligation_failures` frames.
    """

    CASH_SPEND = "cash_spend"
    OUTSIDE_RENT = "outside_rent"
    ESTIMATED_TAX = "estimated_tax"
    TAX_TRUE_UP = "tax_true_up"
    MORTGAGE_PAYMENT = "mortgage_payment"
    PROPERTY_TAX = "property_tax"
    HOA_DUES = "hoa_dues"
    HOMEOWNERS_INSURANCE = "homeowners_insurance"
    PROPERTY_MAINTENANCE = "property_maintenance"


class ScheduledObligation(BaseModel):
    """A required due-now payment at one month.

    Unlike a raw transfer, an obligation is settled through the
    liquidity-policy path: available cash plus policy-emitted sale
    proceeds must cover the whole amount, and the rollout fails if
    the full amount cannot be paid immediately.
    """

    month: int
    obligation_id: str
    obligation_type: str
    agent_id: str
    from_account_id: str
    to_agent_id: str
    to_account_id: str
    amount_due_usd: AmountSpec


class RecurringObligation(BaseModel):
    """A required due-now payment that repeats in a month window."""

    start_month: int
    end_month: int | None = None
    obligation_id: str
    obligation_type: str
    agent_id: str
    from_account_id: str
    to_agent_id: str
    to_account_id: str
    amount_due_usd: AmountSpec

    def is_active_at(self, month: int) -> bool:
        return self.start_month <= month and (self.end_month is None or month <= self.end_month)


class InitialLot(BaseModel):
    """A tax lot that exists at scenario start. Models pre-existing
    holdings: Alice already owns 100 units of VTI bought 24 months
    before the sim starts at $80/unit. The sim creates this lot at
    month 0 as an `AssetPurchase` event with the supplied
    `purchase_month_index` (which may be negative — purchases
    pre-dating the horizon are fine and feed into LTCG/STCG
    classification of later sales). `account_id` identifies the
    holding account used for FIFO pools; lots in different accounts
    are not fungible."""

    lot_id: str
    agent_id: str
    account_id: str = "checking"
    asset_id: str
    purchase_month_index: int
    quantity: float
    cost_basis_per_unit_usd: float


class ScheduledAssetSale(BaseModel):
    """Sell a configured quantity of an asset at a fixed month. The
    sale consumes from the agent's lots of that asset in
    `source_account_id` in FIFO order by `purchase_month_index`.
    Proceeds = `quantity * unit_price` are credited to
    `proceeds_account_id`.

    `price_per_unit_usd` is optional: when supplied the sale uses
    that price uniformly across rollouts (useful for deterministic
    tests). When `None`, the per-rollout per-month price comes from
    the scenario's `SeriesModelBundle` — the canonical case once external
    series integration is in play."""

    month: int
    cause_id: str
    agent_id: str
    source_account_id: str = "checking"
    asset_id: str
    quantity: float
    proceeds_account_id: str
    price_per_unit_usd: float | None = None


class LiquidityPolicy(BaseModel):
    """Asset-sale policy for one agent cash account.

    Required obligations create cash demands, but the policy decides
    whether and how to sell assets to fund them. If a policy emits no
    sale orders, the settlement phase will fail any hard demand that
    cash cannot already cover, even when the agent owns sellable
    assets. Optional cash-buffer rules run after hard demands are
    accounted for and never cause failure by themselves.
    """

    agent_id: str
    account_id: str
    asset_preference_chain: list[str]
    cash_buffer_trigger_below_usd: float = 0.0
    cash_buffer_sale_usd: float = 0.0
    cause_id_prefix: str = "liquidity_sale"


class TaxProfile(BaseModel):
    """A taxed agent's tax-time configuration. At spike 1 only
    single filers are modeled; later layers add MFJ / HoH and any
    filing-status-driven branching. `jurisdiction_ids` is the
    ordered list of taxing authorities — typically
    `["federal_us", "california"]` for a CA resident.

    `tax_authority_agent_id` is the destination of tax-payment
    transfers — a bookkeeping sink, not a taxed agent itself.
    `payment_account_id` is the agent's account that the engine
    debits for estimated-tax and true-up payments;
    `tax_authority_account_id` is the matching credit account on
    the authority side. `prior_year_tax_usd` is the aggregate
    safe-harbor target used to size quarterly estimated payments.
    If left at zero, no quarterly estimates are emitted and the
    January true-up pays the full accrued tax."""

    agent_id: str
    filing_status: str = "single"
    jurisdiction_ids: list[str]
    tax_authority_agent_id: str
    payment_account_id: str = "checking"
    tax_authority_account_id: str = "checking"
    prior_year_tax_usd: float = 0.0


class MortgageFinancing(BaseModel):
    """Mortgage terms attached to a property purchase."""

    liability_id: str
    lender_agent_id: str
    lender_account_id: str = "checking"
    principal_usd: float
    annual_interest_rate: float
    term_months: PositiveInt


class ScheduledPropertyPurchase(BaseModel):
    """Purchase a real property at a fixed month.

    The engine records property state, one owner stake row, optional
    mortgage origination, and a cash transfer for down payment plus
    buyer closing costs. Mortgage proceeds are not routed through the
    buyer's cash account in this first slice; the purchase is booked
    net, with the debt appearing as a liability.
    """

    month: int
    cause_id: str
    property_id: str
    location_id: str
    buyer_agent_id: str
    buyer_account_id: str
    seller_agent_id: str
    seller_account_id: str = "checking"
    purchase_price_usd: float
    down_payment_usd: float
    buyer_closing_cost_usd: float = 0.0
    ownership_pct: float = 1.0
    mortgage: MortgageFinancing | None = None


class PropertyTaxPolicy(BaseModel):
    """Monthly property-tax carrying cost for an owned property.

    `annual_tax_rate` can override location reference data; when it
    is `None`, the rate comes from `Location.annual_property_tax_rate`.
    """

    property_id: str
    owner_agent_id: str
    from_account_id: str = "checking"
    tax_authority_agent_id: str
    tax_authority_account_id: str = "checking"
    annual_tax_rate: float | None = None
    start_month: int = 0
    end_month: int | None = None

    def is_active_at(self, month: int) -> bool:
        return self.start_month <= month and (self.end_month is None or month <= self.end_month)


class FederalSaltCapEntry(BaseModel):
    """One step of the federal SALT-cap schedule.

    The cap that applies in calendar-year-index `Y` is the `cap_usd` of the
    latest entry with `effective_year_index <= Y`. Year-index is 0-based from
    the start of the simulation horizon, so [(0, 40_000.0), (4, 10_000.0)]
    encodes "$40k for years 0..3, then $10k from year 4 onward" — the OBBBA
    transition for a 2026-start sim ($40k for 2026..2029, $10k from 2030).
    """

    effective_year_index: int
    cap_usd: float


# Default schedule reflects the TCJA + OBBBA federal SALT-cap timeline as
# enacted through mid-2025: $40k cap for 2025..2029 (current sims start in 2026
# so year index 0..3), reverting to $10k from 2030 onward. Sims that span the
# transition see the cap tighten mid-horizon.
#
# Known modeling gaps (not implemented; document so the consumer knows what
# we elide):
#   - **AGI-based phase-out of the $40k cap.** The OBBBA cap phases down for
#     high incomes (over ~$500k AGI); we treat it as a flat ceiling.
#   - **Sales tax election.** Taxpayers in no-state-income-tax states may
#     deduct state sales tax instead of state income tax; we always use the
#     accrued state income tax.
#   - **Timing nuance.** Real Schedule A allows deducting state taxes *paid*
#     in the calendar year, which can include prior-year true-ups. We deduct
#     state tax *accrued in this calendar year* (equivalent to assuming all
#     state tax is withheld in the year of accrual).
#   - **Standalone post-2029 sunset.** If Congress doesn't extend OBBBA,
#     2030+ reverts to the TCJA $10k cap — already reflected here. If the
#     entire TCJA sunset triggers, the cap disappears (deduction becomes
#     unlimited); express that by passing an empty schedule (no entries =
#     no cap = uncapped SALT deduction).
DEFAULT_FEDERAL_SALT_CAP_SCHEDULE: tuple[FederalSaltCapEntry, ...] = (
    FederalSaltCapEntry(effective_year_index=0, cap_usd=40_000.0),
    FederalSaltCapEntry(effective_year_index=4, cap_usd=10_000.0),
)


class FederalSaltDeductionPolicy(BaseModel):
    """Federal SALT deduction (Schedule A) for one tax profile.

    SALT contributors are derived from the targeted `TaxProfile`: every
    jurisdiction in `TaxProfile.jurisdiction_ids` other than
    `federal_jurisdiction_id` is treated as a state/local jurisdiction whose
    annual accrued income tax flows into the federal SALT total, alongside
    property tax paid this calendar year by the profile's agent. The total
    is capped per `cap_schedule` and surfaces as a federal itemized line
    that stacks with MID.

    `federal_jurisdiction_id` is the jurisdiction within the profile that
    *receives* the SALT deduction; the SALT cap is a federal-Schedule-A
    concept and only applies there. Default `federal_us` matches the
    convention used by `local_regulation.py` and `tax_profile_defaults`.
    """

    profile_id: str
    federal_jurisdiction_id: str = "federal_us"
    cap_schedule: list[FederalSaltCapEntry] = Field(default_factory=lambda: list(DEFAULT_FEDERAL_SALT_CAP_SCHEDULE))


class PrivateEquityTenderPolicy(BaseModel):
    """Sell private-equity units at sampled tender events to lift liquid net worth to a floor.

    At each tender event for any held PE position belonging to `owner_agent_id`, the engine:

    1. Computes the rollout's current liquid net worth (cash + non-PE lots × their current
       sampled price, by definition excluding PE itself — PE is illiquid).
    2. Evaluates `liquid_net_worth_floor` at the event month. `SeriesIndexedAmount` lets the
       floor inflate (or peg to any other series); a `FixedAmount` keeps it nominal.
    3. `shortfall = max(0, floor - lnw)`.
    4. Sells `min(units_held_in_issuer, shortfall / mark)` units of the tendering issuer at
       the issuer's per-rollout mark (from the PE trajectory bundle).
    5. Proceeds credit `proceeds_account_id`; cap-gain flows through the standard FIFO
       lot-drain machinery (LTCG / STCG by holding period — IRS treats crypto/property/PE
       identically for cap-gains purposes).

    Multiple tenders firing in the same month process in deterministic issuer order; each
    sale updates the cash balance + lot remaining before the next tender's LNW check runs,
    so the floor genuinely caps aggregate sale across all same-month tenders.

    Scope notes (deferred enhancements, captured here so a future reader knows what's missing):

    - **Per-issuer policies.** v1 supports one global policy per agent; a per-issuer policy
      list (`floor_by_issuer: dict[str, AmountSchedule]`) could allow "sell only OpenAI to
      reach $X, never sell SpaceX") if needed.
    - **Partial-tender fraction.** Real tenders sometimes cap participation (e.g. "you may
      sell up to 20% of your holdings"). The trajectory artifact carries a
      `saleable_fraction` field already; consuming it would let the policy gate units sold
      to `min(units_held × saleable_fraction, shortfall / mark)`. Not wired today.
    - **§1202 QSBS exclusion.** Federal exclusion of up to $10M / 10× basis on qualified
      small-business stock held ≥5 years. Not modeled; the user confirmed they don't hold
      QSBS-eligible PE.
    """

    owner_agent_id: str
    proceeds_account_id: str = "checking"
    liquid_net_worth_floor: AmountSchedule


class MortgageInterestDeductionPolicy(BaseModel):
    """Mortgage-interest deduction (IRC §163(h)(3)) for one liability.

    At each tax-year-end, deductible interest =
    `liability_interest_ytd * min(1, principal_cap / origination_principal)`
    per jurisdiction listed in `per_jurisdiction_principal_cap_usd`.
    The qualifying interest from this policy is summed across all
    qualifying liabilities owned by the profile's agent and compared
    against the standard deduction; the engine uses
    `max(itemized, standard)` before bracket-walking.

    Federal (post-TCJA) caps acquisition debt at $750k. California's
    pre-TCJA $1M cap was preserved, so the two diverge for moderately-
    large mortgages.
    """

    liability_id: str
    owner_agent_id: str
    per_jurisdiction_principal_cap_usd: dict[str, float] = Field(
        default_factory=lambda: {"federal_us": 750_000.0, "california": 1_000_000.0}
    )


class Scenario(BaseModel):
    """Spike-1 simulation scenario. Carries the minimum to run
    a multi-rollout simulation over a fixed horizon with both
    scheduled and recurring transfers, plus tax lots and asset
    sales."""

    agents: list[Agent]
    initial_cash: list[InitialAccountBalance]
    initial_lots: list[InitialLot] = Field(default_factory=list)
    scheduled_transfers: list[ScheduledTransfer] = Field(default_factory=list)
    recurring_transfers: list[RecurringTransfer] = Field(default_factory=list)
    scheduled_obligations: list[ScheduledObligation] = Field(default_factory=list)
    recurring_obligations: list[RecurringObligation] = Field(default_factory=list)
    scheduled_asset_sales: list[ScheduledAssetSale] = Field(default_factory=list)
    scheduled_property_purchases: list[ScheduledPropertyPurchase] = Field(default_factory=list)
    property_tax_policies: list[PropertyTaxPolicy] = Field(default_factory=list)
    mortgage_interest_deduction_policies: list[MortgageInterestDeductionPolicy] = Field(default_factory=list)
    federal_salt_deduction_policies: list[FederalSaltDeductionPolicy] = Field(default_factory=list)
    private_equity_tender_policies: list[PrivateEquityTenderPolicy] = Field(default_factory=list)
    external_series: SeriesModelBundle = Field(default_factory=SeriesModelBundle)
    # Required so callers explicitly choose either taxed agents or an intentional no-tax scenario.
    tax_profiles: list[TaxProfile]
    liquidity_policies: list[LiquidityPolicy] = Field(default_factory=list)
    horizon_months: PositiveInt

    @model_validator(mode="after")
    def _reject_duplicate_initial_lot_purchase_months(self) -> Scenario:
        seen: dict[tuple[str, str, str, int], str] = {}
        duplicates: list[tuple[str, str, str, int, str, str]] = []
        for lot in self.initial_lots:
            key = (lot.agent_id, lot.account_id, lot.asset_id, lot.purchase_month_index)
            previous_lot_id = seen.get(key)
            if previous_lot_id is not None:
                duplicates.append((*key, previous_lot_id, lot.lot_id))
            else:
                seen[key] = lot.lot_id
        if duplicates:
            duplicate_list = ", ".join(
                f"{agent_id}/{account_id}/{asset_id}@{purchase_month} ({first_lot_id}, {second_lot_id})"
                for agent_id, account_id, asset_id, purchase_month, first_lot_id, second_lot_id in sorted(duplicates)
            )
            raise ValueError(f"duplicate initial lot purchase months for FIFO pool(s): {duplicate_list}")
        return self

    @model_validator(mode="after")
    def _reject_out_of_horizon_scheduled_events(self) -> Scenario:
        horizon = int(self.horizon_months)
        for sale in self.scheduled_asset_sales:
            if not 0 <= sale.month < horizon:
                raise ValueError(
                    f"scheduled asset sale {sale.cause_id!r} has month {sale.month}, "
                    f"outside scenario horizon [0, {horizon})"
                )
        for purchase in self.scheduled_property_purchases:
            if not 0 <= purchase.month < horizon:
                raise ValueError(
                    f"scheduled property purchase {purchase.cause_id!r} has month {purchase.month}, "
                    f"outside scenario horizon [0, {horizon})"
                )
        return self

    @model_validator(mode="after")
    def _reject_duplicate_liquidity_policy_accounts(self) -> Scenario:
        seen: set[tuple[str, str]] = set()
        duplicates: set[tuple[str, str]] = set()
        for policy in self.liquidity_policies:
            key = (policy.agent_id, policy.account_id)
            if key in seen:
                duplicates.add(key)
            seen.add(key)
        if duplicates:
            duplicate_list = ", ".join(f"{agent_id}/{account_id}" for agent_id, account_id in sorted(duplicates))
            raise ValueError(f"duplicate liquidity policies for account(s): {duplicate_list}")
        return self
