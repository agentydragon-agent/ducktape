"""Product-language projection request and response wire types."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, NonNegativeFloat, NonNegativeInt, PositiveFloat, PositiveInt, model_validator

from augur.api.schemas import ApiModel, Frame, Percentage

SpendIndex = Literal["none", "inflation"]
SellableBucket = Literal["stocks", "crypto"]
MetricName = Literal[
    "cash_usd",
    "holding_value_usd",
    "private_equity_value_usd",
    "property_value_usd",
    "mortgage_balance_usd",
    "home_equity_usd",
    "liquid_net_worth_usd",
    "net_worth_usd",
    "shortfall_usd",
]
MAX_HORIZON_MONTHS = 100 * 12
DEFAULT_SELL_ORDER: tuple[SellableBucket, ...] = ("stocks", "crypto")


class FundingPolicy(ApiModel):
    cash_buffer_trigger_below_usd: NonNegativeFloat = 0.0
    cash_buffer_sale_usd: NonNegativeFloat = 0.0
    sell_order: tuple[SellableBucket, ...] = DEFAULT_SELL_ORDER


class PrivateEquityTenderPolicyWire(ApiModel):
    """User-facing PE tender policy. At each tender event for any held PE position, the
    engine sells units to lift liquid net worth (cash + non-PE holdings) to this floor.

    `liquid_net_worth_floor_usd` of 0 disables PE sales entirely (LNW always >= floor).
    `index_floor_to_inflation` (default true) inflates the floor with CPI so the real-terms
    target stays constant over long horizons. Set to false to keep the floor nominal.
    """

    liquid_net_worth_floor_usd: NonNegativeFloat = 0.0
    index_floor_to_inflation: bool = True


class CashFinancing(ApiModel):
    kind: Literal["cash"] = "cash"


class MortgageFinancing(ApiModel):
    kind: Literal["mortgage"] = "mortgage"
    term_months: Literal[180, 360]
    down_payment_pct: NonNegativeFloat
    annual_rate_pct: NonNegativeFloat


type PropertyFinancing = Annotated[CashFinancing | MortgageFinancing, Field(discriminator="kind")]


class RentalIncomePlan(ApiModel):
    """The property is being rented out to a tenant.

    `fraction_rented` = 1.0 means the whole property is rented (pure investment or
    user lives elsewhere). `fraction_rented` < 1.0 means partial rental (e.g. owner
    occupies the main unit and rents the ADU / rents rooms).

    `monthly_rent_collected_usd` is the gross monthly rent (before vacancy + management
    fees). If `None`, the translator falls back to `Property.rent_estimate_usd` for the
    purchased property; if that's also missing, the request is rejected.
    """

    monthly_rent_collected_usd: PositiveFloat | None = None
    fraction_rented: PositiveFloat = Field(default=1.0, le=1.0)
    # 0..1 multiplier on collected rent. Captures marketing-time vacancy + tenant turnover
    # vacancy in a smoothed-average form; per-rollout stochastic vacancy is a future model.
    vacancy_pct: NonNegativeFloat = Field(default=0.05, le=1.0)


class RentalManagement(ApiModel):
    """Property management agency terms.

    Management fee fires monthly against collected (post-vacancy) rent.
    Leasing fee fires every `avg_tenancy_months` while the property is rented (first fire
    when the rental status activates). Captures lifetime tenant-placement cost without
    modeling specific tenants.
    """

    management_fee_pct: NonNegativeFloat = Field(default=8.0, le=100.0)
    leasing_fee_months: NonNegativeFloat = Field(default=1.0)
    avg_tenancy_months: PositiveInt = 24


class PropertyPurchase(ApiModel):
    property_id: str
    closing_cost_pct: NonNegativeFloat = 1.5
    financing: PropertyFinancing
    # Owner-occupied: gates the federal/CA mortgage interest deduction (§163(h)(3)). When false,
    # the property is treated as an investment / second home and no MID policy is built. No
    # default: callers must commit to an answer rather than inherit one silently.
    is_primary_residence: bool
    # The property is rented (whole or partial) from month 0. Phase 3 will let the user
    # toggle this mid-horizon via lifecycle events.
    initial_rental: RentalIncomePlan | None = None
    # Property is managed by an agency. Requires `initial_rental` set.
    rental_management: RentalManagement | None = None

    @model_validator(mode="after")
    def _rental_management_requires_rental(self) -> PropertyPurchase:
        if self.rental_management is not None and self.initial_rental is None:
            raise ValueError("rental_management requires initial_rental to be set")
        # Pure investment property must not also claim primary-residence MID treatment.
        if self.initial_rental is not None and self.initial_rental.fraction_rented >= 1.0 and self.is_primary_residence:
            raise ValueError("is_primary_residence must be False when fraction_rented == 1.0")
        return self


DEFAULT_ANNUAL_INSURANCE_PCT = 0.4
DEFAULT_ANNUAL_MAINTENANCE_PCT = 1.0


class ScenarioKey(ApiModel):
    exogenous_model_id: str
    horizon_months: PositiveInt = Field(le=MAX_HORIZON_MONTHS)
    monthly_spend_usd: PositiveFloat
    spend_index: SpendIndex
    funding_policy: FundingPolicy = Field(default_factory=FundingPolicy)
    pe_tender_policy: PrivateEquityTenderPolicyWire = Field(default_factory=PrivateEquityTenderPolicyWire)
    monthly_rent_usd: NonNegativeFloat = 0.0
    rental_location_id: str | None = None
    property_purchase: PropertyPurchase | None = None
    annual_insurance_pct: NonNegativeFloat = DEFAULT_ANNUAL_INSURANCE_PCT
    annual_maintenance_pct: NonNegativeFloat = DEFAULT_ANNUAL_MAINTENANCE_PCT

    @model_validator(mode="after")
    def _rent_location_consistency(self) -> ScenarioKey:
        if self.monthly_rent_usd > 0 and self.rental_location_id is None:
            raise ValueError("rental_location_id is required when monthly_rent_usd > 0")
        if self.monthly_rent_usd == 0 and self.rental_location_id is not None:
            raise ValueError("rental_location_id must be unset when monthly_rent_usd == 0")
        return self


class MetricFanRequest(ApiModel):
    scenario: ScenarioKey
    rollout_seeds: tuple[NonNegativeInt, ...] = Field(min_length=1)
    metric: MetricName
    percentiles: tuple[Percentage, ...] = Field(min_length=1)

    @property
    def rollout_count(self) -> int:
        return len(self.rollout_seeds)


class RolloutRequest(ApiModel):
    scenario: ScenarioKey
    seed: NonNegativeInt


class TerminalMetrics(ApiModel):
    cash_usd: float
    holding_value_usd: NonNegativeFloat
    private_equity_value_usd: NonNegativeFloat = 0.0
    property_value_usd: NonNegativeFloat = 0.0
    mortgage_balance_usd: NonNegativeFloat = 0.0
    home_equity_usd: float = 0.0
    liquid_net_worth_usd: float
    net_worth_usd: float
    shortfall_usd: NonNegativeFloat
    failed_month_index: NonNegativeInt | None = None


class _RolloutEventBase(ApiModel):
    month_index: NonNegativeInt
    amount_usd: NonNegativeFloat


class HoldingSaleEvent(_RolloutEventBase):
    kind: Literal["holding_sale"] = "holding_sale"
    asset_id: str
    asset_label: str | None = None
    units: NonNegativeFloat
    proceeds_usd: NonNegativeFloat
    cost_basis_usd: NonNegativeFloat


class MonthlyExpenseEvent(_RolloutEventBase):
    kind: Literal["monthly_expense"] = "monthly_expense"
    amount_due_usd: NonNegativeFloat
    amount_paid_usd: NonNegativeFloat
    shortfall_usd: NonNegativeFloat


class OutsideRentPaymentEvent(_RolloutEventBase):
    kind: Literal["outside_rent"] = "outside_rent"
    amount_due_usd: NonNegativeFloat
    amount_paid_usd: NonNegativeFloat
    shortfall_usd: NonNegativeFloat


class PropertyPurchaseEvent(_RolloutEventBase):
    kind: Literal["property_purchase"] = "property_purchase"
    property_id: str
    purchase_price_usd: NonNegativeFloat
    down_payment_usd: NonNegativeFloat
    mortgage_principal_usd: NonNegativeFloat


class ClosingCostPaymentEvent(_RolloutEventBase):
    kind: Literal["closing_cost_payment"] = "closing_cost_payment"
    property_id: str


class MortgagePaymentEvent(_RolloutEventBase):
    kind: Literal["mortgage_payment"] = "mortgage_payment"
    interest_usd: NonNegativeFloat
    principal_usd: NonNegativeFloat


class PropertyTaxPaymentEvent(_RolloutEventBase):
    kind: Literal["property_tax_payment"] = "property_tax_payment"
    amount_due_usd: NonNegativeFloat
    amount_paid_usd: NonNegativeFloat
    shortfall_usd: NonNegativeFloat


class HoaDuesPaymentEvent(_RolloutEventBase):
    kind: Literal["hoa_dues_payment"] = "hoa_dues_payment"
    amount_due_usd: NonNegativeFloat
    amount_paid_usd: NonNegativeFloat
    shortfall_usd: NonNegativeFloat


class HomeownersInsurancePaymentEvent(_RolloutEventBase):
    kind: Literal["homeowners_insurance_payment"] = "homeowners_insurance_payment"
    amount_due_usd: NonNegativeFloat
    amount_paid_usd: NonNegativeFloat
    shortfall_usd: NonNegativeFloat


class PropertyMaintenancePaymentEvent(_RolloutEventBase):
    kind: Literal["property_maintenance_payment"] = "property_maintenance_payment"
    amount_due_usd: NonNegativeFloat
    amount_paid_usd: NonNegativeFloat
    shortfall_usd: NonNegativeFloat


class TaxAccrualEvent(_RolloutEventBase):
    kind: Literal["tax_accrual"] = "tax_accrual"
    jurisdiction_id: str
    tax_year_end_month: NonNegativeInt
    ordinary_income_usd: float
    ltcg_usd: float
    stcg_usd: float
    ordinary_tax_usd: NonNegativeFloat
    capital_gain_tax_usd: NonNegativeFloat
    total_tax_usd: NonNegativeFloat
    # MID under this jurisdiction's principal cap, 0.0 when not active.
    mortgage_interest_deduction_usd: NonNegativeFloat = 0.0
    # Sum of itemized lines (today MID is the only one). Consumer renders the larger of itemized
    # vs. standard as the "deduction used".
    itemized_deduction_usd: NonNegativeFloat = 0.0
    standard_deduction_usd: NonNegativeFloat = 0.0


class TaxPaymentEvent(_RolloutEventBase):
    kind: Literal["tax_payment"] = "tax_payment"
    obligation_type: str
    amount_due_usd: NonNegativeFloat
    amount_paid_usd: NonNegativeFloat
    shortfall_usd: NonNegativeFloat


class RolloutFailureEvent(_RolloutEventBase):
    kind: Literal["failure"] = "failure"
    amount_due_usd: NonNegativeFloat
    amount_paid_usd: NonNegativeFloat
    shortfall_usd: NonNegativeFloat


type RolloutEvent = Annotated[
    HoldingSaleEvent
    | MonthlyExpenseEvent
    | OutsideRentPaymentEvent
    | PropertyPurchaseEvent
    | ClosingCostPaymentEvent
    | MortgagePaymentEvent
    | PropertyTaxPaymentEvent
    | HoaDuesPaymentEvent
    | HomeownersInsurancePaymentEvent
    | PropertyMaintenancePaymentEvent
    | TaxAccrualEvent
    | TaxPaymentEvent
    | RolloutFailureEvent,
    Field(discriminator="kind"),
]


class RolloutOutput(ApiModel):
    seed: NonNegativeInt
    failed: bool
    monthly_metrics: Frame
    terminal_metrics: TerminalMetrics
    events: tuple[RolloutEvent, ...] = ()


class RolloutSummary(ApiModel):
    seed: NonNegativeInt
    failed: bool
    terminal_metrics: TerminalMetrics
    sort_rank: NonNegativeInt
    rank_percentile: Percentage


class MetricFanResponse(ApiModel):
    exogenous_model_id: str
    metric: MetricName
    monthly_metric_fan: Frame
    terminal_metric_percentiles: Frame
    rollout_summaries: tuple[RolloutSummary, ...]
    failed_count: NonNegativeInt
    diagnostics: tuple[str, ...] = ()


class RolloutResponse(ApiModel):
    exogenous_model_id: str
    rollout: RolloutOutput
    diagnostics: tuple[str, ...] = ()
