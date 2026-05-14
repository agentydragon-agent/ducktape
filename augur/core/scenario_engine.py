from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from augur.core.local_regulation import LocalRegulation, LocationId, local_regulation_for_location
from augur.core.market_bundle import (
    MarketBundle,
    MarketBundleProvider,
    SimpleMarketBundleProvider,
    sample_market_bundle_for_request,
)
from augur.core.property_depreciation import rental_active_mask
from augur.core.property_sale import empty_property_disposition_arrays, property_disposition_arrays
from augur.core.property_tax import monthly_property_tax_usd
from augur.core.scenario_set import (
    AccountType,
    AccruePartnerEquityAction,
    ActorRole,
    AssetType,
    CheckingFloorSellPublicStockPolicy,
    EventType,
    FinancingMode,
    FixedAmountPrivateEquitySaleRule,
    GenericSp500StockPosition,
    MonthlySpendAction,
    MonthlySpendPolicy,
    OccupancyMode,
    PartnerEquityAccrualPolicy,
    PayMortgageAction,
    Policy,
    PrivateEquityPosition,
    PrivateEquitySalePolicy,
    PropertyPurchaseEvent,
    RentalMode,
    Scenario,
    ScenarioAcceptedSummary,
    ScenarioResult,
    ScenarioResultStatus,
    ScenarioSet,
    ScenarioSetRunResponse,
    SellPrivateEquityAction,
    SellSp500Action,
    SimulationAction,
    TransferPartnerContributionAction,
    _PolicyBase,
)
from augur.core.schemas import ColumnarTable

MONTHS_PER_YEAR = 12


@dataclass(frozen=True)
class ScenarioRunArrays:
    scenario_id: str
    scenario_label: str
    month_index: np.ndarray
    cash_usd: np.ndarray
    generic_sp500_value_usd: np.ndarray
    generic_sp500_sale_usd: np.ndarray
    generic_sp500_sale_basis_usd: np.ndarray
    generic_sp500_sale_gain_usd: np.ndarray
    checking_floor_action_usd: np.ndarray
    checking_floor_shortfall_usd: np.ndarray
    private_equity_value_usd: np.ndarray
    private_equity_liquidity_available_value_usd: np.ndarray
    private_equity_sale_usd: np.ndarray
    private_equity_sale_basis_usd: np.ndarray
    private_equity_sale_tax_usd: np.ndarray
    private_equity_liquidity_event: np.ndarray
    property_value_usd: np.ndarray
    mortgage_balance_usd: np.ndarray
    mortgage_interest_usd: np.ndarray
    mortgage_principal_usd: np.ndarray
    mortgage_payment_usd: np.ndarray
    property_tax_usd: np.ndarray
    hoa_usd: np.ndarray
    insurance_usd: np.ndarray
    maintenance_usd: np.ndarray
    rental_gross_income_usd: np.ndarray
    rental_vacancy_loss_usd: np.ndarray
    rental_income_usd: np.ndarray
    rental_management_fee_usd: np.ndarray
    rental_leasing_fee_usd: np.ndarray
    property_carrying_cost_usd: np.ndarray
    net_property_cash_flow_usd: np.ndarray
    purchase_closing_cost_usd: np.ndarray
    sale_closing_cost_usd: np.ndarray
    property_depreciation_usd: np.ndarray
    cumulative_property_depreciation_usd: np.ndarray
    property_sale_gross_usd: np.ndarray
    property_sale_net_proceeds_usd: np.ndarray
    property_sale_tax_usd: np.ndarray
    property_sale_debt_payoff_usd: np.ndarray
    realized_property_gain_usd: np.ndarray
    taxable_property_gain_usd: np.ndarray
    depreciation_recapture_usd: np.ndarray
    net_property_sale_cash_flow_usd: np.ndarray
    home_equity_usd: np.ndarray
    owner_home_equity_claim_usd: np.ndarray
    partner_home_equity_claim_usd: np.ndarray
    partner_contribution_usd: np.ndarray
    partner_contribution_used_usd: np.ndarray
    partner_unallocated_excess_usd: np.ndarray
    partner_ownership_pct: np.ndarray
    liquid_net_worth_usd: np.ndarray
    net_worth_usd: np.ndarray
    partner_present: np.ndarray
    monthly_spend_usd: np.ndarray
    actions: tuple[SimulationAction, ...]

    @property
    def rollout_count(self) -> int:
        return int(self.cash_usd.shape[0])

    @property
    def horizon_months(self) -> int:
        return int(self.cash_usd.shape[1] - 1)

    def monthly_columns(self) -> ColumnarTable:
        row_count = self.rollout_count * (self.horizon_months + 1)
        rollout_index = np.repeat(np.arange(self.rollout_count, dtype="int64"), self.horizon_months + 1)
        month_index = np.tile(self.month_index, self.rollout_count)
        scenario_ids = [self.scenario_id] * row_count
        scenario_labels = [self.scenario_label] * row_count
        return ColumnarTable(
            row_count=row_count,
            columns={
                "scenario_id": scenario_ids,
                "scenario_label": scenario_labels,
                "rollout_index": rollout_index.tolist(),
                "month_index": month_index.tolist(),
                "cash_usd": _flat(self.cash_usd),
                "generic_sp500_value_usd": _flat(self.generic_sp500_value_usd),
                "generic_sp500_sale_usd": _flat(self.generic_sp500_sale_usd),
                "generic_sp500_sale_basis_usd": _flat(self.generic_sp500_sale_basis_usd),
                "generic_sp500_sale_gain_usd": _flat(self.generic_sp500_sale_gain_usd),
                "checking_floor_action_usd": _flat(self.checking_floor_action_usd),
                "checking_floor_shortfall_usd": _flat(self.checking_floor_shortfall_usd),
                "private_equity_value_usd": _flat(self.private_equity_value_usd),
                "private_equity_liquidity_available_value_usd": _flat(
                    self.private_equity_liquidity_available_value_usd
                ),
                "private_equity_sale_usd": _flat(self.private_equity_sale_usd),
                "private_equity_sale_basis_usd": _flat(self.private_equity_sale_basis_usd),
                "private_equity_sale_tax_usd": _flat(self.private_equity_sale_tax_usd),
                "private_equity_liquidity_event": _flat_bool(self.private_equity_liquidity_event),
                "property_value_usd": _flat(self.property_value_usd),
                "mortgage_balance_usd": _flat(self.mortgage_balance_usd),
                "mortgage_interest_usd": _flat(self.mortgage_interest_usd),
                "mortgage_principal_usd": _flat(self.mortgage_principal_usd),
                "mortgage_payment_usd": _flat(self.mortgage_payment_usd),
                "property_tax_usd": _flat(self.property_tax_usd),
                "hoa_usd": _flat(self.hoa_usd),
                "insurance_usd": _flat(self.insurance_usd),
                "maintenance_usd": _flat(self.maintenance_usd),
                "rental_gross_income_usd": _flat(self.rental_gross_income_usd),
                "rental_vacancy_loss_usd": _flat(self.rental_vacancy_loss_usd),
                "rental_income_usd": _flat(self.rental_income_usd),
                "rental_management_fee_usd": _flat(self.rental_management_fee_usd),
                "rental_leasing_fee_usd": _flat(self.rental_leasing_fee_usd),
                "property_carrying_cost_usd": _flat(self.property_carrying_cost_usd),
                "net_property_cash_flow_usd": _flat(self.net_property_cash_flow_usd),
                "purchase_closing_cost_usd": _flat(self.purchase_closing_cost_usd),
                "sale_closing_cost_usd": _flat(self.sale_closing_cost_usd),
                "property_depreciation_usd": _flat(self.property_depreciation_usd),
                "cumulative_property_depreciation_usd": _flat(self.cumulative_property_depreciation_usd),
                "property_sale_gross_usd": _flat(self.property_sale_gross_usd),
                "property_sale_net_proceeds_usd": _flat(self.property_sale_net_proceeds_usd),
                "property_sale_tax_usd": _flat(self.property_sale_tax_usd),
                "property_sale_debt_payoff_usd": _flat(self.property_sale_debt_payoff_usd),
                "realized_property_gain_usd": _flat(self.realized_property_gain_usd),
                "taxable_property_gain_usd": _flat(self.taxable_property_gain_usd),
                "depreciation_recapture_usd": _flat(self.depreciation_recapture_usd),
                "net_property_sale_cash_flow_usd": _flat(self.net_property_sale_cash_flow_usd),
                "home_equity_usd": _flat(self.home_equity_usd),
                "owner_home_equity_claim_usd": _flat(self.owner_home_equity_claim_usd),
                "partner_home_equity_claim_usd": _flat(self.partner_home_equity_claim_usd),
                "partner_contribution_usd": _flat(self.partner_contribution_usd),
                "partner_contribution_used_usd": _flat(self.partner_contribution_used_usd),
                "partner_unallocated_excess_usd": _flat(self.partner_unallocated_excess_usd),
                "partner_ownership_pct": _flat(self.partner_ownership_pct),
                "liquid_net_worth_usd": _flat(self.liquid_net_worth_usd),
                "net_worth_usd": _flat(self.net_worth_usd),
                "partner_present": _flat_bool(self.partner_present),
                "monthly_spend_usd": _flat(self.monthly_spend_usd),
            },
        )

    def terminal_columns(self) -> ColumnarTable:
        final = -1
        return ColumnarTable(
            row_count=self.rollout_count,
            columns={
                "scenario_id": [self.scenario_id] * self.rollout_count,
                "scenario_label": [self.scenario_label] * self.rollout_count,
                "rollout_index": np.arange(self.rollout_count, dtype="int64").tolist(),
                "month_index": [int(self.month_index[final])] * self.rollout_count,
                "final_cash_usd": self.cash_usd[:, final].tolist(),
                "final_generic_sp500_value_usd": self.generic_sp500_value_usd[:, final].tolist(),
                "total_generic_sp500_sale_usd": np.sum(self.generic_sp500_sale_usd, axis=1).tolist(),
                "total_generic_sp500_sale_basis_usd": np.sum(self.generic_sp500_sale_basis_usd, axis=1).tolist(),
                "total_generic_sp500_sale_gain_usd": np.sum(self.generic_sp500_sale_gain_usd, axis=1).tolist(),
                "final_checking_floor_shortfall_usd": self.checking_floor_shortfall_usd[:, final].tolist(),
                "final_private_equity_value_usd": self.private_equity_value_usd[:, final].tolist(),
                "final_private_equity_liquidity_available_value_usd": (
                    self.private_equity_liquidity_available_value_usd[:, final].tolist()
                ),
                "total_private_equity_sale_usd": np.sum(self.private_equity_sale_usd, axis=1).tolist(),
                "total_private_equity_sale_basis_usd": np.sum(self.private_equity_sale_basis_usd, axis=1).tolist(),
                "total_private_equity_sale_tax_usd": np.sum(self.private_equity_sale_tax_usd, axis=1).tolist(),
                "final_property_value_usd": self.property_value_usd[:, final].tolist(),
                "final_mortgage_balance_usd": self.mortgage_balance_usd[:, final].tolist(),
                "final_home_equity_usd": self.home_equity_usd[:, final].tolist(),
                "final_owner_home_equity_claim_usd": self.owner_home_equity_claim_usd[:, final].tolist(),
                "final_partner_home_equity_claim_usd": self.partner_home_equity_claim_usd[:, final].tolist(),
                "final_partner_ownership_pct": self.partner_ownership_pct[:, final].tolist(),
                "total_partner_contribution_used_usd": np.sum(self.partner_contribution_used_usd, axis=1).tolist(),
                "total_rental_income_usd": np.sum(self.rental_income_usd, axis=1).tolist(),
                "total_property_carrying_cost_usd": np.sum(self.property_carrying_cost_usd, axis=1).tolist(),
                "total_net_property_cash_flow_usd": np.sum(self.net_property_cash_flow_usd, axis=1).tolist(),
                "total_purchase_closing_cost_usd": np.sum(self.purchase_closing_cost_usd, axis=1).tolist(),
                "total_sale_closing_cost_usd": np.sum(self.sale_closing_cost_usd, axis=1).tolist(),
                "total_property_depreciation_usd": np.sum(self.property_depreciation_usd, axis=1).tolist(),
                "final_cumulative_property_depreciation_usd": self.cumulative_property_depreciation_usd[
                    :, final
                ].tolist(),
                "total_property_sale_gross_usd": np.sum(self.property_sale_gross_usd, axis=1).tolist(),
                "total_property_sale_net_proceeds_usd": np.sum(self.property_sale_net_proceeds_usd, axis=1).tolist(),
                "total_property_sale_tax_usd": np.sum(self.property_sale_tax_usd, axis=1).tolist(),
                "total_property_sale_debt_payoff_usd": np.sum(self.property_sale_debt_payoff_usd, axis=1).tolist(),
                "total_realized_property_gain_usd": np.sum(self.realized_property_gain_usd, axis=1).tolist(),
                "total_taxable_property_gain_usd": np.sum(self.taxable_property_gain_usd, axis=1).tolist(),
                "total_depreciation_recapture_usd": np.sum(self.depreciation_recapture_usd, axis=1).tolist(),
                "total_net_property_sale_cash_flow_usd": np.sum(self.net_property_sale_cash_flow_usd, axis=1).tolist(),
                "final_liquid_net_worth_usd": self.liquid_net_worth_usd[:, final].tolist(),
                "final_net_worth_usd": self.net_worth_usd[:, final].tolist(),
            },
        )

    def metric_fan_columns(self) -> dict[str, ColumnarTable]:
        return {
            "cash_usd": _fan_columns(self.cash_usd),
            "net_worth_usd": _fan_columns(self.net_worth_usd),
            "liquid_net_worth_usd": _fan_columns(self.liquid_net_worth_usd),
            "generic_sp500_value_usd": _fan_columns(self.generic_sp500_value_usd),
            "checking_floor_shortfall_usd": _fan_columns(self.checking_floor_shortfall_usd),
            "property_value_usd": _fan_columns(self.property_value_usd),
            "home_equity_usd": _fan_columns(self.home_equity_usd),
            "owner_home_equity_claim_usd": _fan_columns(self.owner_home_equity_claim_usd),
            "partner_home_equity_claim_usd": _fan_columns(self.partner_home_equity_claim_usd),
            "partner_ownership_pct": _fan_columns(self.partner_ownership_pct),
            "mortgage_balance_usd": _fan_columns(self.mortgage_balance_usd),
            "rental_income_usd": _fan_columns(self.rental_income_usd),
            "net_property_cash_flow_usd": _fan_columns(self.net_property_cash_flow_usd),
            "property_sale_net_proceeds_usd": _fan_columns(self.property_sale_net_proceeds_usd),
            "net_property_sale_cash_flow_usd": _fan_columns(self.net_property_sale_cash_flow_usd),
            "private_equity_value_usd": _fan_columns(self.private_equity_value_usd),
            "private_equity_liquidity_available_value_usd": _fan_columns(
                self.private_equity_liquidity_available_value_usd
            ),
        }


@dataclass(frozen=True)
class PropertyCashFlowArrays:
    mortgage_payment_usd: np.ndarray
    property_tax_usd: np.ndarray
    hoa_usd: np.ndarray
    insurance_usd: np.ndarray
    maintenance_usd: np.ndarray
    rental_gross_income_usd: np.ndarray
    rental_vacancy_loss_usd: np.ndarray
    rental_income_usd: np.ndarray
    rental_management_fee_usd: np.ndarray
    rental_leasing_fee_usd: np.ndarray
    property_carrying_cost_usd: np.ndarray
    net_property_cash_flow_usd: np.ndarray


@dataclass(frozen=True)
class PartnerEquityArrays:
    contribution_usd: np.ndarray
    contribution_used_usd: np.ndarray
    unallocated_excess_usd: np.ndarray
    house_costs_usd: np.ndarray
    mortgage_payment_usd: np.ndarray
    mortgage_interest_usd: np.ndarray
    mortgage_principal_usd: np.ndarray
    principal_credit_usd: np.ndarray
    house_cost_share: np.ndarray
    ownership_pct: np.ndarray
    home_equity_claim_usd: np.ndarray


@dataclass(frozen=True)
class PrivateEquitySaleRequest:
    event_id: str
    event_type: EventType
    amount_usd: float


@dataclass(frozen=True)
class PrivateEquitySaleEffect:
    sale_usd: np.ndarray
    basis_usd: np.ndarray
    estimated_tax_usd: np.ndarray
    after_tax_proceeds_usd: np.ndarray
    sold_units: np.ndarray
    sold_fraction: np.ndarray


def run_scenario_set_vectorized(
    scenario_set: ScenarioSet,
    *,
    market_bundle: MarketBundle | None = None,
    market_provider: MarketBundleProvider | None = None,
) -> ScenarioSetRunResponse:
    if market_bundle is None:
        provider = market_provider or SimpleMarketBundleProvider()
        market_bundle = sample_market_bundle_for_request(provider, scenario_set.market_request)
    enabled_results: list[ScenarioResult] = []
    for scenario in scenario_set.scenarios:
        if not scenario.enabled:
            enabled_results.append(_disabled_result(scenario))
            continue
        arrays = run_scenario_vectorized(scenario, market_bundle)
        enabled_results.append(
            ScenarioResult(
                scenario_id=scenario.scenario_id,
                scenario_label=scenario.label,
                status=ScenarioResultStatus.SIMULATED,
                summary=_accepted_summary(scenario),
                metric_fan_columns=arrays.metric_fan_columns(),
                monthly_columns=arrays.monthly_columns(),
                terminal_columns=arrays.terminal_columns(),
                actions=arrays.actions,
            )
        )
    return ScenarioSetRunResponse(
        scenario_set_id=scenario_set.scenario_set_id,
        request=scenario_set,
        market_request=scenario_set.market_request,
        report_spec=scenario_set.report_spec,
        market_metadata=market_bundle.metadata.to_json_dict(),
        scenario_results=tuple(enabled_results),
    )


def run_scenario_vectorized(scenario: Scenario, market_bundle: MarketBundle) -> ScenarioRunArrays:
    month_index = market_bundle.month_index
    rollout_count = market_bundle.rollout_count
    month_count = market_bundle.horizon_months + 1
    location_id = scenario.location_id
    initial_cash = _initial_cash_usd(scenario)
    initial_sp500 = _initial_sp500_value_usd(scenario)
    initial_sp500_basis = _initial_sp500_cost_basis_usd(scenario)
    initial_private_equity = _initial_private_equity_value_usd(scenario)
    initial_private_equity_basis = _initial_private_equity_cost_basis_usd(scenario)
    initial_private_equity_units = _initial_private_equity_units(scenario)
    purchase_price = _purchase_price_usd(scenario)

    property_value, mortgage_balance, mortgage_interest, mortgage_principal = _property_and_mortgage_arrays(
        scenario, market_bundle, location_id=location_id
    )
    down_payment = _initial_property_cash_outlay_usd(scenario)
    property_cash_flow = _property_cash_flow_arrays(
        scenario,
        market_bundle,
        location_id=location_id,
        property_value_usd=property_value,
        mortgage_interest_usd=mortgage_interest,
        mortgage_principal_usd=mortgage_principal,
    )
    if scenario.property_selection.property_id is None:
        disposition = empty_property_disposition_arrays(market_bundle)
    else:
        disposition = property_disposition_arrays(
            scenario,
            market_bundle,
            property_value_usd=property_value,
            mortgage_balance_usd=mortgage_balance,
            purchase_price_usd=purchase_price,
            local_regulation=_required_local_regulation(scenario),
        )
    if disposition.sale_month is None:
        property_live_mask = np.ones((rollout_count, month_count), dtype="float64")
    else:
        property_live_mask = (month_index <= disposition.sale_month).astype("float64")
        property_live_mask = np.broadcast_to(property_live_mask[None, :], (rollout_count, month_count)).copy()
    mortgage_interest = mortgage_interest * property_live_mask
    mortgage_principal = mortgage_principal * property_live_mask
    net_property_cash_flow = property_cash_flow.net_property_cash_flow_usd * property_live_mask
    home_equity = property_value - mortgage_balance
    partner_equity = _partner_equity_arrays(
        scenario,
        market_bundle,
        owner_initial_equity_usd=down_payment,
        home_equity_usd=home_equity,
        mortgage_interest_usd=mortgage_interest,
        mortgage_principal_usd=mortgage_principal,
        property_tax_usd=property_cash_flow.property_tax_usd * property_live_mask,
        hoa_usd=property_cash_flow.hoa_usd * property_live_mask,
        insurance_usd=property_cash_flow.insurance_usd * property_live_mask,
        maintenance_usd=property_cash_flow.maintenance_usd * property_live_mask,
    )
    generic_sp500_value = np.zeros((rollout_count, month_count), dtype="float64")
    generic_sp500_sale = np.zeros((rollout_count, month_count), dtype="float64")
    generic_sp500_sale_basis = np.zeros((rollout_count, month_count), dtype="float64")
    generic_sp500_sale_gain = np.zeros((rollout_count, month_count), dtype="float64")
    checking_floor_action = np.zeros((rollout_count, month_count), dtype="float64")
    checking_floor_shortfall = np.zeros((rollout_count, month_count), dtype="float64")
    private_equity_value = np.zeros((rollout_count, month_count), dtype="float64")
    private_equity_liquidity_available_value = np.zeros((rollout_count, month_count), dtype="float64")
    private_equity_sale = np.zeros((rollout_count, month_count), dtype="float64")
    private_equity_sale_basis = np.zeros((rollout_count, month_count), dtype="float64")
    private_equity_sale_tax = np.zeros((rollout_count, month_count), dtype="float64")
    cash = np.zeros((rollout_count, month_count), dtype="float64")
    monthly_spend_arr = np.zeros((rollout_count, month_count), dtype="float64")
    spend_policies = _enabled_policies_of(scenario, MonthlySpendPolicy)
    private_equity_sale_requests = _private_equity_sale_requests_by_month(scenario)
    private_equity_liquidity_event = market_bundle.private_equity_liquidity_event_mask.copy()
    private_equity_sale_policy = _enabled_policy_of(scenario, PrivateEquitySalePolicy)
    checking_policies = _enabled_policies_of(scenario, CheckingFloorSellPublicStockPolicy)
    remaining_private_equity_fraction = np.ones(rollout_count, dtype="float64")
    remaining_sp500_units = np.divide(
        initial_sp500,
        market_bundle.generic_sp500_multipliers[:, 0],
        out=np.zeros(rollout_count, dtype="float64"),
        where=market_bundle.generic_sp500_multipliers[:, 0] > 0,
    )
    remaining_sp500_basis = np.full(rollout_count, initial_sp500_basis, dtype="float64")
    remaining_private_equity_basis = np.full(rollout_count, initial_private_equity_basis, dtype="float64")
    remaining_private_equity_units = np.full(rollout_count, initial_private_equity_units, dtype="float64")
    current_cash = (
        np.full(rollout_count, initial_cash - down_payment, dtype="float64")
        - disposition.purchase_closing_cost_usd[:, 0]
    )
    actions: list[SimulationAction] = []

    for month in range(month_count):
        current_cash = current_cash + disposition.net_property_sale_cash_flow_usd[:, month]
        if month > 0:
            current_cash = (
                current_cash + net_property_cash_flow[:, month] + partner_equity.contribution_used_usd[:, month]
            )

        if month > 0:
            for spend_policy in spend_policies:
                inflation_multiplier = (
                    market_bundle.inflation_multipliers[:, month]
                    if spend_policy.inflation_adjusted
                    else np.ones(rollout_count, dtype="float64")
                )
                spend_amount = float(spend_policy.monthly_spend_usd) * inflation_multiplier
                current_cash = current_cash - spend_amount
                monthly_spend_arr[:, month] = monthly_spend_arr[:, month] + spend_amount
                _record_monthly_spend_actions(
                    actions,
                    month_index=int(month_index[month]),
                    policy=spend_policy,
                    amount_usd=spend_amount,
                    inflation_multiplier=inflation_multiplier,
                )

        private_equity_value_before_sale = (
            initial_private_equity
            * remaining_private_equity_fraction
            * market_bundle.private_equity_value_multipliers[:, month]
        )
        market_liquidity_available_value = np.where(
            market_bundle.private_equity_liquidity_event_mask[:, month], private_equity_value_before_sale, 0.0
        )
        requested_sale = private_equity_sale_requests.get(month)
        sale_effect = _empty_private_equity_sale_effect(rollout_count)
        if private_equity_sale_policy is not None:
            requested_amount = (
                requested_sale.amount_usd
                if requested_sale is not None
                else _private_equity_opportunity_sale_amount(
                    private_equity_sale_policy,
                    liquidity_event_mask=market_bundle.private_equity_liquidity_event_mask[:, month],
                )
            )
            sale_effect = _private_equity_sale_effect(
                requested_amount_usd=requested_amount,
                liquidity_available_value_usd=market_liquidity_available_value,
                private_equity_value_before_sale_usd=private_equity_value_before_sale,
                remaining_basis_usd=remaining_private_equity_basis,
                remaining_units=remaining_private_equity_units,
                cap_gains_rate_pct=float(scenario.tax_profile.cap_gains_rate),
            )
            proceeds_destination = _private_equity_sale_proceeds_destination(private_equity_sale_policy)
            if proceeds_destination is AssetType.GENERIC_SP500_STOCK:
                sp500_multiplier = market_bundle.generic_sp500_multipliers[:, month]
                remaining_sp500_units = remaining_sp500_units + np.divide(
                    sale_effect.after_tax_proceeds_usd,
                    sp500_multiplier,
                    out=np.zeros_like(sale_effect.after_tax_proceeds_usd),
                    where=sp500_multiplier > 0,
                )
                remaining_sp500_basis = remaining_sp500_basis + sale_effect.after_tax_proceeds_usd
            else:
                current_cash = current_cash + sale_effect.after_tax_proceeds_usd
            _record_private_equity_sale_actions(
                actions,
                month_index=int(month_index[month]),
                request=requested_sale,
                policy=private_equity_sale_policy,
                sale_effect=sale_effect,
                proceeds_destination=proceeds_destination,
            )
            remaining_private_equity_fraction = np.maximum(
                0.0, remaining_private_equity_fraction * (1 - sale_effect.sold_fraction)
            )
            remaining_private_equity_basis = np.maximum(0.0, remaining_private_equity_basis - sale_effect.basis_usd)
            remaining_private_equity_units = np.maximum(0.0, remaining_private_equity_units - sale_effect.sold_units)

        sp500_multiplier = market_bundle.generic_sp500_multipliers[:, month]
        sp500_sale = np.zeros(rollout_count, dtype="float64")
        sp500_basis = np.zeros(rollout_count, dtype="float64")
        sp500_shortfall = np.zeros(rollout_count, dtype="float64")
        for checking_policy in checking_policies:
            sp500_value_before_sale = remaining_sp500_units * sp500_multiplier
            policy_sp500_sale, policy_sp500_basis, policy_sp500_shortfall = _checking_floor_stock_sale(
                checking_policy,
                current_cash_usd=current_cash,
                sp500_value_usd=sp500_value_before_sale,
                remaining_sp500_basis_usd=remaining_sp500_basis,
            )
            current_cash = current_cash + policy_sp500_sale
            remaining_sp500_units = np.maximum(
                0.0,
                remaining_sp500_units
                - np.divide(
                    policy_sp500_sale,
                    sp500_multiplier,
                    out=np.zeros_like(policy_sp500_sale),
                    where=sp500_multiplier > 0,
                ),
            )
            remaining_sp500_basis = np.maximum(0.0, remaining_sp500_basis - policy_sp500_basis)
            sp500_sale = sp500_sale + policy_sp500_sale
            sp500_basis = sp500_basis + policy_sp500_basis
            sp500_shortfall = np.maximum(sp500_shortfall, policy_sp500_shortfall)
            _record_sp500_sale_actions(
                actions,
                month_index=int(month_index[month]),
                policy=checking_policy,
                amount_usd=policy_sp500_sale,
                basis_usd=policy_sp500_basis,
                shortfall_usd=policy_sp500_shortfall,
            )
        sp500_value_after_sale = remaining_sp500_units * sp500_multiplier

        cash[:, month] = current_cash
        generic_sp500_value[:, month] = sp500_value_after_sale
        generic_sp500_sale[:, month] = sp500_sale
        generic_sp500_sale_basis[:, month] = sp500_basis
        generic_sp500_sale_gain[:, month] = sp500_sale - sp500_basis
        checking_floor_action[:, month] = sp500_sale
        checking_floor_shortfall[:, month] = sp500_shortfall
        private_equity_sale[:, month] = sale_effect.sale_usd
        private_equity_sale_basis[:, month] = sale_effect.basis_usd
        private_equity_sale_tax[:, month] = sale_effect.estimated_tax_usd
        private_equity_liquidity_available_value[:, month] = np.maximum(
            0.0, market_liquidity_available_value - sale_effect.sale_usd
        )
        private_equity_value[:, month] = private_equity_value_before_sale - sale_effect.sale_usd

    partner_present = np.full((rollout_count, month_count), _has_partner(scenario), dtype=np.bool_)
    partner_home_equity_claim = partner_equity.home_equity_claim_usd
    owner_home_equity_claim = home_equity - partner_home_equity_claim
    if disposition.sale_month is None:
        owner_home_equity_claim_for_net_worth = owner_home_equity_claim
    else:
        unsold_mask = (month_index < disposition.sale_month).astype("float64")
        unsold_mask = np.broadcast_to(unsold_mask[None, :], (rollout_count, month_count))
        owner_home_equity_claim_for_net_worth = owner_home_equity_claim * unsold_mask
    liquid_net_worth = cash + generic_sp500_value + private_equity_liquidity_available_value
    net_worth = cash + generic_sp500_value + private_equity_value + owner_home_equity_claim_for_net_worth
    _record_partner_agreement_actions(
        actions,
        scenario=scenario,
        month_index=month_index,
        partner_equity=partner_equity,
        mortgage_balance_usd=mortgage_balance,
    )
    return ScenarioRunArrays(
        scenario_id=scenario.scenario_id,
        scenario_label=scenario.label,
        month_index=month_index,
        cash_usd=cash,
        generic_sp500_value_usd=generic_sp500_value,
        generic_sp500_sale_usd=generic_sp500_sale,
        generic_sp500_sale_basis_usd=generic_sp500_sale_basis,
        generic_sp500_sale_gain_usd=generic_sp500_sale_gain,
        checking_floor_action_usd=checking_floor_action,
        checking_floor_shortfall_usd=checking_floor_shortfall,
        private_equity_value_usd=private_equity_value,
        private_equity_liquidity_available_value_usd=private_equity_liquidity_available_value,
        private_equity_sale_usd=private_equity_sale,
        private_equity_sale_basis_usd=private_equity_sale_basis,
        private_equity_sale_tax_usd=private_equity_sale_tax,
        private_equity_liquidity_event=private_equity_liquidity_event,
        property_value_usd=property_value,
        mortgage_balance_usd=mortgage_balance,
        mortgage_interest_usd=mortgage_interest,
        mortgage_principal_usd=mortgage_principal,
        mortgage_payment_usd=property_cash_flow.mortgage_payment_usd * property_live_mask,
        property_tax_usd=property_cash_flow.property_tax_usd * property_live_mask,
        hoa_usd=property_cash_flow.hoa_usd * property_live_mask,
        insurance_usd=property_cash_flow.insurance_usd * property_live_mask,
        maintenance_usd=property_cash_flow.maintenance_usd * property_live_mask,
        rental_gross_income_usd=property_cash_flow.rental_gross_income_usd * property_live_mask,
        rental_vacancy_loss_usd=property_cash_flow.rental_vacancy_loss_usd * property_live_mask,
        rental_income_usd=property_cash_flow.rental_income_usd * property_live_mask,
        rental_management_fee_usd=property_cash_flow.rental_management_fee_usd * property_live_mask,
        rental_leasing_fee_usd=property_cash_flow.rental_leasing_fee_usd * property_live_mask,
        property_carrying_cost_usd=property_cash_flow.property_carrying_cost_usd * property_live_mask,
        net_property_cash_flow_usd=net_property_cash_flow,
        purchase_closing_cost_usd=disposition.purchase_closing_cost_usd,
        sale_closing_cost_usd=disposition.sale_closing_cost_usd,
        property_depreciation_usd=disposition.property_depreciation_usd,
        cumulative_property_depreciation_usd=disposition.cumulative_property_depreciation_usd,
        property_sale_gross_usd=disposition.property_sale_gross_usd,
        property_sale_net_proceeds_usd=disposition.property_sale_net_proceeds_usd,
        property_sale_tax_usd=disposition.property_sale_tax_usd,
        property_sale_debt_payoff_usd=disposition.property_sale_debt_payoff_usd,
        realized_property_gain_usd=disposition.realized_property_gain_usd,
        taxable_property_gain_usd=disposition.taxable_property_gain_usd,
        depreciation_recapture_usd=disposition.depreciation_recapture_usd,
        net_property_sale_cash_flow_usd=disposition.net_property_sale_cash_flow_usd,
        home_equity_usd=home_equity,
        owner_home_equity_claim_usd=owner_home_equity_claim,
        partner_home_equity_claim_usd=partner_home_equity_claim,
        partner_contribution_usd=partner_equity.contribution_usd,
        partner_contribution_used_usd=partner_equity.contribution_used_usd,
        partner_unallocated_excess_usd=partner_equity.unallocated_excess_usd,
        partner_ownership_pct=partner_equity.ownership_pct,
        liquid_net_worth_usd=liquid_net_worth,
        net_worth_usd=net_worth,
        partner_present=partner_present,
        monthly_spend_usd=monthly_spend_arr,
        actions=_sorted_actions(actions),
    )


def _checking_floor_stock_sale(
    policy: CheckingFloorSellPublicStockPolicy,
    *,
    current_cash_usd: np.ndarray,
    sp500_value_usd: np.ndarray,
    remaining_sp500_basis_usd: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    floor_usd = policy.floor_usd
    sale_amount_usd = policy.sale_amount_usd
    should_sell = current_cash_usd < floor_usd
    sale = np.where(should_sell, np.minimum(sale_amount_usd, sp500_value_usd), 0.0)
    basis = np.divide(
        remaining_sp500_basis_usd * sale, sp500_value_usd, out=np.zeros_like(sale), where=sp500_value_usd > 0
    )
    shortfall = np.maximum(0.0, floor_usd - (current_cash_usd + sale))
    return sale, basis, shortfall


def _empty_private_equity_sale_effect(rollout_count: int) -> PrivateEquitySaleEffect:
    zeros = np.zeros(rollout_count, dtype="float64")
    return PrivateEquitySaleEffect(
        sale_usd=zeros,
        basis_usd=zeros,
        estimated_tax_usd=zeros,
        after_tax_proceeds_usd=zeros,
        sold_units=zeros,
        sold_fraction=zeros,
    )


def _private_equity_sale_effect(
    *,
    requested_amount_usd: float | np.ndarray,
    liquidity_available_value_usd: np.ndarray,
    private_equity_value_before_sale_usd: np.ndarray,
    remaining_basis_usd: np.ndarray,
    remaining_units: np.ndarray,
    cap_gains_rate_pct: float,
) -> PrivateEquitySaleEffect:
    sale = np.minimum(requested_amount_usd, liquidity_available_value_usd)
    sold_fraction = np.divide(
        sale,
        private_equity_value_before_sale_usd,
        out=np.zeros_like(sale),
        where=private_equity_value_before_sale_usd > 0,
    )
    basis = remaining_basis_usd * sold_fraction
    taxable_gain = np.maximum(0.0, sale - basis)
    estimated_tax = taxable_gain * cap_gains_rate_pct / 100
    return PrivateEquitySaleEffect(
        sale_usd=sale,
        basis_usd=basis,
        estimated_tax_usd=estimated_tax,
        after_tax_proceeds_usd=np.maximum(0.0, sale - estimated_tax),
        sold_units=remaining_units * sold_fraction,
        sold_fraction=sold_fraction,
    )


def _private_equity_opportunity_sale_amount(
    policy: PrivateEquitySalePolicy, *, liquidity_event_mask: np.ndarray
) -> np.ndarray:
    if isinstance(policy.sale_rule, FixedAmountPrivateEquitySaleRule):
        return np.where(liquidity_event_mask, float(policy.sale_rule.amount_usd), 0.0)
    return np.zeros(liquidity_event_mask.shape, dtype="float64")


def _record_sp500_sale_actions(
    actions: list[SimulationAction],
    *,
    month_index: int,
    policy: Policy,
    amount_usd: np.ndarray,
    basis_usd: np.ndarray,
    shortfall_usd: np.ndarray,
) -> None:
    for rollout_index in np.nonzero((amount_usd > 0) | (shortfall_usd > 0))[0].tolist():
        amount = float(amount_usd[rollout_index])
        basis = float(basis_usd[rollout_index])
        actions.append(
            SellSp500Action(
                rollout_index=rollout_index,
                month_index=month_index,
                actor_id=policy.actor_id,
                policy_id=policy.policy_id,
                amount_usd=amount,
                basis_usd=basis,
                gain_usd=amount - basis,
                shortfall_usd=float(shortfall_usd[rollout_index]),
            )
        )


def _record_private_equity_sale_actions(
    actions: list[SimulationAction],
    *,
    month_index: int,
    request: PrivateEquitySaleRequest | None,
    policy: Policy,
    sale_effect: PrivateEquitySaleEffect,
    proceeds_destination: AccountType | AssetType,
) -> None:
    actions.extend(
        SellPrivateEquityAction(
            rollout_index=rollout_index,
            month_index=month_index,
            actor_id=policy.actor_id,
            policy_id=policy.policy_id,
            event_id=request.event_id if request is not None else None,
            event_type=request.event_type if request is not None else None,
            amount_usd=float(sale_effect.sale_usd[rollout_index]),
            after_tax_proceeds_usd=float(sale_effect.after_tax_proceeds_usd[rollout_index]),
            basis_usd=float(sale_effect.basis_usd[rollout_index]),
            taxable_gain_usd=float(
                max(0.0, sale_effect.sale_usd[rollout_index] - sale_effect.basis_usd[rollout_index])
            ),
            estimated_tax_usd=float(sale_effect.estimated_tax_usd[rollout_index]),
            units_sold=float(sale_effect.sold_units[rollout_index]),
            sold_fraction=float(sale_effect.sold_fraction[rollout_index]),
            proceeds_destination=proceeds_destination,
        )
        for rollout_index in np.nonzero(sale_effect.sale_usd > 0)[0].tolist()
    )


def _record_monthly_spend_actions(
    actions: list[SimulationAction],
    *,
    month_index: int,
    policy: MonthlySpendPolicy,
    amount_usd: np.ndarray,
    inflation_multiplier: np.ndarray,
) -> None:
    actions.extend(
        MonthlySpendAction(
            rollout_index=rollout_index,
            month_index=month_index,
            actor_id=policy.actor_id,
            policy_id=policy.policy_id,
            amount_usd=float(amount_usd[rollout_index]),
            inflation_multiplier=float(inflation_multiplier[rollout_index]),
        )
        for rollout_index in np.nonzero(amount_usd > 0)[0].tolist()
    )


def _record_partner_agreement_actions(
    actions: list[SimulationAction],
    *,
    scenario: Scenario,
    month_index: np.ndarray,
    partner_equity: PartnerEquityArrays,
    mortgage_balance_usd: np.ndarray,
) -> None:
    policy = _enabled_policy_of(scenario, PartnerEquityAccrualPolicy)
    property_id = _partner_equity_property_id(scenario, policy)
    if policy is None or property_id is None:
        return
    owner_actor_id = _primary_owner_actor_id(scenario)
    active = (partner_equity.contribution_usd > 0) | (partner_equity.unallocated_excess_usd > 0)
    rollout_indexes, month_positions = np.nonzero(active)
    for rollout_index, month_position in zip(rollout_indexes.tolist(), month_positions.tolist(), strict=True):
        month = int(month_index[month_position])
        contribution = float(partner_equity.contribution_usd[rollout_index, month_position])
        contribution_used = float(partner_equity.contribution_used_usd[rollout_index, month_position])
        mortgage_principal = float(partner_equity.mortgage_principal_usd[rollout_index, month_position])
        actions.append(
            TransferPartnerContributionAction(
                rollout_index=rollout_index,
                month_index=month,
                actor_id=policy.actor_id,
                policy_id=policy.policy_id,
                recipient_actor_id=owner_actor_id,
                amount_usd=contribution,
                applied_to_house_costs_usd=contribution_used,
                unallocated_amount_usd=float(partner_equity.unallocated_excess_usd[rollout_index, month_position]),
            )
        )
        actions.append(
            PayMortgageAction(
                rollout_index=rollout_index,
                month_index=month,
                actor_id=owner_actor_id,
                policy_id=policy.policy_id,
                mortgage_payment_usd=float(partner_equity.mortgage_payment_usd[rollout_index, month_position]),
                mortgage_interest_usd=float(partner_equity.mortgage_interest_usd[rollout_index, month_position]),
                mortgage_principal_usd=mortgage_principal,
                mortgage_balance_after_usd=float(mortgage_balance_usd[rollout_index, month_position]),
            )
        )
        actions.append(
            AccruePartnerEquityAction(
                rollout_index=rollout_index,
                month_index=month,
                actor_id=policy.actor_id,
                policy_id=policy.policy_id,
                beneficiary_actor_id=policy.actor_id,
                property_id=property_id,
                house_costs_usd=float(partner_equity.house_costs_usd[rollout_index, month_position]),
                cash_transfer_used_for_house_costs_usd=contribution_used,
                mortgage_principal_usd=mortgage_principal,
                principal_credit_usd=float(partner_equity.principal_credit_usd[rollout_index, month_position]),
                house_cost_share=float(partner_equity.house_cost_share[rollout_index, month_position]),
                ownership_pct_after=float(partner_equity.ownership_pct[rollout_index, month_position]),
                home_equity_claim_usd_after=float(partner_equity.home_equity_claim_usd[rollout_index, month_position]),
            )
        )


def _sorted_actions(actions: list[SimulationAction]) -> tuple[SimulationAction, ...]:
    return tuple(sorted(actions, key=lambda action: (action.month_index, action.rollout_index, action.action_type)))


def _property_cash_flow_arrays(
    scenario: Scenario,
    market_bundle: MarketBundle,
    *,
    location_id: LocationId | None,
    property_value_usd: np.ndarray,
    mortgage_interest_usd: np.ndarray,
    mortgage_principal_usd: np.ndarray,
) -> PropertyCashFlowArrays:
    zeros = np.zeros_like(property_value_usd, dtype="float64")
    mortgage_payment = mortgage_interest_usd + mortgage_principal_usd
    if scenario.property_selection.property_id is None:
        return PropertyCashFlowArrays(
            mortgage_payment_usd=mortgage_payment,
            property_tax_usd=zeros,
            hoa_usd=zeros,
            insurance_usd=zeros,
            maintenance_usd=zeros,
            rental_gross_income_usd=zeros,
            rental_vacancy_loss_usd=zeros,
            rental_income_usd=zeros,
            rental_management_fee_usd=zeros,
            rental_leasing_fee_usd=zeros,
            property_carrying_cost_usd=zeros,
            net_property_cash_flow_usd=-mortgage_payment,
        )

    property_tax = monthly_property_tax_usd(
        purchase_price_usd=_purchase_price_usd(scenario),
        local_regulation=_required_local_regulation(scenario),
        market_bundle=market_bundle,
    )
    expense_multiplier = market_bundle.inflation_multipliers.copy()
    expense_multiplier[:, 0] = 0.0
    hoa = _scenario_hoa_monthly_usd(scenario) * expense_multiplier
    property_assumptions = scenario.property_assumptions
    insurance = (property_assumptions.insurance_annual_usd / MONTHS_PER_YEAR) * expense_multiplier
    maintenance = property_value_usd * (property_assumptions.maintenance_pct / 100) / MONTHS_PER_YEAR
    maintenance[:, 0] = 0.0
    (rental_gross_income, rental_vacancy_loss, rental_income, rental_management_fee, rental_leasing_fee) = (
        _rental_cash_flow_arrays(scenario, market_bundle, location_id=location_id)
    )
    property_carrying_cost = property_tax + hoa + insurance + maintenance + rental_management_fee + rental_leasing_fee
    net_property_cash_flow = rental_income - property_carrying_cost - mortgage_payment
    return PropertyCashFlowArrays(
        mortgage_payment_usd=mortgage_payment,
        property_tax_usd=property_tax,
        hoa_usd=hoa,
        insurance_usd=insurance,
        maintenance_usd=maintenance,
        rental_gross_income_usd=rental_gross_income,
        rental_vacancy_loss_usd=rental_vacancy_loss,
        rental_income_usd=rental_income,
        rental_management_fee_usd=rental_management_fee,
        rental_leasing_fee_usd=rental_leasing_fee,
        property_carrying_cost_usd=property_carrying_cost,
        net_property_cash_flow_usd=net_property_cash_flow,
    )


def _rental_cash_flow_arrays(
    scenario: Scenario, market_bundle: MarketBundle, *, location_id: LocationId | None
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    shape = (market_bundle.rollout_count, market_bundle.horizon_months + 1)
    gross = np.zeros(shape, dtype="float64")
    vacancy_loss = np.zeros(shape, dtype="float64")
    income = np.zeros(shape, dtype="float64")
    management_fee = np.zeros(shape, dtype="float64")
    leasing_fee = np.zeros(shape, dtype="float64")
    rental = scenario.rental_plan
    if rental.rental_mode is RentalMode.NOT_RENTED:
        return gross, vacancy_loss, income, management_fee, leasing_fee

    active = rental_active_mask(scenario, market_bundle)
    rent_multiplier = market_bundle.rent_multipliers(location_id)
    if rental.rental_mode is RentalMode.RENT_ROOMS_WHILE_OWNER_LIVES_THERE:
        base_rent = float(rental.rooms_rented) * float(rental.room_rent_monthly_usd or 0.0)
        vacancy_fraction = _pct_fraction(float(rental.room_vacancy_pct), "room_vacancy_pct")
        applies_management = False
    else:
        base_rent = float(rental.monthly_rent_usd or 0.0)
        vacancy_fraction = _pct_fraction(float(rental.vacancy_pct), "vacancy_pct")
        applies_management = True

    gross = base_rent * rent_multiplier * active[None, :]
    vacancy_loss = gross * vacancy_fraction
    income = gross - vacancy_loss
    if applies_management:
        management_fee = income * _pct_fraction(float(rental.management_fee_pct), "management_fee_pct")
        leasing_fee = gross * _pct_fraction(float(rental.leasing_fee_pct), "leasing_fee_pct") / MONTHS_PER_YEAR
    return gross, vacancy_loss, income, management_fee, leasing_fee


def _partner_equity_arrays(
    scenario: Scenario,
    market_bundle: MarketBundle,
    *,
    owner_initial_equity_usd: float,
    home_equity_usd: np.ndarray,
    mortgage_interest_usd: np.ndarray,
    mortgage_principal_usd: np.ndarray,
    property_tax_usd: np.ndarray,
    hoa_usd: np.ndarray,
    insurance_usd: np.ndarray,
    maintenance_usd: np.ndarray,
) -> PartnerEquityArrays:
    zeros = np.zeros_like(home_equity_usd, dtype="float64")
    policy = _enabled_policy_of(scenario, PartnerEquityAccrualPolicy)
    property_id = _partner_equity_property_id(scenario, policy)
    if policy is None or not _has_partner(scenario) or property_id is None:
        return PartnerEquityArrays(
            contribution_usd=zeros,
            contribution_used_usd=zeros,
            unallocated_excess_usd=zeros,
            house_costs_usd=zeros,
            mortgage_payment_usd=zeros,
            mortgage_interest_usd=zeros,
            mortgage_principal_usd=zeros,
            principal_credit_usd=zeros,
            house_cost_share=zeros,
            ownership_pct=zeros,
            home_equity_claim_usd=zeros,
        )

    base_payment = policy.base_monthly_payment_usd
    occupied_months = _partner_occupied_months(scenario, policy, market_bundle.horizon_months)
    month_matrix = np.broadcast_to(market_bundle.month_index[None, :], home_equity_usd.shape)
    active = (month_matrix > 0) & (month_matrix <= occupied_months)
    payment_growth = _partner_payment_growth(policy, market_bundle)
    configured_payment = np.where(active, base_payment * payment_growth, 0.0)

    mortgage_payment = mortgage_interest_usd + mortgage_principal_usd
    house_uses = (
        mortgage_interest_usd + mortgage_principal_usd + property_tax_usd + hoa_usd + insurance_usd + maintenance_usd
    )
    contribution_used = np.where(active, np.minimum(configured_payment, house_uses), 0.0)
    unallocated_excess = np.where(active, np.maximum(0.0, configured_payment - contribution_used), 0.0)
    contribution_share = np.divide(
        contribution_used, house_uses, out=np.zeros_like(contribution_used), where=house_uses > 0
    )
    principal_credit = mortgage_principal_usd * contribution_share
    owner_principal = mortgage_principal_usd - principal_credit
    partner_equity_ledger = np.cumsum(principal_credit, axis=1)
    owner_equity_ledger = owner_initial_equity_usd + np.cumsum(owner_principal, axis=1)
    total_equity_ledger = partner_equity_ledger + owner_equity_ledger
    live_ownership_pct = np.divide(
        partner_equity_ledger,
        total_equity_ledger,
        out=np.zeros_like(partner_equity_ledger),
        where=total_equity_ledger > 0,
    )
    freeze_after_month = _partner_freeze_after_month(scenario, policy, occupied_months, market_bundle.horizon_months)
    ownership_pct = _ownership_with_optional_freeze(live_ownership_pct, month_matrix, freeze_after_month)
    claim = np.maximum(home_equity_usd, 0.0) * ownership_pct
    return PartnerEquityArrays(
        contribution_usd=configured_payment,
        contribution_used_usd=contribution_used,
        unallocated_excess_usd=unallocated_excess,
        house_costs_usd=house_uses,
        mortgage_payment_usd=mortgage_payment,
        mortgage_interest_usd=mortgage_interest_usd,
        mortgage_principal_usd=mortgage_principal_usd,
        principal_credit_usd=principal_credit,
        house_cost_share=contribution_share,
        ownership_pct=ownership_pct,
        home_equity_claim_usd=claim,
    )


def _partner_equity_property_id(scenario: Scenario, policy: PartnerEquityAccrualPolicy | None) -> str | None:
    if policy is None:
        return None
    return policy.property_id or scenario.property_selection.property_id


def _partner_payment_growth(policy: PartnerEquityAccrualPolicy, market_bundle: MarketBundle) -> np.ndarray:
    if policy.grow_with_inflation:
        return market_bundle.inflation_multipliers
    growth_pct = policy.payment_growth_annual_pct
    month_index = market_bundle.month_index.astype("float64")
    growth = (1 + growth_pct / 100) ** (month_index / MONTHS_PER_YEAR)
    return np.broadcast_to(growth[None, :], (market_bundle.rollout_count, market_bundle.horizon_months + 1)).copy()


def _partner_occupied_months(scenario: Scenario, policy: PartnerEquityAccrualPolicy, horizon_months: int) -> int:
    if policy.occupied_months is not None:
        occupied_months = int(policy.occupied_months)
    elif scenario.occupancy_plan.occupancy_mode is OccupancyMode.NO_OWNER_OCCUPANCY:
        occupied_months = 0
    elif scenario.occupancy_plan.end_month is not None:
        occupied_months = int(scenario.occupancy_plan.end_month)
    else:
        occupied_months = horizon_months
    return max(0, min(occupied_months, horizon_months))


def _partner_freeze_after_month(
    scenario: Scenario, policy: PartnerEquityAccrualPolicy, occupied_months: int, horizon_months: int
) -> int | None:
    if policy.freeze_ownership_after_month is not None:
        return max(0, min(int(policy.freeze_ownership_after_month), horizon_months))
    if occupied_months < horizon_months:
        return occupied_months
    if scenario.rental_plan.rental_mode is RentalMode.TRANSITION_TO_WHOLE_PROPERTY_RENTAL:
        return occupied_months
    return None


def _ownership_with_optional_freeze(
    live_ownership_pct: np.ndarray, month_index: np.ndarray, freeze_after_month: int | None
) -> np.ndarray:
    if freeze_after_month is None:
        return live_ownership_pct
    freeze_mask = month_index == freeze_after_month
    found = np.any(freeze_mask, axis=1, keepdims=True)
    freeze_positions = np.argmax(freeze_mask, axis=1)
    frozen = np.take_along_axis(live_ownership_pct, freeze_positions[:, None], axis=1)
    should_freeze = (month_index >= freeze_after_month) & found
    return np.where(should_freeze, frozen, live_ownership_pct)


def _property_and_mortgage_arrays(
    scenario: Scenario, market_bundle: MarketBundle, *, location_id: LocationId | None
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    rollout_count = market_bundle.rollout_count
    month_count = market_bundle.horizon_months + 1
    property_value = np.zeros((rollout_count, month_count), dtype="float64")
    mortgage_balance = np.zeros((rollout_count, month_count), dtype="float64")
    mortgage_interest = np.zeros((rollout_count, month_count), dtype="float64")
    mortgage_principal = np.zeros((rollout_count, month_count), dtype="float64")
    if scenario.property_selection.property_id is None:
        return property_value, mortgage_balance, mortgage_interest, mortgage_principal

    purchase_price = _purchase_price_usd(scenario)
    property_value = purchase_price * market_bundle.home_value_multipliers(location_id)
    loan_amount, annual_rate_pct, term_months = _loan_terms(scenario, market_bundle, purchase_price)
    if np.allclose(loan_amount, 0):
        return property_value, mortgage_balance, mortgage_interest, mortgage_principal

    mortgage_balance, mortgage_interest, mortgage_principal = _amortization_arrays(
        loan_amount=loan_amount,
        annual_rate_pct=annual_rate_pct,
        term_months=term_months,
        horizon_months=market_bundle.horizon_months,
    )
    return property_value, mortgage_balance, mortgage_interest, mortgage_principal


def _amortization_arrays(
    *, loan_amount: np.ndarray, annual_rate_pct: np.ndarray, term_months: int, horizon_months: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    rollout_count = loan_amount.shape[0]
    month_count = horizon_months + 1
    balance = np.zeros((rollout_count, month_count), dtype="float64")
    interest = np.zeros((rollout_count, month_count), dtype="float64")
    principal = np.zeros((rollout_count, month_count), dtype="float64")
    current_balance = loan_amount.astype("float64").copy()
    balance[:, 0] = current_balance
    monthly_rate = annual_rate_pct / 100 / MONTHS_PER_YEAR
    payment = np.zeros_like(loan_amount)
    zero_rate = monthly_rate == 0
    payment[zero_rate] = loan_amount[zero_rate] / term_months
    nonzero_rate = ~zero_rate
    payment[nonzero_rate] = (
        loan_amount[nonzero_rate]
        * monthly_rate[nonzero_rate]
        * (1 + monthly_rate[nonzero_rate]) ** term_months
        / ((1 + monthly_rate[nonzero_rate]) ** term_months - 1)
    )
    for month in range(1, month_count):
        active = (month <= term_months) & (current_balance > 0)
        month_interest = np.where(active, current_balance * monthly_rate, 0.0)
        month_principal = np.where(active, np.minimum(payment - month_interest, current_balance), 0.0)
        current_balance = np.maximum(0.0, current_balance - month_principal)
        interest[:, month] = month_interest
        principal[:, month] = month_principal
        balance[:, month] = current_balance
    return balance, interest, principal


def _loan_terms(
    scenario: Scenario, market_bundle: MarketBundle, purchase_price_usd: float
) -> tuple[np.ndarray, np.ndarray, int]:
    financing = scenario.financing
    rollout_count = market_bundle.rollout_count
    if financing.financing_mode is FinancingMode.CASH:
        return (np.zeros(rollout_count, dtype="float64"), np.zeros(rollout_count, dtype="float64"), 1)
    if financing.down_payment_pct > 100:
        raise ValueError("down_payment_pct must be <= 100")
    if financing.loan_amount_usd is not None:
        loan_amount_value = float(financing.loan_amount_usd)
        if loan_amount_value > purchase_price_usd:
            raise ValueError("loan_amount_usd must not exceed purchase_price_usd")
    else:
        loan_amount_value = purchase_price_usd * (1 - financing.down_payment_pct / 100)
    loan_amount = np.full(rollout_count, loan_amount_value, dtype="float64")
    rate_pct = (
        np.full(rollout_count, float(financing.mortgage_rate_pct), dtype="float64")
        if financing.mortgage_rate_pct is not None
        else market_bundle.mortgage_30y_rate_pct[:, 0]
    )
    term_years = financing.mortgage_term_years
    if term_years is None:
        term_years = 15 if financing.financing_mode is FinancingMode.FIXED_15 else 30
    return loan_amount, rate_pct, int(term_years) * MONTHS_PER_YEAR


def _initial_property_cash_outlay_usd(scenario: Scenario) -> float:
    if scenario.property_selection.property_id is None:
        return 0.0
    purchase_price = _purchase_price_usd(scenario)
    financing = scenario.financing
    if financing.financing_mode is FinancingMode.CASH:
        return purchase_price
    if financing.loan_amount_usd is not None:
        return purchase_price - float(financing.loan_amount_usd)
    return purchase_price * (financing.down_payment_pct / 100)


def _purchase_price_usd(scenario: Scenario) -> float:
    purchase_price = scenario.property_selection.purchase_price_usd
    if purchase_price is None:
        property_id = scenario.property_selection.property_id
        if property_id is None:
            return 0.0
        raise ValueError(f"scenario {scenario.scenario_id!r} selects {property_id} without purchase_price_usd")
    return float(purchase_price)


def _private_equity_sale_requests_by_month(scenario: Scenario) -> dict[int, PrivateEquitySaleRequest]:
    requests: dict[int, PrivateEquitySaleRequest] = {}
    for event in scenario.events:
        if event.event_type not in {
            EventType.PRIVATE_EQUITY_SALE_REQUEST,
            EventType.PRIVATE_EQUITY_IPO,
            EventType.PRIVATE_EQUITY_ACQUISITION,
        }:
            continue
        requested = float(event.amount_usd) if event.amount_usd is not None else float("inf")
        current = requests.get(event.month_index)
        if current is not None and current.amount_usd >= requested:
            continue
        requests[event.month_index] = PrivateEquitySaleRequest(
            event_id=event.event_id, event_type=event.event_type, amount_usd=requested
        )
    return requests


def _private_equity_sale_proceeds_destination(policy: PrivateEquitySalePolicy) -> AccountType | AssetType:
    if policy.proceeds_destination == "generic_sp500_stock":
        return AssetType.GENERIC_SP500_STOCK
    return AccountType.CHECKING


def _initial_cash_usd(scenario: Scenario) -> float:
    return sum(
        account.balance_usd
        for account in scenario.initial_balance_sheet.accounts
        if account.account_type.value == "checking"
    )


def _initial_sp500_value_usd(scenario: Scenario) -> float:
    return sum(
        asset.value_usd
        for asset in scenario.initial_balance_sheet.assets
        if isinstance(asset, GenericSp500StockPosition)
    )


def _initial_sp500_cost_basis_usd(scenario: Scenario) -> float:
    return sum(
        asset.cost_basis_usd if asset.cost_basis_usd is not None else asset.value_usd
        for asset in scenario.initial_balance_sheet.assets
        if isinstance(asset, GenericSp500StockPosition)
    )


def _initial_private_equity_value_usd(scenario: Scenario) -> float:
    return sum(
        asset.value_usd for asset in scenario.initial_balance_sheet.assets if isinstance(asset, PrivateEquityPosition)
    )


def _initial_private_equity_cost_basis_usd(scenario: Scenario) -> float:
    return sum(
        asset.cost_basis_usd if asset.cost_basis_usd is not None else asset.value_usd
        for asset in scenario.initial_balance_sheet.assets
        if isinstance(asset, PrivateEquityPosition)
    )


def _initial_private_equity_units(scenario: Scenario) -> float:
    return sum(
        asset.units or 0.0
        for asset in scenario.initial_balance_sheet.assets
        if isinstance(asset, PrivateEquityPosition)
    )


def _has_partner(scenario: Scenario) -> bool:
    return any(actor.role is ActorRole.EQUITY_BUILDING_OCCUPANT for actor in scenario.actors)


def _primary_owner_actor_id(scenario: Scenario) -> str:
    for actor in scenario.actors:
        if actor.role is ActorRole.PRIMARY_OWNER:
            return actor.actor_id
    return "owner"


def _enabled_policy_of[PolicyT: _PolicyBase](scenario: Scenario, cls: type[PolicyT]) -> PolicyT | None:
    for policy in scenario.policies:
        if isinstance(policy, cls) and policy.enabled:
            return policy
    return None


def _enabled_policies_of[PolicyT: _PolicyBase](scenario: Scenario, cls: type[PolicyT]) -> tuple[PolicyT, ...]:
    return tuple(policy for policy in scenario.policies if isinstance(policy, cls) and policy.enabled)


def _scenario_hoa_monthly_usd(scenario: Scenario) -> float:
    for event in scenario.events:
        if isinstance(event, PropertyPurchaseEvent) and event.hoa_monthly_usd is not None:
            return float(event.hoa_monthly_usd)
    return 0.0


def _required_local_regulation(scenario: Scenario) -> LocalRegulation:
    location_id = scenario.location_id
    if location_id is None:
        raise ValueError(f"scenario {scenario.scenario_id!r} has real estate but no location_id")
    return local_regulation_for_location(location_id)


def _pct_fraction(value: float, name: str) -> float:
    if value < 0 or value > 100:
        raise ValueError(f"{name} must be in [0, 100]")
    return value / 100


def _accepted_summary(scenario: Scenario) -> ScenarioAcceptedSummary:
    return ScenarioAcceptedSummary(
        enabled=scenario.enabled,
        property_id=scenario.property_selection.property_id,
        location_id=scenario.location_id,
        actor_count=len(scenario.actors),
        event_count=len(scenario.events),
        policy_count=len(scenario.policies),
    )


def _disabled_result(scenario: Scenario) -> ScenarioResult:
    return ScenarioResult(
        scenario_id=scenario.scenario_id,
        scenario_label=scenario.label,
        status=ScenarioResultStatus.DISABLED,
        summary=_accepted_summary(scenario),
        warnings=("scenario disabled",),
    )


def _flat(values: np.ndarray) -> list[float]:
    return values.reshape(-1).tolist()


def _flat_bool(values: np.ndarray) -> list[bool]:
    return values.reshape(-1).astype(bool).tolist()


def _fan_columns(values: np.ndarray) -> ColumnarTable:
    matrix = np.asarray(values, dtype="float64")
    if matrix.ndim != 2:
        raise ValueError("fan values must be shaped (rollout, month)")
    month_index = np.arange(matrix.shape[1], dtype="int64")
    percentiles = (1, 2, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80, 85, 90, 95, 98, 99)
    percentile_values = np.nanpercentile(matrix, percentiles, axis=0)
    columns: dict[str, list[Any]] = {
        "month_index": month_index.tolist(),
        "year": (month_index / MONTHS_PER_YEAR).tolist(),
    }
    for index, percentile in enumerate(percentiles):
        columns[f"p{percentile:02d}"] = percentile_values[index].tolist()
    return ColumnarTable(row_count=int(matrix.shape[1]), columns=columns)


def scenario_set_from_body(body: dict[str, Any]) -> ScenarioSet:
    return ScenarioSet.model_validate(body)
