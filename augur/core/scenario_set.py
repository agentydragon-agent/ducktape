from __future__ import annotations

from collections import Counter
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import Field, NonNegativeFloat, NonNegativeInt, PositiveFloat, PositiveInt, model_validator

from augur.core.local_regulation import LocalRegulation
from augur.core.schemas import ApiModel, ColumnarTable, Percentage


class EventType(StrEnum):
    PROPERTY_PURCHASE = "property_purchase"
    PROPERTY_SALE = "property_sale"
    MORTGAGE_ORIGINATION = "mortgage_origination"
    MOVE_RESIDENCE = "move_residence"
    START_RENTAL = "start_rental"
    STOP_RENTAL = "stop_rental"
    PORTFOLIO_TRADE = "portfolio_trade"
    PRIVATE_EQUITY_IPO = "private_equity_ipo"
    PRIVATE_EQUITY_ACQUISITION = "private_equity_acquisition"


class PolicyType(StrEnum):
    CHECKING_FLOOR_SELL_PUBLIC_STOCK = "checking_floor_sell_public_stock"
    PRIVATE_EQUITY_SALE = "private_equity_sale"
    PORTFOLIO_TARGET_REBALANCE = "portfolio_target_rebalance"
    PARTNER_EQUITY_ACCRUAL = "partner_equity_accrual"
    MANUAL_EVENT_SCHEDULE = "manual_event_schedule"
    LIQUIDITY_RESERVE = "liquidity_reserve"
    MONTHLY_SPEND = "monthly_spend"


class PrivateEquitySaleRuleType(StrEnum):
    FIXED_AMOUNT_ON_OPPORTUNITY = "fixed_amount_on_opportunity"
    LIQUID_NET_WORTH_FLOOR = "liquid_net_worth_floor"


class PrivateEquitySaleProceedsDestination(StrEnum):
    CASH = "cash"
    GENERIC_SP500_STOCK = "generic_sp500_stock"


class LiquidityReserveRuleType(StrEnum):
    FIXED = "fixed"
    PROJECTED_DEFICITS = "projected_deficits"


class ActionType(StrEnum):
    SELL_SP500 = "sell_sp500"
    SELL_PRIVATE_EQUITY = "sell_private_equity"
    SETTLE_PROPERTY_SALE = "settle_property_sale"
    TRANSFER_PARTNER_CONTRIBUTION = "transfer_partner_contribution"
    PAY_MORTGAGE = "pay_mortgage"
    ACCRUE_PARTNER_EQUITY = "accrue_partner_equity"
    MONTHLY_SPEND = "monthly_spend"


class PolicyDecisionType(StrEnum):
    MONTHLY_SPEND = "monthly_spend"
    SELL_PUBLIC_STOCK = "sell_public_stock"
    PRIVATE_EQUITY_SALE = "private_equity_sale"
    PARTNER_CONTRIBUTION = "partner_contribution"


class PrivateEquitySaleDecisionReason(StrEnum):
    NO_SALE_OPPORTUNITY = "no_sale_opportunity"
    POLICY_NOT_TRIGGERED = "policy_not_triggered"
    SALE_REQUESTED = "sale_requested"


class MarketObservationType(StrEnum):
    MARKET_PATH = "market_path"
    PRIVATE_EQUITY_SALE_OPPORTUNITY = "private_equity_sale_opportunity"


class RolloutStatusType(StrEnum):
    ACTIVE = "active"
    CASH_NEGATIVE = "cash_negative"


class AccountingDetailType(StrEnum):
    PROPERTY_SALE_BASIS_GAIN = "property_sale_basis_gain"
    TAX_PAYMENT_ALLOCATION = "tax_payment_allocation"


class TaxPaymentTiming(StrEnum):
    ALLOCATED_TO_SOURCE_MONTH = "allocated_to_source_month"


class ActorRole(StrEnum):
    PRIMARY_OWNER = "primary_owner"
    EQUITY_BUILDING_OCCUPANT = "equity_building_occupant"
    TENANT = "tenant"
    LANDLORD = "landlord"


class AccountType(StrEnum):
    CHECKING = "checking"
    TAXABLE_BROKERAGE = "taxable_brokerage"
    ESCROW = "escrow"


class AssetType(StrEnum):
    CASH = "cash"
    GENERIC_SP500_STOCK = "generic_sp500_stock"
    PRIVATE_EQUITY = "private_equity"
    REAL_ESTATE = "real_estate"
    DEFERRED_TAX_ASSET = "deferred_tax_asset"


class LiabilityType(StrEnum):
    MORTGAGE = "mortgage"
    TAX_LIABILITY = "tax_liability"
    ACTOR_EQUITY_CLAIM = "actor_equity_claim"


PropertyId = str


class OccupancyMode(StrEnum):
    OWNER_LIVES_IN_PROPERTY = "owner_lives_in_property"
    OWNER_LIVES_IN_OTHER_OWNED_PROPERTY = "owner_lives_in_other_owned_property"
    OWNER_RENTS_ELSEWHERE = "owner_rents_elsewhere"
    NO_OWNER_OCCUPANCY = "no_owner_occupancy"


class RentalMode(StrEnum):
    NOT_RENTED = "not_rented"
    RENT_ROOMS_WHILE_OWNER_LIVES_THERE = "rent_rooms_while_owner_lives_there"
    RENT_WHOLE_PROPERTY = "rent_whole_property"
    TRANSITION_TO_WHOLE_PROPERTY_RENTAL = "transition_to_whole_property_rental"


class TaxRegime(StrEnum):
    CALIFORNIA_PROP13 = "california_prop13"
    CALIFORNIA_OWNER_OCCUPIED = "california_owner_occupied"
    CALIFORNIA_INVESTMENT_PROPERTY = "california_investment_property"
    SAN_FRANCISCO_SECURED_PROPERTY_TAX = "san_francisco_secured_property_tax"
    SAN_FRANCISCO_TRANSFER_TAX = "san_francisco_transfer_tax"
    VALLEJO_PROPERTY_TAX = "vallejo_property_tax"
    MARE_ISLAND_SPECIAL_ASSESSMENTS = "mare_island_special_assessments"
    CALIFORNIA_TRANSFER_TAX = "california_transfer_tax"
    FEDERAL_MORTGAGE_INTEREST = "federal_mortgage_interest"
    RENTAL_DEPRECIATION = "rental_depreciation"
    DEPRECIATION_RECAPTURE = "depreciation_recapture"
    FEDERAL_CAPITAL_GAINS = "federal_capital_gains"
    CALIFORNIA_INCOME_TAX = "california_income_tax"
    PRIMARY_RESIDENCE_EXCLUSION = "primary_residence_exclusion"


class TaxFilingStatus(StrEnum):
    SINGLE = "single"
    MARRIED_FILING_JOINTLY = "married_filing_jointly"
    MARRIED_FILING_SEPARATELY = "married_filing_separately"
    HEAD_OF_HOUSEHOLD = "head_of_household"


class FinancingMode(StrEnum):
    CASH = "cash"
    FIXED_30 = "fixed_30"
    FIXED_15 = "fixed_15"
    CUSTOM = "custom"


class ReportMetric(StrEnum):
    NET_WORTH = "net_worth"
    LIQUID_NET_WORTH = "liquid_net_worth"
    HOME_EQUITY = "home_equity"
    ACTOR_EQUITY = "actor_equity"
    PROPERTY_VALUE = "property_value"
    OWNER_CASH_FLOW = "owner_cash_flow"
    TAX_CASH_FLOW = "tax_cash_flow"
    PRIVATE_EQUITY_SALE_OPPORTUNITY = "private_equity_sale_opportunity"


class Actor(ApiModel):
    actor_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_\-]*$")
    label: str
    role: ActorRole


class _EventBase(ApiModel):
    event_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_\-]*$")
    month_index: NonNegativeInt
    actor_id: str | None = None
    property_id: PropertyId | None = None
    amount_usd: float | None = None
    description: str | None = None


class PropertyPurchaseEvent(_EventBase):
    event_type: Literal[EventType.PROPERTY_PURCHASE] = EventType.PROPERTY_PURCHASE
    hoa_monthly_usd: NonNegativeFloat | None = None


class PropertySaleEvent(_EventBase):
    event_type: Literal[EventType.PROPERTY_SALE] = EventType.PROPERTY_SALE


class MortgageOriginationEvent(_EventBase):
    event_type: Literal[EventType.MORTGAGE_ORIGINATION] = EventType.MORTGAGE_ORIGINATION


class MoveResidenceEvent(_EventBase):
    event_type: Literal[EventType.MOVE_RESIDENCE] = EventType.MOVE_RESIDENCE


class StartRentalEvent(_EventBase):
    event_type: Literal[EventType.START_RENTAL] = EventType.START_RENTAL


class StopRentalEvent(_EventBase):
    event_type: Literal[EventType.STOP_RENTAL] = EventType.STOP_RENTAL


class PortfolioTradeEvent(_EventBase):
    event_type: Literal[EventType.PORTFOLIO_TRADE] = EventType.PORTFOLIO_TRADE


class PrivateEquityIpoEvent(_EventBase):
    event_type: Literal[EventType.PRIVATE_EQUITY_IPO] = EventType.PRIVATE_EQUITY_IPO


class PrivateEquityAcquisitionEvent(_EventBase):
    event_type: Literal[EventType.PRIVATE_EQUITY_ACQUISITION] = EventType.PRIVATE_EQUITY_ACQUISITION


Event = Annotated[
    PropertyPurchaseEvent
    | PropertySaleEvent
    | MortgageOriginationEvent
    | MoveResidenceEvent
    | StartRentalEvent
    | StopRentalEvent
    | PortfolioTradeEvent
    | PrivateEquityIpoEvent
    | PrivateEquityAcquisitionEvent,
    Field(discriminator="event_type"),
]


class _PolicyBase(ApiModel):
    policy_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_\-]*$")
    actor_id: str
    enabled: bool = True


class CheckingFloorSellPublicStockPolicy(_PolicyBase):
    """Sell SP500 when checking cash dips below a floor."""

    policy_type: Literal[PolicyType.CHECKING_FLOOR_SELL_PUBLIC_STOCK] = PolicyType.CHECKING_FLOOR_SELL_PUBLIC_STOCK
    floor_usd: NonNegativeFloat = 0.0
    sale_amount_usd: NonNegativeFloat = 0.0


class FixedAmountPrivateEquitySaleRule(ApiModel):
    sale_rule_type: Literal[PrivateEquitySaleRuleType.FIXED_AMOUNT_ON_OPPORTUNITY] = (
        PrivateEquitySaleRuleType.FIXED_AMOUNT_ON_OPPORTUNITY
    )
    amount_usd: PositiveFloat


class LiquidNetWorthFloorPrivateEquitySaleRule(ApiModel):
    sale_rule_type: Literal[PrivateEquitySaleRuleType.LIQUID_NET_WORTH_FLOOR] = (
        PrivateEquitySaleRuleType.LIQUID_NET_WORTH_FLOOR
    )
    min_liquid_net_worth_usd: NonNegativeFloat
    sale_amount_usd: PositiveFloat


PrivateEquitySaleRule = Annotated[
    FixedAmountPrivateEquitySaleRule | LiquidNetWorthFloorPrivateEquitySaleRule, Field(discriminator="sale_rule_type")
]


class PrivateEquitySalePolicy(_PolicyBase):
    """Sell private equity when market sale opportunities satisfy the policy rule."""

    policy_type: Literal[PolicyType.PRIVATE_EQUITY_SALE] = PolicyType.PRIVATE_EQUITY_SALE
    proceeds_destination: PrivateEquitySaleProceedsDestination = PrivateEquitySaleProceedsDestination.CASH
    sale_rule: PrivateEquitySaleRule


class FixedLiquidityReserveRule(ApiModel):
    reserve_rule_type: Literal[LiquidityReserveRuleType.FIXED] = LiquidityReserveRuleType.FIXED
    min_reserve_usd: NonNegativeFloat = 0.0


class ProjectedDeficitsLiquidityReserveRule(ApiModel):
    reserve_rule_type: Literal[LiquidityReserveRuleType.PROJECTED_DEFICITS] = (
        LiquidityReserveRuleType.PROJECTED_DEFICITS
    )
    min_reserve_usd: NonNegativeFloat = 0.0
    forward_months: NonNegativeInt = 0


LiquidityReserveRule = Annotated[
    FixedLiquidityReserveRule | ProjectedDeficitsLiquidityReserveRule, Field(discriminator="reserve_rule_type")
]


class LiquidityReservePolicy(_PolicyBase):
    """Defines an agent's minimum-liquid-reserve target."""

    policy_type: Literal[PolicyType.LIQUIDITY_RESERVE] = PolicyType.LIQUIDITY_RESERVE
    reserve_rule: LiquidityReserveRule = Field(default_factory=FixedLiquidityReserveRule)


class PortfolioTargetRebalancePolicy(_PolicyBase):
    policy_type: Literal[PolicyType.PORTFOLIO_TARGET_REBALANCE] = PolicyType.PORTFOLIO_TARGET_REBALANCE


class PartnerEquityAccrualPolicy(_PolicyBase):
    """A partner contributes monthly toward a property the primary owner holds, accruing
    ownership share in proportion to principal credit."""

    policy_type: Literal[PolicyType.PARTNER_EQUITY_ACCRUAL] = PolicyType.PARTNER_EQUITY_ACCRUAL
    property_id: PropertyId | None = None
    base_monthly_payment_usd: NonNegativeFloat = 0.0
    grow_with_inflation: bool = True
    payment_growth_annual_pct: NonNegativeFloat = 0.0
    occupied_months: NonNegativeInt | None = None
    freeze_ownership_after_month: NonNegativeInt | None = None


class ManualEventSchedulePolicy(_PolicyBase):
    policy_type: Literal[PolicyType.MANUAL_EVENT_SCHEDULE] = PolicyType.MANUAL_EVENT_SCHEDULE


class MonthlySpendPolicy(_PolicyBase):
    """Agent spends a fixed amount each month from checking (e.g. living expenses).

    When `inflation_adjusted` is true, the spend grows with the market
    bundle's inflation multipliers."""

    policy_type: Literal[PolicyType.MONTHLY_SPEND] = PolicyType.MONTHLY_SPEND
    monthly_spend_usd: NonNegativeFloat
    inflation_adjusted: bool = False


Policy = Annotated[
    CheckingFloorSellPublicStockPolicy
    | PrivateEquitySalePolicy
    | PortfolioTargetRebalancePolicy
    | PartnerEquityAccrualPolicy
    | ManualEventSchedulePolicy
    | LiquidityReservePolicy
    | MonthlySpendPolicy,
    Field(discriminator="policy_type"),
]


class _SimulationActionBase(ApiModel):
    rollout_index: NonNegativeInt
    month_index: NonNegativeInt
    actor_id: str
    policy_id: str


class SellSp500Action(_SimulationActionBase):
    action_type: Literal[ActionType.SELL_SP500] = ActionType.SELL_SP500
    amount_usd: float
    after_tax_proceeds_usd: float
    basis_usd: float
    gain_usd: float
    tax_usd: float
    shortfall_usd: float


class SellPrivateEquityAction(_SimulationActionBase):
    action_type: Literal[ActionType.SELL_PRIVATE_EQUITY] = ActionType.SELL_PRIVATE_EQUITY
    event_id: str | None = None
    event_type: EventType | None = None
    amount_usd: float
    after_tax_proceeds_usd: float
    basis_usd: float
    taxable_gain_usd: float
    estimated_tax_usd: float
    units_sold: float
    sold_fraction: float
    proceeds_destination: AccountType | AssetType


class SettlePropertySaleAction(_SimulationActionBase):
    action_type: Literal[ActionType.SETTLE_PROPERTY_SALE] = ActionType.SETTLE_PROPERTY_SALE
    event_id: str
    event_type: Literal[EventType.PROPERTY_SALE] = EventType.PROPERTY_SALE
    property_id: PropertyId
    gross_sale_usd: float
    selling_cost_usd: float
    debt_payoff_usd: float
    adjusted_basis_usd: float
    realized_gain_usd: float
    depreciation_recapture_usd: float
    capital_gain_usd: float
    capital_gain_exclusion_usd: float
    taxable_capital_gain_usd: float
    taxable_gain_usd: float
    tax_usd: float
    net_proceeds_usd: float
    proceeds_destination: AccountType = AccountType.CHECKING


class TransferPartnerContributionAction(_SimulationActionBase):
    action_type: Literal[ActionType.TRANSFER_PARTNER_CONTRIBUTION] = ActionType.TRANSFER_PARTNER_CONTRIBUTION
    recipient_actor_id: str
    amount_usd: float
    applied_to_house_costs_usd: float
    unallocated_amount_usd: float


class PayMortgageAction(_SimulationActionBase):
    action_type: Literal[ActionType.PAY_MORTGAGE] = ActionType.PAY_MORTGAGE
    mortgage_payment_usd: float
    mortgage_interest_usd: float
    mortgage_principal_usd: float
    mortgage_balance_after_usd: float


class AccruePartnerEquityAction(_SimulationActionBase):
    action_type: Literal[ActionType.ACCRUE_PARTNER_EQUITY] = ActionType.ACCRUE_PARTNER_EQUITY
    beneficiary_actor_id: str
    property_id: PropertyId
    house_costs_usd: float
    cash_transfer_used_for_house_costs_usd: float
    mortgage_principal_usd: float
    principal_credit_usd: float
    house_cost_share: float
    ownership_pct_after: float
    home_equity_claim_usd_after: float


class MonthlySpendAction(_SimulationActionBase):
    action_type: Literal[ActionType.MONTHLY_SPEND] = ActionType.MONTHLY_SPEND
    amount_usd: float
    inflation_multiplier: float = 1.0


SimulationAction = Annotated[
    SellSp500Action
    | SellPrivateEquityAction
    | SettlePropertySaleAction
    | TransferPartnerContributionAction
    | PayMortgageAction
    | AccruePartnerEquityAction
    | MonthlySpendAction,
    Field(discriminator="action_type"),
]


class _SimulationPolicyDecisionBase(ApiModel):
    rollout_index: NonNegativeInt
    month_index: NonNegativeInt
    actor_id: str
    policy_id: str


class MonthlySpendDecision(_SimulationPolicyDecisionBase):
    decision_type: Literal[PolicyDecisionType.MONTHLY_SPEND] = PolicyDecisionType.MONTHLY_SPEND
    amount_usd: float
    inflation_multiplier: float = 1.0


class SellPublicStockDecision(_SimulationPolicyDecisionBase):
    decision_type: Literal[PolicyDecisionType.SELL_PUBLIC_STOCK] = PolicyDecisionType.SELL_PUBLIC_STOCK
    asset_type: Literal[AssetType.GENERIC_SP500_STOCK] = AssetType.GENERIC_SP500_STOCK
    requested_amount_usd: float
    current_cash_usd: float
    target_cash_floor_usd: float | None = None


class PrivateEquitySaleDecision(_SimulationPolicyDecisionBase):
    decision_type: Literal[PolicyDecisionType.PRIVATE_EQUITY_SALE] = PolicyDecisionType.PRIVATE_EQUITY_SALE
    decision_reason: PrivateEquitySaleDecisionReason
    requested_amount_usd: float
    sale_opportunity_value_usd: float
    private_equity_value_before_sale_usd: float
    liquid_net_worth_usd: float
    target_liquid_net_worth_floor_usd: float | None = None
    proceeds_destination: AccountType | AssetType


class PartnerContributionDecision(_SimulationPolicyDecisionBase):
    decision_type: Literal[PolicyDecisionType.PARTNER_CONTRIBUTION] = PolicyDecisionType.PARTNER_CONTRIBUTION
    recipient_actor_id: str
    requested_amount_usd: float
    property_id: PropertyId


SimulationPolicyDecision = Annotated[
    MonthlySpendDecision | SellPublicStockDecision | PrivateEquitySaleDecision | PartnerContributionDecision,
    Field(discriminator="decision_type"),
]


class _SimulationMarketObservationBase(ApiModel):
    rollout_index: NonNegativeInt
    month_index: NonNegativeInt


class MarketPathObservation(_SimulationMarketObservationBase):
    observation_type: Literal[MarketObservationType.MARKET_PATH] = MarketObservationType.MARKET_PATH
    location_id: str | None = None
    inflation_multiplier: float
    sp500_multiplier: float
    private_equity_value_multiplier: float
    home_value_multiplier: float
    rent_multiplier: float
    mortgage_30y_rate_pct: float
    private_equity_sale_opportunity_event: bool


class PrivateEquitySaleOpportunityObservation(_SimulationMarketObservationBase):
    observation_type: Literal[MarketObservationType.PRIVATE_EQUITY_SALE_OPPORTUNITY] = (
        MarketObservationType.PRIVATE_EQUITY_SALE_OPPORTUNITY
    )
    sale_opportunity_value_usd: float
    private_equity_value_before_sale_usd: float


SimulationMarketObservation = Annotated[
    MarketPathObservation | PrivateEquitySaleOpportunityObservation, Field(discriminator="observation_type")
]


class _SimulationLedgerBase(ApiModel):
    rollout_index: NonNegativeInt
    month_index: NonNegativeInt
    actor_id: str
    policy_id: str | None = None
    event_id: str | None = None
    account_id: str | None = None
    asset_id: str | None = None
    liability_id: str | None = None
    property_id: PropertyId | None = None
    domain: str
    category: str
    amount_usd: float
    counterparty_actor_id: str | None = None


class SimulationLedgerEntry(_SimulationLedgerBase):
    """A realized economic movement for one rollout/month."""


class SimulationBalanceSnapshot(_SimulationLedgerBase):
    """A point-in-time state value for one rollout/month."""


class _SimulationAccountingDetailBase(ApiModel):
    rollout_index: NonNegativeInt
    month_index: NonNegativeInt
    actor_id: str
    policy_id: str | None = None
    event_id: str | None = None
    property_id: PropertyId | None = None


class PropertySaleBasisGainDetail(_SimulationAccountingDetailBase):
    detail_type: Literal[AccountingDetailType.PROPERTY_SALE_BASIS_GAIN] = AccountingDetailType.PROPERTY_SALE_BASIS_GAIN
    gross_sale_usd: float
    selling_cost_usd: float
    debt_payoff_usd: float
    adjusted_basis_usd: float
    realized_gain_usd: float
    depreciation_recapture_usd: float
    capital_gain_usd: float
    capital_gain_exclusion_usd: float
    taxable_capital_gain_usd: float
    taxable_gain_usd: float


class TaxPaymentAllocationDetail(_SimulationAccountingDetailBase):
    detail_type: Literal[AccountingDetailType.TAX_PAYMENT_ALLOCATION] = AccountingDetailType.TAX_PAYMENT_ALLOCATION
    tax_year_index: NonNegativeInt
    payment_timing: TaxPaymentTiming = TaxPaymentTiming.ALLOCATED_TO_SOURCE_MONTH
    federal_income_tax_usd: float
    california_income_tax_usd: float
    total_income_tax_usd: float
    property_sale_tax_usd: float
    generic_sp500_sale_tax_usd: float
    private_equity_sale_tax_usd: float
    property_depreciation_recapture_usd: float
    taxable_property_capital_gain_usd: float
    generic_sp500_taxable_gain_usd: float
    private_equity_taxable_gain_usd: float
    total_taxable_income_usd: float


SimulationAccountingDetail = Annotated[
    PropertySaleBasisGainDetail | TaxPaymentAllocationDetail, Field(discriminator="detail_type")
]


class ReportSpec(ApiModel):
    metrics: tuple[ReportMetric, ...] = (
        ReportMetric.NET_WORTH,
        ReportMetric.LIQUID_NET_WORTH,
        ReportMetric.HOME_EQUITY,
    )
    percentiles: tuple[float, ...] = (5, 25, 50, 75, 95)
    include_monthly_columns: bool = True
    include_sample_paths: Literal[False] = False

    @model_validator(mode="after")
    def _percentiles_in_range(self) -> ReportSpec:
        out_of_range = [value for value in self.percentiles if value < 0 or value > 100]
        if out_of_range:
            raise ValueError(f"percentiles must be in [0, 100]: {out_of_range}")
        return self


class TaxProfile(ApiModel):
    filing_status: TaxFilingStatus = TaxFilingStatus.SINGLE
    annual_ordinary_income_usd: NonNegativeFloat = 0
    federal_standard_deduction_usd: NonNegativeFloat | None = None
    california_standard_deduction_usd: NonNegativeFloat | None = None
    marginal_tax_rate: Percentage = 40
    cap_gains_rate: Percentage = 30
    cap_gains_exclusion_usd: NonNegativeFloat = 250_000


class TransactionCosts(ApiModel):
    closing_cost_buy_pct: Percentage = 2.5
    closing_cost_sell_pct: Percentage = 6.5


class PropertyAssumptions(ApiModel):
    insurance_annual_usd: NonNegativeFloat = 1800
    maintenance_pct: Percentage = 1
    depreciable_basis_pct: Percentage = 80


class PropertySelection(ApiModel):
    property_id: PropertyId | None = None
    location_id: str | None = None
    purchase_price_usd: NonNegativeFloat | None = None
    tax_regime: TaxRegime | None = None
    local_regulation: LocalRegulation | None = None


class Financing(ApiModel):
    financing_mode: FinancingMode = FinancingMode.FIXED_30
    down_payment_pct: NonNegativeFloat = 25
    mortgage_rate_pct: NonNegativeFloat | None = None
    mortgage_term_years: PositiveInt | None = None
    credit_score: NonNegativeInt | None = None
    loan_amount_usd: NonNegativeFloat | None = None


class OccupancyPlan(ApiModel):
    occupancy_mode: OccupancyMode = OccupancyMode.OWNER_LIVES_IN_PROPERTY
    owner_residence_property_id: PropertyId | None = None
    start_month: NonNegativeInt = 0
    end_month: NonNegativeInt | None = None

    @model_validator(mode="after")
    def _end_after_start(self) -> OccupancyPlan:
        if self.end_month is not None and self.end_month < self.start_month:
            raise ValueError("end_month must be greater than or equal to start_month")
        return self


class _RentalPlanBase(ApiModel):
    start_month: NonNegativeInt | None = None
    end_month: NonNegativeInt | None = None
    monthly_rent_usd: NonNegativeFloat | None = None
    rooms_rented: NonNegativeInt = 0
    room_rent_monthly_usd: NonNegativeFloat | None = None
    vacancy_pct: NonNegativeFloat = 0
    room_vacancy_pct: NonNegativeFloat = 0
    management_fee_pct: NonNegativeFloat = 0
    leasing_fee_pct: NonNegativeFloat = 0

    @model_validator(mode="after")
    def _end_after_start(self) -> _RentalPlanBase:
        if self.start_month is not None and self.end_month is not None and self.end_month < self.start_month:
            raise ValueError("end_month must be greater than or equal to start_month")
        return self


class NotRentedRentalPlan(_RentalPlanBase):
    rental_mode: Literal[RentalMode.NOT_RENTED] = RentalMode.NOT_RENTED


class WholePropertyRentalPlan(_RentalPlanBase):
    rental_mode: Literal[RentalMode.RENT_WHOLE_PROPERTY] = RentalMode.RENT_WHOLE_PROPERTY
    monthly_rent_usd: NonNegativeFloat


class TransitionWholePropertyRentalPlan(_RentalPlanBase):
    rental_mode: Literal[RentalMode.TRANSITION_TO_WHOLE_PROPERTY_RENTAL] = (
        RentalMode.TRANSITION_TO_WHOLE_PROPERTY_RENTAL
    )
    monthly_rent_usd: NonNegativeFloat


class RoomRentalPlan(_RentalPlanBase):
    rental_mode: Literal[RentalMode.RENT_ROOMS_WHILE_OWNER_LIVES_THERE] = RentalMode.RENT_ROOMS_WHILE_OWNER_LIVES_THERE
    room_rent_monthly_usd: NonNegativeFloat


RentalPlan = Annotated[
    NotRentedRentalPlan | WholePropertyRentalPlan | TransitionWholePropertyRentalPlan | RoomRentalPlan,
    Field(discriminator="rental_mode"),
]


class AccountBalance(ApiModel):
    account_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_\-]*$")
    account_type: AccountType
    owner_actor_id: str
    balance_usd: float


class _AssetPositionBase(ApiModel):
    asset_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_\-]*$")
    owner_actor_id: str
    value_usd: float


class CashAssetPosition(_AssetPositionBase):
    asset_type: Literal[AssetType.CASH] = AssetType.CASH


class GenericSp500StockPosition(_AssetPositionBase):
    asset_type: Literal[AssetType.GENERIC_SP500_STOCK] = AssetType.GENERIC_SP500_STOCK
    cost_basis_usd: float | None = None


class PrivateEquityPosition(_AssetPositionBase):
    asset_type: Literal[AssetType.PRIVATE_EQUITY] = AssetType.PRIVATE_EQUITY
    units: NonNegativeFloat | None = None
    cost_basis_usd: float | None = None


class RealEstateAssetPosition(_AssetPositionBase):
    asset_type: Literal[AssetType.REAL_ESTATE] = AssetType.REAL_ESTATE
    property_id: PropertyId


class DeferredTaxAssetPosition(_AssetPositionBase):
    asset_type: Literal[AssetType.DEFERRED_TAX_ASSET] = AssetType.DEFERRED_TAX_ASSET


AssetPosition = Annotated[
    CashAssetPosition
    | GenericSp500StockPosition
    | PrivateEquityPosition
    | RealEstateAssetPosition
    | DeferredTaxAssetPosition,
    Field(discriminator="asset_type"),
]


class _LiabilityBase(ApiModel):
    liability_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_\-]*$")
    owner_actor_id: str
    balance_usd: float


class MortgageLiability(_LiabilityBase):
    liability_type: Literal[LiabilityType.MORTGAGE] = LiabilityType.MORTGAGE
    rate_pct: NonNegativeFloat | None = None
    property_id: PropertyId | None = None


class TaxLiability(_LiabilityBase):
    liability_type: Literal[LiabilityType.TAX_LIABILITY] = LiabilityType.TAX_LIABILITY


class ActorEquityClaimLiability(_LiabilityBase):
    liability_type: Literal[LiabilityType.ACTOR_EQUITY_CLAIM] = LiabilityType.ACTOR_EQUITY_CLAIM
    property_id: PropertyId | None = None


LiabilityBalance = Annotated[
    MortgageLiability | TaxLiability | ActorEquityClaimLiability, Field(discriminator="liability_type")
]


class InitialBalanceSheet(ApiModel):
    accounts: tuple[AccountBalance, ...] = ()
    assets: tuple[AssetPosition, ...] = ()
    liabilities: tuple[LiabilityBalance, ...] = ()


class MarketRequest(ApiModel):
    market_model_id: str = "current_market_model"
    rollout_count: PositiveInt = 128
    horizon_months: PositiveInt = 360
    seed: int


class Scenario(ApiModel):
    scenario_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_\-]*$")
    label: str
    enabled: bool = True
    color: str | None = None
    actors: tuple[Actor, ...] = Field(min_length=1)
    events: tuple[Event, ...] = ()
    policies: tuple[Policy, ...] = ()
    property_selection: PropertySelection = Field(default_factory=PropertySelection)
    financing: Financing = Field(default_factory=Financing)
    occupancy_plan: OccupancyPlan = Field(default_factory=OccupancyPlan)
    rental_plan: RentalPlan = Field(default_factory=NotRentedRentalPlan)
    tax_profile: TaxProfile = Field(default_factory=TaxProfile)
    transaction_costs: TransactionCosts = Field(default_factory=TransactionCosts)
    property_assumptions: PropertyAssumptions = Field(default_factory=PropertyAssumptions)
    initial_balance_sheet: InitialBalanceSheet = Field(default_factory=InitialBalanceSheet)
    tax_regimes: tuple[TaxRegime, ...] = ()

    @property
    def location_id(self) -> str | None:
        return self.property_selection.location_id


class ScenarioSet(ApiModel):
    scenario_set_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_\-]*$")
    title: str
    market_request: MarketRequest
    report_spec: ReportSpec = Field(default_factory=ReportSpec)
    scenarios: tuple[Scenario, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _scenario_ids_are_unique(self) -> ScenarioSet:
        scenario_ids = [scenario.scenario_id for scenario in self.scenarios]
        duplicate_ids = sorted({scenario_id for scenario_id in scenario_ids if scenario_ids.count(scenario_id) > 1})
        if duplicate_ids:
            raise ValueError(f"scenario ids must be unique: {duplicate_ids}")
        return self


class ScenarioAcceptedSummary(ApiModel):
    enabled: bool
    property_id: PropertyId | None = None
    location_id: str | None = None
    actor_count: NonNegativeInt
    event_count: NonNegativeInt
    policy_count: NonNegativeInt


class ExogenousPathIdentity(ApiModel):
    rollout_index: NonNegativeInt
    path_set_id: str
    exogenous_path_id: str
    market_model_id: str
    seed: int
    event_stream_ids: tuple[str, ...] = ()


class ProjectionTrajectoryIdentity(ApiModel):
    scenario_id: str
    rollout_index: NonNegativeInt
    path_set_id: str
    exogenous_path_id: str
    projection_trajectory_id: str


class RolloutStatus(ApiModel):
    rollout_index: NonNegativeInt
    status: RolloutStatusType
    min_cash_usd: float
    first_negative_cash_month_index: NonNegativeInt | None = None


class RolloutStatusSummary(ApiModel):
    total_rollout_count: NonNegativeInt = 0
    counts_by_status: dict[RolloutStatusType, NonNegativeInt] = Field(default_factory=dict)

    @classmethod
    def from_statuses(cls, statuses: tuple[RolloutStatus, ...]) -> RolloutStatusSummary:
        status_counts = Counter(status.status for status in statuses)
        counts = {status: status_counts[status] for status in RolloutStatusType} if statuses else {}
        return cls(total_rollout_count=len(statuses), counts_by_status=counts)


class ScenarioResult(ApiModel):
    scenario_id: str
    scenario_label: str
    summary: ScenarioAcceptedSummary
    projection_trajectories: tuple[ProjectionTrajectoryIdentity, ...] = ()
    rollout_statuses: tuple[RolloutStatus, ...] = ()
    rollout_status_summary: RolloutStatusSummary = Field(default_factory=RolloutStatusSummary)
    metric_fan_columns: dict[str, ColumnarTable] = Field(default_factory=dict)
    monthly_columns: ColumnarTable | None = None
    terminal_columns: ColumnarTable | None = None
    actions: tuple[SimulationAction, ...] = ()
    policy_decisions: tuple[SimulationPolicyDecision, ...] = ()
    market_observations: tuple[SimulationMarketObservation, ...] = ()
    ledger_entries: tuple[SimulationLedgerEntry, ...] = ()
    balance_snapshots: tuple[SimulationBalanceSnapshot, ...] = ()
    accounting_details: tuple[SimulationAccountingDetail, ...] = ()
    warnings: tuple[str, ...] = ()


class ScenarioSetRunResponse(ApiModel):
    scenario_set_id: str
    request: ScenarioSet
    market_request: MarketRequest
    report_spec: ReportSpec
    market_metadata: dict[str, Any] | None = None
    exogenous_paths: tuple[ExogenousPathIdentity, ...] = ()
    scenario_results: tuple[ScenarioResult, ...]
    warnings: tuple[str, ...] = ()
