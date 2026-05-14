from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, NonNegativeFloat, model_validator

# ---------------------------------------------------------------------------
# Base configurations.
# ---------------------------------------------------------------------------
#
# Shared simulator models use ordinary snake_case field names. App-specific
# HTTP boundaries may adapt those names for browser compatibility, but that
# conversion is not a core schema concern.


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class InternalModel(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LenientSourceModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class OpenSchemaModel(BaseModel):
    """Frozen, accepts unknown fields. Used for shapes where the keys are
    dynamic or evolve faster than the schema (fan-row percentile keys,
    percentile bags, etc.)."""

    model_config = ConfigDict(extra="allow", frozen=True)


Percentage = Annotated[NonNegativeFloat, Field(le=100)]


# ---------------------------------------------------------------------------
# Request shapes (boundary with the browser).
# ---------------------------------------------------------------------------


class PropertyRequest(InternalModel):
    id: str
    price_usd: float
    beds: float
    hoa_monthly_usd: float = 0
    rent_zestimate_usd: float | None = None
    tax_rate_override: float | None = None


class Property(InternalModel):
    """Full listing record. The frontend renders all of these fields; the
    simulator only needs the subset on `PropertyRequest`."""

    id: str
    address: str
    neighborhood: str
    type: str
    price_usd: float
    zestimate_usd: float | None = None
    rent_zestimate_usd: float | None = None
    rent_source: str | None = None
    beds: float
    baths: float
    sqft: float
    year_built: int
    hoa_monthly_usd: float = 0
    annual_tax_on_list_usd: float | None = None
    days_on_market: int | None = None
    listing_status: str | None = None
    source_url: str
    image_url: str
    notes: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    tax_rate_override: float | None = None

    def to_request(self) -> PropertyRequest:
        return PropertyRequest(
            id=self.id,
            price_usd=self.price_usd,
            beds=self.beds,
            hoa_monthly_usd=self.hoa_monthly_usd,
            rent_zestimate_usd=self.rent_zestimate_usd,
            tax_rate_override=self.tax_rate_override,
        )


class KnobsConfig(ApiModel):
    down_payment_pct: float
    credit_score: float
    custom_mortgage_rate: float
    custom_mortgage_term_years: float
    starting_portfolio_usd: float
    custom_counterfactual_rent_monthly_usd: float
    counterfactual_rent_growth: float
    hold_years: float
    appreciation_rate: float
    sp500_rate: float
    maintenance_pct: float
    owner_occupancy_years: float
    marginal_tax_rate: float
    cap_gains_rate: float
    inflation: float
    vacancy_pct: float
    mgmt_pct: float
    leasing_fee_pct: float
    rooms_rented_while_living: float
    room_rent_monthly_usd: float
    room_vacancy_pct: float
    portfolio_liquidation_tax_pct: float
    insurance_annual_usd: float
    closing_cost_buy_pct: float
    closing_cost_sell_pct: float
    cap_gains_exclusion_usd: float
    depreciable_basis_pct: float
    financing_mode: Literal["cash", "fixed_30", "fixed_15", "custom"]
    occupancy_type: Literal["primary_residence", "second_home", "investment"]
    rent_counterfactual_mode: Literal["custom", "selected_property"]


class ScenarioKnobs(KnobsConfig):
    """`KnobsConfig` augmented with per-rollout path overrides.

    `simulate_arrangement` reads these (when present) to drive each scenario
    along the rollout's drawn macro path; absent / `None` fields fall back to
    `KnobsConfig`'s deterministic single-rate growth. Analysis-only callers
    pass a `ScenarioKnobs` with every override unset (use
    `ScenarioKnobs.from_knobs(knobs)`)."""

    home_value_multipliers: list[float] | None = None
    sale_home_value_multipliers: list[float] | None = None
    portfolio_multipliers: list[float] | None = None
    rent_multipliers: list[float] | None = None
    counterfactual_rent_multipliers: list[float] | None = None
    expense_inflation_multipliers: list[float] | None = None

    @classmethod
    def from_knobs(cls, knobs: KnobsConfig) -> ScenarioKnobs:
        return cls.model_validate(knobs.model_dump())


# ---------------------------------------------------------------------------
# Private-equity liquidity / joint rollout shapes (round-trip with browser).
# ---------------------------------------------------------------------------


class PrivateEquityEvent(InternalModel):
    month_index: int
    # TODO: only "tender" is currently emitted by rollouts. "acquisition"
    # remains in the literal as a placeholder for the eventual acquisition
    # regime; "ipo" / "public_mark" were dropped when IPO modeling was
    # removed and should come back together with a real public-equity
    # regime.
    event_type: Literal["tender", "acquisition"]
    price_usd_per_unit: float


class PrivateEquityPath(InternalModel):
    current_price_usd: float
    price_path: list[float]
    events: list[PrivateEquityEvent]


class MarketMultipliers(InternalModel):
    """The base multiplier paths every macro rollout produces.
    Reused by `JointRolloutPath` (rollout input) and `MarketPath`
    (post-simulation output with derived CAGRs). Location-specific
    home/rent factors ride in the factor maps below."""

    home_value_multipliers: list[float]
    sale_home_value_multipliers: list[float]
    portfolio_multipliers: list[float]
    rent_multipliers: list[float]
    expense_inflation_multipliers: list[float]
    home_value_factor_multipliers: dict[str, list[float]] = Field(default_factory=dict)
    rent_factor_multipliers: dict[str, list[float]] = Field(default_factory=dict)
    mortgage30_rate_path: list[float] = Field(default_factory=list)


class JointRolloutPath(MarketMultipliers):
    private_equity_path: PrivateEquityPath


# ---------------------------------------------------------------------------
# Financing + amortization (simulation outputs).
# ---------------------------------------------------------------------------


class Financing(InternalModel):
    financing_mode: str
    financing_label: str
    occupancy_type: str
    occupancy_label: str
    credit_score: float
    down_payment_pct: float
    loan_to_value_pct: float
    term_years: float
    rate_pct: float
    base_rate_pct: float | None
    credit_spread_pct: float | None
    occupancy_spread_pct: float | None
    ltv_spread_pct: float | None
    is_custom: bool
    is_cash: bool


class AmortizationMonth(InternalModel):
    month_index: int
    payment_usd: float
    interest_usd: float
    principal_usd: float
    balance_usd: float
    cumulative_interest_usd: float
    cumulative_principal_usd: float


class AmortizationYear(InternalModel):
    year: int
    balance_usd: float
    cum_interest_usd: float
    cum_principal_usd: float
    year_interest_usd: float
    year_principal_usd: float


class AmortizationSchedule(InternalModel):
    payment_usd: float
    monthly: list[AmortizationMonth]
    yearly: list[AmortizationYear]


# ---------------------------------------------------------------------------
# House simulation (per-property, per-knobs run).
# ---------------------------------------------------------------------------


LedgerActor = str
LedgerDomain = Literal["cash", "equity"]


class LedgerRow(InternalModel):
    month_index: int
    year_index: int
    actor: LedgerActor
    domain: LedgerDomain
    category: str
    amount_usd: float


class MonthRow(InternalModel):
    month_index: int
    year_index: int
    phase: Literal["occupied", "rental"]
    home_value_usd: float
    mortgage_balance_usd: float
    mortgage_interest_usd: float
    mortgage_principal_usd: float
    property_tax_usd: float
    insurance_usd: float
    hoa_usd: float
    maintenance_usd: float
    tenant_rent_usd: float
    rooms_rented: int
    room_rent_usd: float
    tax_shield_usd: float
    active_rental_share: float
    monthly_depreciation_usd: float
    cumulative_depreciation_usd: float
    suspended_passive_losses_usd: float
    rental_taxable_income_usd: float
    passive_loss_offset_used_usd: float
    rental_income_tax_usd: float
    owner_equity_ledger_usd: float


class SaleOutcome(InternalModel):
    selling_costs_usd: float
    gross_equity_usd: float
    adjusted_basis_usd: float
    total_gain_usd: float
    capital_gain_usd: float
    recapture_gain_usd: float
    exclusion_usd: float
    taxable_gain_usd: float
    recapture_tax_usd: float
    capital_gains_tax_usd: float
    passive_loss_release_benefit_usd: float
    suspended_passive_losses_usd: float
    cg_tax_usd: float
    net_sale_proceeds_usd: float


class SimulationTerminal(InternalModel):
    final_month: MonthRow
    final_home_value_usd: float
    final_loan_balance_usd: float
    owner_equity_ledger_usd: float
    sale: SaleOutcome
    owner_net_proceeds_usd: float


class SimulationResult(InternalModel):
    # Property + scenario knobs the simulator was driven with. Carrying the
    # typed models here lets `analysis.py` (project_summary, project_yearly_ledger,
    # …) read fields without re-deriving request state.
    property: PropertyRequest
    knobs: ScenarioKnobs
    purchase_price_usd: float
    down_payment_usd: float
    closing_buy_usd: float
    portfolio_liquidation_tax_usd: float
    initial_outlay_usd: float
    loan_amount_usd: float
    financing: Financing
    tax_rate: float
    initial_annual_tax_usd: float
    hold_months: int
    occupied_months: int
    depreciable_basis_usd: float
    amortization: AmortizationSchedule
    months: list[MonthRow]
    ledger: list[LedgerRow]
    validations: list[str]
    terminal: SimulationTerminal


# ---------------------------------------------------------------------------
# Projections / sale path (consumed by browser charts).
# ---------------------------------------------------------------------------


class MonthlySalePathRow(InternalModel):
    month_index: int
    rent_path_usd: float
    buy_liquid_usd: float
    buy_locked_equity_usd: float
    buy_path_usd: float
    sp500_usd: float
    own_usd: float
    delta_usd: float
    project_buy_liquid_usd: float
    project_own_usd: float
    project_delta_usd: float
    net_sale_proceeds_usd: float
    gross_equity_usd: float
    owner_sale_claim_usd: float
    owner_equity_ledger_usd: float


# ---------------------------------------------------------------------------
# Personal-wealth / private-equity policy outputs.
# ---------------------------------------------------------------------------


class PrivateEquitySale(InternalModel):
    month_index: int
    event_type: str
    units: float
    price_usd_per_unit: float
    after_tax_proceeds_usd: float


class PrivateEquityLiquidityRow(InternalModel):
    month_index: int
    base_liquid_usd: float
    liquid_private_equity_proceeds_usd: float
    liquid_net_worth_contribution_usd: float
    private_equity_after_tax_mark_value_usd: float
    private_equity_units_remaining: float
    private_equity_units_sold: float
    liquidity_shortfall: bool
    sales: list[PrivateEquitySale]


class PrivateEquityLiquidityPath(InternalModel):
    rows: list[PrivateEquityLiquidityRow]
    sales: list[PrivateEquitySale]
    terminal: PrivateEquityLiquidityRow
    had_liquidity_shortfall: bool
    had_eligible_sale: bool


class NetWorthRow(MonthlySalePathRow):
    """Adds personal-wealth columns on top of the per-month sale path:
    aggregated net-worth views, the private-equity mark-to-market value, and
    the liquidity-shortfall flag."""

    liquid_net_worth_usd: float
    economic_net_worth_usd: float
    private_equity_liquid_value_usd: float
    private_equity_event_pv_usd: float
    private_equity_units_remaining: float
    liquidity_shortfall: bool


class _PolicyActionBase(InternalModel):
    month_index: int


class PolicyActionTrade(_PolicyActionBase):
    """SP500 trade triggered by housing cash-flow shortfall / surplus."""

    action_type: Literal["sold_sp500", "bought_sp500"]
    amount_usd: int
    reason: str


class PolicyActionRental(_PolicyActionBase):
    """Property switches from owner-occupied to rented (or starts rented)."""

    action_type: Literal["moved_out_and_rented_property", "rented_property_out_from_start"]


class PolicyActionPrivateEquity(_PolicyActionBase):
    """Private-equity tender / acquisition / IPO sale through the guardrail policy."""

    action_type: Literal["sold_privateEquity"]
    event_type: str
    units: float
    price_usd_per_unit: float
    after_tax_proceeds_usd: int
    reason: str


PolicyAction = Annotated[
    PolicyActionTrade | PolicyActionRental | PolicyActionPrivateEquity, Field(discriminator="action_type")
]


# ---------------------------------------------------------------------------
# Stochastic outcome view (what the browser actually renders).
# ---------------------------------------------------------------------------


class ColumnarTable(InternalModel):
    """Rectangular, JSON-safe table payload.

    Each entry in `columns` is one complete column with `row_count` values.
    This is the HTTP shape for array-like simulator outputs; UI libraries that
    still need row objects can transpose it at the frontend boundary.
    """

    row_count: int
    columns: dict[str, list[Any]]

    @model_validator(mode="after")
    def _columns_match_row_count(self) -> ColumnarTable:
        if self.row_count < 0:
            raise ValueError("row_count must be non-negative")
        lengths = {name: len(values) for name, values in self.columns.items()}
        mismatched = {name: length for name, length in lengths.items() if length != self.row_count}
        if mismatched:
            raise ValueError(f"column lengths must equal row_count={self.row_count}: {mismatched}")
        return self


class Percentiles(OpenSchemaModel):
    pass


class HistogramBucket(InternalModel):
    from_value: float
    to_value: float
    mid: float
    count: int
    share: float
    percentile_low: float
    percentile_high: float


class SamplePathColumns(InternalModel):
    delta_path_columns: ColumnarTable
    economic_net_worth_path_columns: ColumnarTable
    appreciation_path_columns: ColumnarTable
    policy_actions: list[PolicyAction]


class ModelRunMetadata(InternalModel):
    fitted_with: str
    policy: dict[str, Any]


class MarketPath(MarketMultipliers):
    terminal_home_annual_cagr_pct: float
    terminal_sale_annual_cagr_pct: float
    terminal_sp500_annual_cagr_pct: float
    terminal_rent_annual_cagr_pct: float
    terminal_inflation_annual_cagr_pct: float
    terminal_appreciation_pct: float
    cumulative_home_appreciation_pct: list[float]
    terminal_home_log_growth: float


class RolloutComputation(InternalModel):
    """One sampled rollout evaluated through the deterministic + personal-wealth
    pipeline. The aggregator over many runs uses these as typed records instead
    of the older `dict[str, Any]` bag.
    """

    market_path: MarketPath
    monthly_sale_path: list[MonthlySalePathRow]
    net_worth_path: list[NetWorthRow]
    private_equity_liquidity_path: PrivateEquityLiquidityPath
    private_equity_path: PrivateEquityPath
    policy_actions: list[PolicyAction]
    summary: dict[str, Any]
    sale_path: list[MonthlySalePathRow]


class StochasticOutcomeView(InternalModel):
    model_run: ModelRunMetadata
    rollouts: int
    probability_buy_wins: float
    probability_liquidity_shortfall: float
    probability_private_equity_sale: float
    terminal_economic_net_worth: Percentiles
    terminal_liquid_net_worth: Percentiles
    terminal_private_equity_event_pv: Percentiles
    terminal_private_equity_liquid_value: Percentiles
    terminal_delta: Percentiles
    terminal_annual_appreciation: Percentiles
    terminal_appreciation: Percentiles
    terminal_sp500_annual_return: Percentiles
    terminal_rent_growth: Percentiles
    rent_path_fan_columns: ColumnarTable
    buy_liquid_fan_columns: ColumnarTable
    buy_path_fan_columns: ColumnarTable
    economic_net_worth_fan_columns: ColumnarTable
    liquid_net_worth_fan_columns: ColumnarTable
    private_equity_event_pv_fan_columns: ColumnarTable
    delta_fan_columns: ColumnarTable
    appreciation_fan_columns: ColumnarTable
    delta_histogram: list[HistogramBucket]
    sample_path_columns: list[SamplePathColumns]


# ---------------------------------------------------------------------------
# HTTP request / response shapes for the FastAPI endpoints.
# ---------------------------------------------------------------------------


class RunRequest(InternalModel):
    """One combined backend call covering both the deterministic per-property
    analysis sweep and the stochastic outcome view for the focused property.
    Omit `rollout_samples` to take the backend default (also reported on
    `BootstrapResponse.default_rollout_samples`)."""

    property_id: str
    knobs: KnobsConfig
    rollout_samples: int | None = None


class RunResponse(InternalModel):
    horizon_start: str
    horizon_months: int
    evidence: dict[str, Any]
    analysis_columns: ColumnarTable
    analysis_financing: Financing
    joint_view: StochasticOutcomeView


# ---------------------------------------------------------------------------
# Source-data + Manifold fetch shapes (already existed).
# ---------------------------------------------------------------------------


class ZillowCityRegionConfig(StrictModel):
    region_name: str
    state: str = "CA"


class SourceDataConfig(StrictModel):
    fred_sp500_csv: str
    yahoo_spy_adjusted_json: str
    fred_cpi_us_csv: str
    fred_sf_rent_cpi_csv: str
    fred_sfxrsa_csv: str
    fred_fhfa_sf_oakland_berkeley_csv: str
    fred_mortgage30_csv: str
    zillow_city_zhvi_csv: str
    zillow_home_value_regions: dict[str, ZillowCityRegionConfig]
    minimum_aligned_months: int = 36


class ManifoldAnswer(LenientSourceModel):
    text: str | None = None
    probability: float | None = None


class ManifoldRawMarket(LenientSourceModel):
    id: str
    question: str | None = None
    outcome_type: str | None = None
    probability: float | None = None
    volume: float | None = None
    volume_24_hours: float | None = None
    total_liquidity: float | None = None
    unique_bettor_count: int | None = None
    last_updated_time: int | None = None
    last_bet_time: int | None = None
    close_time: int | None = None
    is_resolved: bool | None = None
    resolution: str | None = None
    creator_username: str | None = None
    creator_name: str | None = None
    slug: str | None = None
    answers: list[ManifoldAnswer] = Field(default_factory=list)


class ManifoldMarketSnapshot(StrictModel):
    id: str
    question: str | None = None
    outcome_type: str | None = None
    probability: float | None = None
    volume: float | None = None
    volume_24_hours: float | None = None
    total_liquidity: float | None = None
    unique_bettor_count: int | None = None
    last_updated_time: int | None = None
    last_bet_time: int | None = None
    close_time: int | None = None
    is_resolved: bool | None = None
    resolution: str | None = None
    url: str
    answers: list[ManifoldAnswer] = Field(default_factory=list)
