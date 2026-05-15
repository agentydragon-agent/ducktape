from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

import numpy as np

from augur.core.annual_tax import AnnualSaleTaxAllocation, annual_sale_tax_allocation
from augur.core.local_regulation import LocalRegulation, local_regulation_for_location
from augur.core.market_bundle import MarketBundle
from augur.core.policy_runtime import (
    LedgerEntryBatch,
    MortgagePaymentApplication,
    PrivateEquitySaleApplication,
    PrivateEquitySaleInstructionBatch,
    PrivateEquitySaleOpportunityBatch,
    actor_policy_programs,
    apply_debit_account_instruction,
    apply_generic_sp500_sale_instruction,
    apply_mortgage_payment,
    apply_partner_house_cost_contribution,
    apply_partner_ownership_accrual,
    apply_private_equity_sale_instruction,
    apply_property_operating_cash_flows,
    checking_floor_sell_public_stock_instruction,
    enabled_rules_of_type,
    monthly_spend_debit_instruction,
    partner_contribution_instruction,
    private_equity_sale_instruction,
    private_equity_sale_opportunity,
)
from augur.core.property_depreciation import rental_active_mask
from augur.core.property_sale import (
    PropertyDispositionArrays,
    empty_property_disposition_arrays,
    property_disposition_arrays,
)
from augur.core.property_tax import monthly_property_tax_usd
from augur.core.scenario_set import (
    AccountingDetailType,
    AccruePartnerEquityAction,
    ActorRole,
    AssetType,
    CheckingFloorSellPublicStockPolicy,
    FinancingMode,
    GenericSp500StockPosition,
    LiquidNetWorthFloorPrivateEquitySaleRule,
    MarketPathObservation,
    MonthlySpendAction,
    MonthlySpendDecision,
    MonthlySpendPolicy,
    OccupancyMode,
    PartnerContributionDecision,
    PartnerEquityAccrualPolicy,
    PayMortgageAction,
    Policy,
    PrivateEquityPosition,
    PrivateEquitySaleDecision,
    PrivateEquitySaleDecisionReason,
    PrivateEquitySaleOpportunityObservation,
    PrivateEquitySalePolicy,
    PropertyPurchaseEvent,
    PropertySaleBasisGainDetail,
    RentalMode,
    Scenario,
    SellPrivateEquityAction,
    SellPublicStockDecision,
    SellSp500Action,
    SettlePropertySaleAction,
    SimulationAccountingDetail,
    SimulationAction,
    SimulationBalanceSnapshot,
    SimulationLedgerEntry,
    SimulationMarketObservation,
    SimulationPolicyDecision,
    TaxPaymentAllocationDetail,
    TransferPartnerContributionAction,
)
from augur.core.schemas import ColumnarTable

MONTHS_PER_YEAR = 12
MORTGAGE_SERVICING_POLICY_ID = "mortgage_servicing"
PROPERTY_OPERATING_CASH_FLOW_POLICY_ID = "property_operating_cash_flow"
PROPERTY_SALE_SETTLEMENT_POLICY_ID = "property_sale_settlement"
ANNUAL_TAX_ACCOUNTING_POLICY_ID = "annual_tax_accounting"


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
    generic_sp500_sale_tax_usd: np.ndarray
    checking_floor_action_usd: np.ndarray
    checking_floor_shortfall_usd: np.ndarray
    private_equity_value_usd: np.ndarray
    private_equity_sale_opportunity_value_usd: np.ndarray
    private_equity_sale_usd: np.ndarray
    private_equity_sale_basis_usd: np.ndarray
    private_equity_sale_tax_usd: np.ndarray
    federal_income_tax_usd: np.ndarray
    california_income_tax_usd: np.ndarray
    total_income_tax_usd: np.ndarray
    private_equity_sale_opportunity_event: np.ndarray
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
    property_sale_adjusted_basis_usd: np.ndarray
    realized_property_gain_usd: np.ndarray
    property_sale_capital_gain_usd: np.ndarray
    property_sale_capital_gain_exclusion_usd: np.ndarray
    taxable_property_capital_gain_usd: np.ndarray
    taxable_property_gain_usd: np.ndarray
    depreciation_recapture_usd: np.ndarray
    net_property_sale_cash_flow_usd: np.ndarray
    home_equity_usd: np.ndarray
    owner_home_equity_claim_usd: np.ndarray
    partner_home_equity_claim_usd: np.ndarray
    partner_contribution_usd: np.ndarray
    partner_contribution_used_usd: np.ndarray
    partner_unallocated_excess_usd: np.ndarray
    partner_house_costs_usd: np.ndarray
    partner_principal_credit_usd: np.ndarray
    owner_principal_credit_usd: np.ndarray
    partner_house_cost_share: np.ndarray
    partner_equity_ledger_usd: np.ndarray
    owner_equity_ledger_usd: np.ndarray
    partner_ownership_pct: np.ndarray
    liquid_net_worth_usd: np.ndarray
    net_worth_usd: np.ndarray
    partner_present: np.ndarray
    monthly_spend_usd: np.ndarray
    actions: tuple[SimulationAction, ...]
    policy_decisions: tuple[SimulationPolicyDecision, ...]
    market_observations: tuple[SimulationMarketObservation, ...]
    ledger_entries: tuple[SimulationLedgerEntry, ...]
    balance_snapshots: tuple[SimulationBalanceSnapshot, ...]
    accounting_details: tuple[SimulationAccountingDetail, ...]

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
                "generic_sp500_sale_tax_usd": _flat(self.generic_sp500_sale_tax_usd),
                "checking_floor_action_usd": _flat(self.checking_floor_action_usd),
                "checking_floor_shortfall_usd": _flat(self.checking_floor_shortfall_usd),
                "private_equity_value_usd": _flat(self.private_equity_value_usd),
                "private_equity_sale_opportunity_value_usd": _flat(self.private_equity_sale_opportunity_value_usd),
                "private_equity_sale_usd": _flat(self.private_equity_sale_usd),
                "private_equity_sale_basis_usd": _flat(self.private_equity_sale_basis_usd),
                "private_equity_sale_tax_usd": _flat(self.private_equity_sale_tax_usd),
                "federal_income_tax_usd": _flat(self.federal_income_tax_usd),
                "california_income_tax_usd": _flat(self.california_income_tax_usd),
                "total_income_tax_usd": _flat(self.total_income_tax_usd),
                "private_equity_sale_opportunity_event": _flat_bool(self.private_equity_sale_opportunity_event),
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
                "property_sale_adjusted_basis_usd": _flat(self.property_sale_adjusted_basis_usd),
                "realized_property_gain_usd": _flat(self.realized_property_gain_usd),
                "property_sale_capital_gain_usd": _flat(self.property_sale_capital_gain_usd),
                "property_sale_capital_gain_exclusion_usd": _flat(self.property_sale_capital_gain_exclusion_usd),
                "taxable_property_capital_gain_usd": _flat(self.taxable_property_capital_gain_usd),
                "taxable_property_gain_usd": _flat(self.taxable_property_gain_usd),
                "depreciation_recapture_usd": _flat(self.depreciation_recapture_usd),
                "net_property_sale_cash_flow_usd": _flat(self.net_property_sale_cash_flow_usd),
                "home_equity_usd": _flat(self.home_equity_usd),
                "owner_home_equity_claim_usd": _flat(self.owner_home_equity_claim_usd),
                "partner_home_equity_claim_usd": _flat(self.partner_home_equity_claim_usd),
                "partner_contribution_usd": _flat(self.partner_contribution_usd),
                "partner_contribution_used_usd": _flat(self.partner_contribution_used_usd),
                "partner_unallocated_excess_usd": _flat(self.partner_unallocated_excess_usd),
                "partner_house_costs_usd": _flat(self.partner_house_costs_usd),
                "partner_principal_credit_usd": _flat(self.partner_principal_credit_usd),
                "owner_principal_credit_usd": _flat(self.owner_principal_credit_usd),
                "partner_house_cost_share": _flat(self.partner_house_cost_share),
                "partner_equity_ledger_usd": _flat(self.partner_equity_ledger_usd),
                "owner_equity_ledger_usd": _flat(self.owner_equity_ledger_usd),
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
                "total_generic_sp500_sale_tax_usd": np.sum(self.generic_sp500_sale_tax_usd, axis=1).tolist(),
                "final_checking_floor_shortfall_usd": self.checking_floor_shortfall_usd[:, final].tolist(),
                "final_private_equity_value_usd": self.private_equity_value_usd[:, final].tolist(),
                "final_private_equity_sale_opportunity_value_usd": (
                    self.private_equity_sale_opportunity_value_usd[:, final].tolist()
                ),
                "total_private_equity_sale_usd": np.sum(self.private_equity_sale_usd, axis=1).tolist(),
                "total_private_equity_sale_basis_usd": np.sum(self.private_equity_sale_basis_usd, axis=1).tolist(),
                "total_private_equity_sale_tax_usd": np.sum(self.private_equity_sale_tax_usd, axis=1).tolist(),
                "total_federal_income_tax_usd": np.sum(self.federal_income_tax_usd, axis=1).tolist(),
                "total_california_income_tax_usd": np.sum(self.california_income_tax_usd, axis=1).tolist(),
                "total_income_tax_usd": np.sum(self.total_income_tax_usd, axis=1).tolist(),
                "final_property_value_usd": self.property_value_usd[:, final].tolist(),
                "final_mortgage_balance_usd": self.mortgage_balance_usd[:, final].tolist(),
                "final_home_equity_usd": self.home_equity_usd[:, final].tolist(),
                "final_owner_home_equity_claim_usd": self.owner_home_equity_claim_usd[:, final].tolist(),
                "final_partner_home_equity_claim_usd": self.partner_home_equity_claim_usd[:, final].tolist(),
                "final_partner_ownership_pct": self.partner_ownership_pct[:, final].tolist(),
                "total_partner_contribution_used_usd": np.sum(self.partner_contribution_used_usd, axis=1).tolist(),
                "total_partner_principal_credit_usd": np.sum(self.partner_principal_credit_usd, axis=1).tolist(),
                "total_owner_principal_credit_usd": np.sum(self.owner_principal_credit_usd, axis=1).tolist(),
                "final_partner_equity_ledger_usd": self.partner_equity_ledger_usd[:, final].tolist(),
                "final_owner_equity_ledger_usd": self.owner_equity_ledger_usd[:, final].tolist(),
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
                "total_property_sale_adjusted_basis_usd": np.sum(
                    self.property_sale_adjusted_basis_usd, axis=1
                ).tolist(),
                "total_realized_property_gain_usd": np.sum(self.realized_property_gain_usd, axis=1).tolist(),
                "total_property_sale_capital_gain_usd": np.sum(self.property_sale_capital_gain_usd, axis=1).tolist(),
                "total_property_sale_capital_gain_exclusion_usd": np.sum(
                    self.property_sale_capital_gain_exclusion_usd, axis=1
                ).tolist(),
                "total_taxable_property_capital_gain_usd": np.sum(
                    self.taxable_property_capital_gain_usd, axis=1
                ).tolist(),
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
            "partner_principal_credit_usd": _fan_columns(self.partner_principal_credit_usd),
            "partner_equity_ledger_usd": _fan_columns(self.partner_equity_ledger_usd),
            "owner_equity_ledger_usd": _fan_columns(self.owner_equity_ledger_usd),
            "partner_ownership_pct": _fan_columns(self.partner_ownership_pct),
            "mortgage_balance_usd": _fan_columns(self.mortgage_balance_usd),
            "rental_income_usd": _fan_columns(self.rental_income_usd),
            "net_property_cash_flow_usd": _fan_columns(self.net_property_cash_flow_usd),
            "property_sale_net_proceeds_usd": _fan_columns(self.property_sale_net_proceeds_usd),
            "net_property_sale_cash_flow_usd": _fan_columns(self.net_property_sale_cash_flow_usd),
            "private_equity_value_usd": _fan_columns(self.private_equity_value_usd),
            "private_equity_sale_opportunity_value_usd": _fan_columns(self.private_equity_sale_opportunity_value_usd),
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
    ledger_entries: tuple[LedgerEntryBatch, ...]


@dataclass(frozen=True)
class PartnerEquityAgreementArrays:
    policy: PartnerEquityAccrualPolicy
    property_id: str
    recipient_actor_id: str
    contribution_usd: np.ndarray
    contribution_used_usd: np.ndarray
    unallocated_excess_usd: np.ndarray
    house_costs_usd: np.ndarray
    mortgage_payment_usd: np.ndarray
    mortgage_interest_usd: np.ndarray
    mortgage_principal_usd: np.ndarray
    principal_credit_usd: np.ndarray
    owner_principal_usd: np.ndarray
    house_cost_share: np.ndarray
    partner_equity_ledger_usd: np.ndarray
    owner_equity_ledger_usd: np.ndarray
    ownership_pct: np.ndarray
    home_equity_claim_usd: np.ndarray
    owner_home_equity_claim_usd: np.ndarray


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
    owner_principal_usd: np.ndarray
    house_cost_share: np.ndarray
    partner_equity_ledger_usd: np.ndarray
    owner_equity_ledger_usd: np.ndarray
    ownership_pct: np.ndarray
    home_equity_claim_usd: np.ndarray
    owner_home_equity_claim_usd: np.ndarray
    agreements: tuple[PartnerEquityAgreementArrays, ...]


@dataclass(frozen=True)
class Sp500SaleActionRecord:
    month_position: int
    month_index: int
    policy: Policy
    amount_usd: np.ndarray
    basis_usd: np.ndarray
    shortfall_usd: np.ndarray


@dataclass(frozen=True)
class PrivateEquitySaleActionRecord:
    month_position: int
    month_index: int
    instruction: PrivateEquitySaleInstructionBatch
    sale_application: PrivateEquitySaleApplication


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
    generic_sp500_sale_gain = np.zeros((rollout_count, month_count), dtype="float64")
    generic_sp500_sale_tax = np.zeros((rollout_count, month_count), dtype="float64")
    checking_floor_shortfall = np.zeros((rollout_count, month_count), dtype="float64")
    private_equity_value = np.zeros((rollout_count, month_count), dtype="float64")
    private_equity_sale_opportunity_value = np.zeros((rollout_count, month_count), dtype="float64")
    private_equity_sale_taxable_gain = np.zeros((rollout_count, month_count), dtype="float64")
    private_equity_sale_tax = np.zeros((rollout_count, month_count), dtype="float64")
    cash = np.zeros((rollout_count, month_count), dtype="float64")
    policy_programs = actor_policy_programs(scenario)
    private_equity_sale_opportunity_event = market_bundle.private_equity_sale_opportunity_mask.copy()
    spend_policies = enabled_rules_of_type(policy_programs, MonthlySpendPolicy)
    checking_policies = enabled_rules_of_type(policy_programs, CheckingFloorSellPublicStockPolicy)
    private_equity_sale_policies = enabled_rules_of_type(policy_programs, PrivateEquitySalePolicy)
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
    policy_decisions: list[SimulationPolicyDecision] = []
    market_observations: list[SimulationMarketObservation] = list(_market_path_observations(scenario, market_bundle))
    ledger_entries: list[SimulationLedgerEntry] = []
    balance_snapshots: list[SimulationBalanceSnapshot] = []
    accounting_details: list[SimulationAccountingDetail] = []
    sp500_sale_action_records: list[Sp500SaleActionRecord] = []
    private_equity_sale_action_records: list[PrivateEquitySaleActionRecord] = []

    for month in range(month_count):
        current_cash = current_cash + disposition.net_property_sale_cash_flow_usd[:, month]
        if month > 0:
            current_cash = (
                current_cash + net_property_cash_flow[:, month] + partner_equity.contribution_used_usd[:, month]
            )

        if month > 0:
            for spend_policy in spend_policies:
                spend_decision = monthly_spend_debit_instruction(
                    spend_policy, inflation_multiplier=market_bundle.inflation_multipliers[:, month]
                )
                spend_application = apply_debit_account_instruction(spend_decision.debit, current_cash_usd=current_cash)
                current_cash = spend_application.current_cash_usd
                spend_ledger = spend_application.ledger_entries[0]
                _record_ledger_entry_month(ledger_entries, month_index=int(month_index[month]), entry=spend_ledger)
                _record_monthly_spend_decisions(
                    policy_decisions,
                    month_index=int(month_index[month]),
                    policy=spend_policy,
                    amount_usd=spend_decision.debit.amount_usd,
                    inflation_multiplier=spend_decision.inflation_multiplier,
                )
                _record_monthly_spend_actions(
                    actions,
                    month_index=int(month_index[month]),
                    policy=spend_policy,
                    amount_usd=spend_application.debit_usd,
                    inflation_multiplier=spend_decision.inflation_multiplier,
                )

        private_equity_value_before_sale = (
            initial_private_equity
            * remaining_private_equity_fraction
            * market_bundle.private_equity_value_multipliers[:, month]
        )
        market_opportunity = private_equity_sale_opportunity(
            sale_opportunity_mask=market_bundle.private_equity_sale_opportunity_mask[:, month],
            private_equity_value_before_sale_usd=private_equity_value_before_sale,
        )
        _record_private_equity_sale_opportunity_observations(
            market_observations, month_index=int(month_index[month]), opportunity=market_opportunity
        )
        market_sale_opportunity_value = market_opportunity.sale_opportunity_value_usd
        private_equity_sale_month = np.zeros(rollout_count, dtype="float64")
        private_equity_sale_taxable_gain_month = np.zeros(rollout_count, dtype="float64")
        private_equity_sale_tax_month = np.zeros(rollout_count, dtype="float64")
        for private_equity_sale_policy in private_equity_sale_policies:
            current_private_equity_value = (
                initial_private_equity
                * remaining_private_equity_fraction
                * market_bundle.private_equity_value_multipliers[:, month]
            )
            current_opportunity = private_equity_sale_opportunity(
                sale_opportunity_mask=market_bundle.private_equity_sale_opportunity_mask[:, month],
                private_equity_value_before_sale_usd=current_private_equity_value,
            )
            liquid_net_worth = current_cash + remaining_sp500_units * market_bundle.generic_sp500_multipliers[:, month]
            sale_instruction = private_equity_sale_instruction(
                private_equity_sale_policy, opportunity=current_opportunity, liquid_net_worth_usd=liquid_net_worth
            )
            _record_private_equity_sale_decisions(
                policy_decisions,
                month_index=int(month_index[month]),
                policy=private_equity_sale_policy,
                instruction=sale_instruction,
                opportunity=current_opportunity,
                liquid_net_worth_usd=liquid_net_worth,
            )
            sale_application = apply_private_equity_sale_instruction(
                sale_instruction,
                opportunity=current_opportunity,
                remaining_basis_usd=remaining_private_equity_basis,
                remaining_units=remaining_private_equity_units,
                remaining_fraction=remaining_private_equity_fraction,
                cap_gains_rate_pct=0.0,
            )
            if sale_instruction.proceeds_destination is AssetType.GENERIC_SP500_STOCK:
                sp500_multiplier = market_bundle.generic_sp500_multipliers[:, month]
                remaining_sp500_units = remaining_sp500_units + np.divide(
                    sale_application.after_tax_proceeds_usd,
                    sp500_multiplier,
                    out=np.zeros_like(sale_application.after_tax_proceeds_usd),
                    where=sp500_multiplier > 0,
                )
                remaining_sp500_basis = remaining_sp500_basis + sale_application.after_tax_proceeds_usd
            else:
                current_cash = current_cash + sale_application.after_tax_proceeds_usd
            private_equity_sale_action_records.append(
                PrivateEquitySaleActionRecord(
                    month_position=month,
                    month_index=int(month_index[month]),
                    instruction=sale_instruction,
                    sale_application=sale_application,
                )
            )
            remaining_private_equity_fraction = sale_application.remaining_fraction
            remaining_private_equity_basis = sale_application.remaining_basis_usd
            remaining_private_equity_units = sale_application.remaining_units
            private_equity_sale_month = private_equity_sale_month + sale_application.sale_usd
            private_equity_sale_taxable_gain_month = (
                private_equity_sale_taxable_gain_month + sale_application.taxable_gain_usd
            )
            private_equity_sale_tax_month = private_equity_sale_tax_month + sale_application.estimated_tax_usd

        sp500_multiplier = market_bundle.generic_sp500_multipliers[:, month]
        sp500_sale = np.zeros(rollout_count, dtype="float64")
        sp500_basis = np.zeros(rollout_count, dtype="float64")
        sp500_shortfall = np.zeros(rollout_count, dtype="float64")
        for checking_policy in checking_policies:
            sp500_sale_instruction = checking_floor_sell_public_stock_instruction(
                checking_policy, current_cash_usd=current_cash
            )
            _record_sell_public_stock_decisions(
                policy_decisions,
                month_index=int(month_index[month]),
                policy=checking_policy,
                current_cash_usd=current_cash,
                requested_amount_usd=sp500_sale_instruction.requested_amount_usd,
            )
            sp500_sale_application = apply_generic_sp500_sale_instruction(
                sp500_sale_instruction,
                current_cash_usd=current_cash,
                remaining_units=remaining_sp500_units,
                remaining_basis_usd=remaining_sp500_basis,
                sp500_unit_price_usd=sp500_multiplier,
            )
            current_cash = sp500_sale_application.current_cash_usd
            remaining_sp500_units = sp500_sale_application.remaining_units
            remaining_sp500_basis = sp500_sale_application.remaining_basis_usd
            sp500_sale = sp500_sale + sp500_sale_application.sale_usd
            sp500_basis = sp500_basis + sp500_sale_application.basis_usd
            sp500_shortfall = np.maximum(sp500_shortfall, sp500_sale_application.shortfall_usd)
            sp500_sale_action_records.append(
                Sp500SaleActionRecord(
                    month_position=month,
                    month_index=int(month_index[month]),
                    policy=checking_policy,
                    amount_usd=sp500_sale_application.sale_usd,
                    basis_usd=sp500_sale_application.basis_usd,
                    shortfall_usd=sp500_sale_application.shortfall_usd,
                )
            )
        sp500_value_after_sale = remaining_sp500_units * sp500_multiplier

        cash[:, month] = current_cash
        generic_sp500_value[:, month] = sp500_value_after_sale
        generic_sp500_sale_gain[:, month] = sp500_sale - sp500_basis
        checking_floor_shortfall[:, month] = sp500_shortfall
        private_equity_sale_taxable_gain[:, month] = private_equity_sale_taxable_gain_month
        private_equity_sale_tax[:, month] = private_equity_sale_tax_month
        private_equity_sale_opportunity_value[:, month] = np.maximum(
            0.0, market_sale_opportunity_value - private_equity_sale_month
        )
        private_equity_value[:, month] = private_equity_value_before_sale - private_equity_sale_month

    annual_tax = annual_sale_tax_allocation(
        scenario.tax_profile,
        month_index=month_index,
        property_depreciation_recapture_usd=disposition.depreciation_recapture_usd,
        taxable_property_capital_gain_usd=disposition.taxable_property_capital_gain_usd,
        generic_sp500_sale_gain_usd=generic_sp500_sale_gain,
        private_equity_sale_taxable_gain_usd=private_equity_sale_taxable_gain,
    )
    generic_sp500_sale_tax = annual_tax.generic_sp500_sale_tax_usd
    adjusted_private_equity_sale_tax = annual_tax.private_equity_sale_tax_usd
    property_sale_tax = annual_tax.property_sale_tax_usd
    property_sale_net_proceeds = (
        disposition.property_sale_gross_usd
        - disposition.sale_closing_cost_usd
        - disposition.property_sale_debt_payoff_usd
        - property_sale_tax
    )
    partner_equity = _settle_partner_equity_on_property_sale(
        partner_equity, sale_month=disposition.sale_month, property_sale_net_proceeds_usd=property_sale_net_proceeds
    )
    tax_cash_adjustment = np.cumsum(
        (disposition.property_sale_tax_usd - property_sale_tax)
        + (private_equity_sale_tax - adjusted_private_equity_sale_tax)
        - generic_sp500_sale_tax,
        axis=1,
    )
    cash = cash + tax_cash_adjustment
    private_equity_sale_tax = adjusted_private_equity_sale_tax

    partner_present = np.full((rollout_count, month_count), _has_partner(scenario), dtype=np.bool_)
    partner_home_equity_claim = partner_equity.home_equity_claim_usd
    owner_home_equity_claim = partner_equity.owner_home_equity_claim_usd
    if disposition.sale_month is None:
        owner_home_equity_claim_for_net_worth = owner_home_equity_claim
    else:
        unsold_mask = (month_index < disposition.sale_month).astype("float64")
        unsold_mask = np.broadcast_to(unsold_mask[None, :], (rollout_count, month_count))
        owner_home_equity_claim_for_net_worth = owner_home_equity_claim * unsold_mask
    liquid_net_worth = cash + generic_sp500_value
    net_worth = cash + generic_sp500_value + private_equity_value + owner_home_equity_claim_for_net_worth
    _record_property_sale_actions(
        actions,
        scenario=scenario,
        disposition=disposition,
        tax_usd=property_sale_tax,
        net_proceeds_usd=property_sale_net_proceeds,
    )
    _record_property_sale_ledger_entries(
        ledger_entries,
        scenario=scenario,
        disposition=disposition,
        tax_usd=property_sale_tax,
        net_proceeds_usd=property_sale_net_proceeds,
    )
    _record_property_sale_accounting_details(accounting_details, scenario=scenario, disposition=disposition)
    _record_tax_payment_allocation_details(
        accounting_details,
        scenario=scenario,
        month_index=month_index,
        annual_tax=annual_tax,
        property_depreciation_recapture_usd=disposition.depreciation_recapture_usd,
        taxable_property_capital_gain_usd=disposition.taxable_property_capital_gain_usd,
        generic_sp500_sale_gain_usd=generic_sp500_sale_gain,
        private_equity_sale_taxable_gain_usd=private_equity_sale_taxable_gain,
    )
    for sp500_sale_action_record in sp500_sale_action_records:
        source_tax = _tax_share_for_sale_action(
            source_tax_usd=generic_sp500_sale_tax[:, sp500_sale_action_record.month_position],
            action_taxable_income_usd=np.maximum(
                0.0, sp500_sale_action_record.amount_usd - sp500_sale_action_record.basis_usd
            ),
            source_taxable_income_usd=np.maximum(
                0.0, generic_sp500_sale_gain[:, sp500_sale_action_record.month_position]
            ),
        )
        _record_sp500_sale_ledger_entries(
            ledger_entries,
            month_index=sp500_sale_action_record.month_index,
            policy=sp500_sale_action_record.policy,
            amount_usd=sp500_sale_action_record.amount_usd,
            basis_usd=sp500_sale_action_record.basis_usd,
            tax_usd=source_tax,
        )
        _record_sp500_sale_actions(
            actions,
            month_index=sp500_sale_action_record.month_index,
            policy=sp500_sale_action_record.policy,
            amount_usd=sp500_sale_action_record.amount_usd,
            basis_usd=sp500_sale_action_record.basis_usd,
            tax_usd=source_tax,
            shortfall_usd=sp500_sale_action_record.shortfall_usd,
        )
    for private_equity_sale_action_record in private_equity_sale_action_records:
        source_tax = _tax_share_for_sale_action(
            source_tax_usd=private_equity_sale_tax[:, private_equity_sale_action_record.month_position],
            action_taxable_income_usd=private_equity_sale_action_record.sale_application.taxable_gain_usd,
            source_taxable_income_usd=private_equity_sale_taxable_gain[
                :, private_equity_sale_action_record.month_position
            ],
        )
        _record_private_equity_sale_ledger_entries(
            ledger_entries,
            month_index=private_equity_sale_action_record.month_index,
            instruction=private_equity_sale_action_record.instruction,
            sale_application=private_equity_sale_action_record.sale_application,
            tax_usd=source_tax,
        )
        _record_private_equity_sale_actions(
            actions,
            month_index=private_equity_sale_action_record.month_index,
            instruction=private_equity_sale_action_record.instruction,
            sale_application=private_equity_sale_action_record.sale_application,
            estimated_tax_usd=source_tax,
        )
    _record_partner_agreement_actions(actions, month_index=month_index, partner_equity=partner_equity)
    _record_partner_contribution_decisions(policy_decisions, month_index=month_index, partner_equity=partner_equity)
    _record_partner_agreement_ledger_detail(
        ledger_entries,
        balance_snapshots,
        month_index=month_index,
        partner_equity=partner_equity,
        owner_actor_id=_primary_owner_actor_id(scenario),
    )
    mortgage_application = apply_mortgage_payment(
        actor_id=_primary_owner_actor_id(scenario),
        policy_id=MORTGAGE_SERVICING_POLICY_ID,
        mortgage_payment_usd=property_cash_flow.mortgage_payment_usd * property_live_mask,
        mortgage_interest_usd=mortgage_interest,
        mortgage_principal_usd=mortgage_principal,
        mortgage_balance_after_usd=mortgage_balance,
    )
    _record_mortgage_payment_actions(actions, month_index=month_index, mortgage_application=mortgage_application)
    _record_ledger_entry_batches(ledger_entries, month_index=month_index, entries=mortgage_application.ledger_entries)
    _record_ledger_entry_batches(
        ledger_entries,
        month_index=month_index,
        entries=property_cash_flow.ledger_entries,
        amount_multiplier=property_live_mask,
    )
    monthly_spend_from_ledger = -_ledger_amount_matrix(
        ledger_entries, rollout_count=rollout_count, month_index=month_index, domain="cash", category="monthly_spend"
    )
    mortgage_interest_from_ledger = -_ledger_amount_matrix(
        ledger_entries,
        rollout_count=rollout_count,
        month_index=month_index,
        domain="cash",
        category="mortgage_interest",
    )
    mortgage_principal_from_ledger = -_ledger_amount_matrix(
        ledger_entries,
        rollout_count=rollout_count,
        month_index=month_index,
        domain="cash",
        category="mortgage_principal",
    )
    mortgage_payment_from_ledger = mortgage_interest_from_ledger + mortgage_principal_from_ledger
    property_tax_from_ledger = -_ledger_amount_matrix(
        ledger_entries, rollout_count=rollout_count, month_index=month_index, domain="cash", category="property_tax"
    )
    hoa_from_ledger = -_ledger_amount_matrix(
        ledger_entries, rollout_count=rollout_count, month_index=month_index, domain="cash", category="hoa"
    )
    insurance_from_ledger = -_ledger_amount_matrix(
        ledger_entries, rollout_count=rollout_count, month_index=month_index, domain="cash", category="insurance"
    )
    maintenance_from_ledger = -_ledger_amount_matrix(
        ledger_entries, rollout_count=rollout_count, month_index=month_index, domain="cash", category="maintenance"
    )
    rental_gross_income_from_ledger = _ledger_amount_matrix(
        ledger_entries,
        rollout_count=rollout_count,
        month_index=month_index,
        domain="rental",
        category="rental_gross_income",
    )
    rental_vacancy_loss_from_ledger = -_ledger_amount_matrix(
        ledger_entries,
        rollout_count=rollout_count,
        month_index=month_index,
        domain="rental",
        category="rental_vacancy_loss",
    )
    rental_income_from_ledger = _ledger_amount_matrix(
        ledger_entries, rollout_count=rollout_count, month_index=month_index, domain="cash", category="rental_income"
    )
    rental_management_fee_from_ledger = -_ledger_amount_matrix(
        ledger_entries,
        rollout_count=rollout_count,
        month_index=month_index,
        domain="cash",
        category="rental_management_fee",
    )
    rental_leasing_fee_from_ledger = -_ledger_amount_matrix(
        ledger_entries,
        rollout_count=rollout_count,
        month_index=month_index,
        domain="cash",
        category="rental_leasing_fee",
    )
    property_carrying_cost_from_ledger = (
        property_tax_from_ledger
        + hoa_from_ledger
        + insurance_from_ledger
        + maintenance_from_ledger
        + rental_management_fee_from_ledger
        + rental_leasing_fee_from_ledger
    )
    net_property_cash_flow_from_ledger = (
        rental_income_from_ledger - property_carrying_cost_from_ledger - mortgage_payment_from_ledger
    )
    generic_sp500_sale_from_ledger = -_ledger_amount_matrix(
        ledger_entries,
        rollout_count=rollout_count,
        month_index=month_index,
        domain="asset",
        category="generic_sp500_sale",
    )
    generic_sp500_sale_basis_from_ledger = -_ledger_amount_matrix(
        ledger_entries,
        rollout_count=rollout_count,
        month_index=month_index,
        domain="basis",
        category="generic_sp500_sale_basis",
    )
    generic_sp500_sale_tax_from_ledger = -_ledger_amount_matrix(
        ledger_entries,
        rollout_count=rollout_count,
        month_index=month_index,
        domain="tax",
        category="generic_sp500_sale_tax",
    )
    private_equity_sale_from_ledger = -_ledger_amount_matrix(
        ledger_entries,
        rollout_count=rollout_count,
        month_index=month_index,
        domain="asset",
        category="private_equity_sale",
    )
    private_equity_sale_basis_from_ledger = -_ledger_amount_matrix(
        ledger_entries,
        rollout_count=rollout_count,
        month_index=month_index,
        domain="basis",
        category="private_equity_sale_basis",
    )
    private_equity_sale_tax_from_ledger = -_ledger_amount_matrix(
        ledger_entries,
        rollout_count=rollout_count,
        month_index=month_index,
        domain="tax",
        category="private_equity_sale_tax",
    )
    property_sale_gross_from_ledger = _ledger_amount_matrix(
        ledger_entries,
        rollout_count=rollout_count,
        month_index=month_index,
        domain="property_sale",
        category="property_sale_gross",
    )
    sale_closing_cost_from_ledger = -_ledger_amount_matrix(
        ledger_entries,
        rollout_count=rollout_count,
        month_index=month_index,
        domain="property_sale",
        category="sale_closing_cost",
    )
    property_sale_debt_payoff_from_ledger = -_ledger_amount_matrix(
        ledger_entries,
        rollout_count=rollout_count,
        month_index=month_index,
        domain="property_sale",
        category="property_sale_debt_payoff",
    )
    property_sale_tax_from_ledger = -_ledger_amount_matrix(
        ledger_entries, rollout_count=rollout_count, month_index=month_index, domain="tax", category="property_sale_tax"
    )
    property_sale_net_proceeds_from_ledger = _ledger_amount_matrix(
        ledger_entries,
        rollout_count=rollout_count,
        month_index=month_index,
        domain="cash",
        category="property_sale_net_proceeds",
    )
    partner_contribution_from_ledger = -_ledger_amount_matrix(
        ledger_entries,
        rollout_count=rollout_count,
        month_index=month_index,
        domain="cash",
        category="partner_contribution_transfer",
    )
    partner_contribution_used_from_ledger = _ledger_amount_matrix(
        ledger_entries,
        rollout_count=rollout_count,
        month_index=month_index,
        domain="cash",
        category="partner_contribution_used_for_house_costs",
    )
    partner_unallocated_excess_from_ledger = _ledger_amount_matrix(
        ledger_entries,
        rollout_count=rollout_count,
        month_index=month_index,
        domain="escrow",
        category="partner_contribution_unallocated",
    )
    partner_principal_credit_from_ledger = _ledger_amount_matrix(
        ledger_entries,
        rollout_count=rollout_count,
        month_index=month_index,
        domain="ownership",
        category="partner_principal_credit",
    )
    federal_income_tax_from_accounting = _accounting_detail_amount_matrix(
        accounting_details,
        rollout_count=rollout_count,
        month_index=month_index,
        detail_type=AccountingDetailType.TAX_PAYMENT_ALLOCATION,
        amount_field="federal_income_tax_usd",
    )
    california_income_tax_from_accounting = _accounting_detail_amount_matrix(
        accounting_details,
        rollout_count=rollout_count,
        month_index=month_index,
        detail_type=AccountingDetailType.TAX_PAYMENT_ALLOCATION,
        amount_field="california_income_tax_usd",
    )
    total_income_tax_from_accounting = _accounting_detail_amount_matrix(
        accounting_details,
        rollout_count=rollout_count,
        month_index=month_index,
        detail_type=AccountingDetailType.TAX_PAYMENT_ALLOCATION,
        amount_field="total_income_tax_usd",
    )
    property_sale_adjusted_basis_from_accounting = _accounting_detail_amount_matrix(
        accounting_details,
        rollout_count=rollout_count,
        month_index=month_index,
        detail_type=AccountingDetailType.PROPERTY_SALE_BASIS_GAIN,
        amount_field="adjusted_basis_usd",
    )
    realized_property_gain_from_accounting = _accounting_detail_amount_matrix(
        accounting_details,
        rollout_count=rollout_count,
        month_index=month_index,
        detail_type=AccountingDetailType.PROPERTY_SALE_BASIS_GAIN,
        amount_field="realized_gain_usd",
    )
    property_sale_capital_gain_from_accounting = _accounting_detail_amount_matrix(
        accounting_details,
        rollout_count=rollout_count,
        month_index=month_index,
        detail_type=AccountingDetailType.PROPERTY_SALE_BASIS_GAIN,
        amount_field="capital_gain_usd",
    )
    property_sale_capital_gain_exclusion_from_accounting = _accounting_detail_amount_matrix(
        accounting_details,
        rollout_count=rollout_count,
        month_index=month_index,
        detail_type=AccountingDetailType.PROPERTY_SALE_BASIS_GAIN,
        amount_field="capital_gain_exclusion_usd",
    )
    taxable_property_capital_gain_from_accounting = _accounting_detail_amount_matrix(
        accounting_details,
        rollout_count=rollout_count,
        month_index=month_index,
        detail_type=AccountingDetailType.PROPERTY_SALE_BASIS_GAIN,
        amount_field="taxable_capital_gain_usd",
    )
    taxable_property_gain_from_accounting = _accounting_detail_amount_matrix(
        accounting_details,
        rollout_count=rollout_count,
        month_index=month_index,
        detail_type=AccountingDetailType.PROPERTY_SALE_BASIS_GAIN,
        amount_field="taxable_gain_usd",
    )
    depreciation_recapture_from_accounting = _accounting_detail_amount_matrix(
        accounting_details,
        rollout_count=rollout_count,
        month_index=month_index,
        detail_type=AccountingDetailType.PROPERTY_SALE_BASIS_GAIN,
        amount_field="depreciation_recapture_usd",
    )
    return ScenarioRunArrays(
        scenario_id=scenario.scenario_id,
        scenario_label=scenario.label,
        month_index=month_index,
        cash_usd=cash,
        generic_sp500_value_usd=generic_sp500_value,
        generic_sp500_sale_usd=generic_sp500_sale_from_ledger,
        generic_sp500_sale_basis_usd=generic_sp500_sale_basis_from_ledger,
        generic_sp500_sale_gain_usd=generic_sp500_sale_from_ledger - generic_sp500_sale_basis_from_ledger,
        generic_sp500_sale_tax_usd=generic_sp500_sale_tax_from_ledger,
        checking_floor_action_usd=generic_sp500_sale_from_ledger,
        checking_floor_shortfall_usd=checking_floor_shortfall,
        private_equity_value_usd=private_equity_value,
        private_equity_sale_opportunity_value_usd=private_equity_sale_opportunity_value,
        private_equity_sale_usd=private_equity_sale_from_ledger,
        private_equity_sale_basis_usd=private_equity_sale_basis_from_ledger,
        private_equity_sale_tax_usd=private_equity_sale_tax_from_ledger,
        federal_income_tax_usd=federal_income_tax_from_accounting,
        california_income_tax_usd=california_income_tax_from_accounting,
        total_income_tax_usd=total_income_tax_from_accounting,
        private_equity_sale_opportunity_event=private_equity_sale_opportunity_event,
        property_value_usd=property_value,
        mortgage_balance_usd=mortgage_balance,
        mortgage_interest_usd=mortgage_interest_from_ledger,
        mortgage_principal_usd=mortgage_principal_from_ledger,
        mortgage_payment_usd=mortgage_payment_from_ledger,
        property_tax_usd=property_tax_from_ledger,
        hoa_usd=hoa_from_ledger,
        insurance_usd=insurance_from_ledger,
        maintenance_usd=maintenance_from_ledger,
        rental_gross_income_usd=rental_gross_income_from_ledger,
        rental_vacancy_loss_usd=rental_vacancy_loss_from_ledger,
        rental_income_usd=rental_income_from_ledger,
        rental_management_fee_usd=rental_management_fee_from_ledger,
        rental_leasing_fee_usd=rental_leasing_fee_from_ledger,
        property_carrying_cost_usd=property_carrying_cost_from_ledger,
        net_property_cash_flow_usd=net_property_cash_flow_from_ledger,
        purchase_closing_cost_usd=disposition.purchase_closing_cost_usd,
        sale_closing_cost_usd=sale_closing_cost_from_ledger,
        property_depreciation_usd=disposition.property_depreciation_usd,
        cumulative_property_depreciation_usd=disposition.cumulative_property_depreciation_usd,
        property_sale_gross_usd=property_sale_gross_from_ledger,
        property_sale_net_proceeds_usd=property_sale_net_proceeds_from_ledger,
        property_sale_tax_usd=property_sale_tax_from_ledger,
        property_sale_debt_payoff_usd=property_sale_debt_payoff_from_ledger,
        property_sale_adjusted_basis_usd=property_sale_adjusted_basis_from_accounting,
        realized_property_gain_usd=realized_property_gain_from_accounting,
        property_sale_capital_gain_usd=property_sale_capital_gain_from_accounting,
        property_sale_capital_gain_exclusion_usd=property_sale_capital_gain_exclusion_from_accounting,
        taxable_property_capital_gain_usd=taxable_property_capital_gain_from_accounting,
        taxable_property_gain_usd=taxable_property_gain_from_accounting,
        depreciation_recapture_usd=depreciation_recapture_from_accounting,
        net_property_sale_cash_flow_usd=property_sale_net_proceeds_from_ledger,
        home_equity_usd=home_equity,
        owner_home_equity_claim_usd=owner_home_equity_claim,
        partner_home_equity_claim_usd=partner_home_equity_claim,
        partner_contribution_usd=partner_contribution_from_ledger,
        partner_contribution_used_usd=partner_contribution_used_from_ledger,
        partner_unallocated_excess_usd=partner_unallocated_excess_from_ledger,
        partner_house_costs_usd=partner_equity.house_costs_usd,
        partner_principal_credit_usd=partner_principal_credit_from_ledger,
        owner_principal_credit_usd=partner_equity.owner_principal_usd,
        partner_house_cost_share=partner_equity.house_cost_share,
        partner_equity_ledger_usd=partner_equity.partner_equity_ledger_usd,
        owner_equity_ledger_usd=partner_equity.owner_equity_ledger_usd,
        partner_ownership_pct=partner_equity.ownership_pct,
        liquid_net_worth_usd=liquid_net_worth,
        net_worth_usd=net_worth,
        partner_present=partner_present,
        monthly_spend_usd=monthly_spend_from_ledger,
        actions=_sorted_actions(actions),
        policy_decisions=_sorted_policy_decisions(policy_decisions),
        market_observations=_sorted_market_observations(market_observations),
        ledger_entries=_sorted_ledger_entries(ledger_entries),
        balance_snapshots=_sorted_balance_snapshots(balance_snapshots),
        accounting_details=_sorted_accounting_details(accounting_details),
    )


def _market_path_observations(
    scenario: Scenario, market_bundle: MarketBundle
) -> tuple[SimulationMarketObservation, ...]:
    home_multiplier = market_bundle.home_value_multipliers(scenario.location_id)
    rent_multiplier = market_bundle.rent_multipliers(scenario.location_id)
    observations: list[SimulationMarketObservation] = []
    rollout_indexes, month_positions = np.indices(
        (market_bundle.rollout_count, market_bundle.horizon_months + 1), sparse=False
    )
    for rollout_index, month_position in zip(
        rollout_indexes.ravel().tolist(), month_positions.ravel().tolist(), strict=True
    ):
        observations.append(
            MarketPathObservation(
                rollout_index=rollout_index,
                month_index=int(market_bundle.month_index[month_position]),
                location_id=scenario.location_id,
                inflation_multiplier=float(market_bundle.inflation_multipliers[rollout_index, month_position]),
                sp500_multiplier=float(market_bundle.generic_sp500_multipliers[rollout_index, month_position]),
                private_equity_value_multiplier=float(
                    market_bundle.private_equity_value_multipliers[rollout_index, month_position]
                ),
                home_value_multiplier=float(home_multiplier[rollout_index, month_position]),
                rent_multiplier=float(rent_multiplier[rollout_index, month_position]),
                mortgage_30y_rate_pct=float(market_bundle.mortgage_30y_rate_pct[rollout_index, month_position]),
                private_equity_sale_opportunity_event=bool(
                    market_bundle.private_equity_sale_opportunity_mask[rollout_index, month_position]
                ),
            )
        )
    return tuple(observations)


def _record_private_equity_sale_opportunity_observations(
    records: list[SimulationMarketObservation], *, month_index: int, opportunity: PrivateEquitySaleOpportunityBatch
) -> None:
    active_rollouts = np.nonzero(opportunity.sale_opportunity_mask)[0].tolist()
    records.extend(
        (
            PrivateEquitySaleOpportunityObservation(
                rollout_index=rollout_index,
                month_index=month_index,
                sale_opportunity_value_usd=float(opportunity.sale_opportunity_value_usd[rollout_index]),
                private_equity_value_before_sale_usd=float(
                    opportunity.private_equity_value_before_sale_usd[rollout_index]
                ),
            )
        )
        for rollout_index in active_rollouts
    )


def _record_monthly_spend_decisions(
    records: list[SimulationPolicyDecision],
    *,
    month_index: int,
    policy: MonthlySpendPolicy,
    amount_usd: np.ndarray,
    inflation_multiplier: np.ndarray,
) -> None:
    active_rollouts = np.nonzero(amount_usd > 0)[0].tolist()
    records.extend(
        (
            MonthlySpendDecision(
                rollout_index=rollout_index,
                month_index=month_index,
                actor_id=policy.actor_id,
                policy_id=policy.policy_id,
                amount_usd=float(amount_usd[rollout_index]),
                inflation_multiplier=float(inflation_multiplier[rollout_index]),
            )
        )
        for rollout_index in active_rollouts
    )


def _record_sell_public_stock_decisions(
    records: list[SimulationPolicyDecision],
    *,
    month_index: int,
    policy: CheckingFloorSellPublicStockPolicy,
    current_cash_usd: np.ndarray,
    requested_amount_usd: np.ndarray,
) -> None:
    active_rollouts = np.nonzero(requested_amount_usd > 0)[0].tolist()
    records.extend(
        (
            SellPublicStockDecision(
                rollout_index=rollout_index,
                month_index=month_index,
                actor_id=policy.actor_id,
                policy_id=policy.policy_id,
                requested_amount_usd=float(requested_amount_usd[rollout_index]),
                current_cash_usd=float(current_cash_usd[rollout_index]),
                target_cash_floor_usd=float(policy.floor_usd),
            )
        )
        for rollout_index in active_rollouts
    )


def _record_private_equity_sale_decisions(
    records: list[SimulationPolicyDecision],
    *,
    month_index: int,
    policy: PrivateEquitySalePolicy,
    instruction: PrivateEquitySaleInstructionBatch,
    opportunity: PrivateEquitySaleOpportunityBatch,
    liquid_net_worth_usd: np.ndarray,
) -> None:
    target_liquid_net_worth_floor_usd = (
        float(policy.sale_rule.min_liquid_net_worth_usd)
        if isinstance(policy.sale_rule, LiquidNetWorthFloorPrivateEquitySaleRule)
        else None
    )
    records.extend(
        (
            PrivateEquitySaleDecision(
                rollout_index=rollout_index,
                month_index=month_index,
                actor_id=instruction.actor_id,
                policy_id=instruction.policy_id,
                decision_reason=_private_equity_sale_decision_reason(
                    requested_amount_usd=instruction.requested_amount_usd[rollout_index],
                    sale_opportunity_value_usd=opportunity.sale_opportunity_value_usd[rollout_index],
                ),
                requested_amount_usd=float(instruction.requested_amount_usd[rollout_index]),
                sale_opportunity_value_usd=float(opportunity.sale_opportunity_value_usd[rollout_index]),
                private_equity_value_before_sale_usd=float(
                    opportunity.private_equity_value_before_sale_usd[rollout_index]
                ),
                liquid_net_worth_usd=float(liquid_net_worth_usd[rollout_index]),
                target_liquid_net_worth_floor_usd=target_liquid_net_worth_floor_usd,
                proceeds_destination=instruction.proceeds_destination,
            )
        )
        for rollout_index in range(instruction.requested_amount_usd.shape[0])
    )


def _private_equity_sale_decision_reason(
    *, requested_amount_usd: float, sale_opportunity_value_usd: float
) -> PrivateEquitySaleDecisionReason:
    if requested_amount_usd > 0:
        return PrivateEquitySaleDecisionReason.SALE_REQUESTED
    if sale_opportunity_value_usd <= 0:
        return PrivateEquitySaleDecisionReason.NO_SALE_OPPORTUNITY
    return PrivateEquitySaleDecisionReason.POLICY_NOT_TRIGGERED


def _record_partner_contribution_decisions(
    records: list[SimulationPolicyDecision], *, month_index: np.ndarray, partner_equity: PartnerEquityArrays
) -> None:
    for agreement in partner_equity.agreements:
        policy = agreement.policy
        rollout_indexes, month_positions = np.nonzero(agreement.contribution_usd > 0)
        for rollout_index, month_position in zip(rollout_indexes.tolist(), month_positions.tolist(), strict=True):
            records.append(
                PartnerContributionDecision(
                    rollout_index=rollout_index,
                    month_index=int(month_index[month_position]),
                    actor_id=policy.actor_id,
                    policy_id=policy.policy_id,
                    recipient_actor_id=agreement.recipient_actor_id,
                    requested_amount_usd=float(agreement.contribution_usd[rollout_index, month_position]),
                    property_id=agreement.property_id,
                )
            )


def _record_ledger_entry_month(
    records: list[SimulationLedgerEntry], *, month_index: int, entry: LedgerEntryBatch
) -> None:
    active_rollouts = np.nonzero(entry.amount_usd != 0)[0].tolist()
    records.extend(
        (
            SimulationLedgerEntry(
                rollout_index=rollout_index,
                month_index=month_index,
                actor_id=entry.actor_id,
                policy_id=entry.policy_id,
                domain=entry.domain,
                category=entry.category,
                amount_usd=float(entry.amount_usd[rollout_index]),
                counterparty_actor_id=entry.counterparty_actor_id,
            )
        )
        for rollout_index in active_rollouts
    )


def _record_ledger_entry_batches(
    records: list[SimulationLedgerEntry],
    *,
    month_index: np.ndarray,
    entries: tuple[LedgerEntryBatch, ...],
    amount_multiplier: np.ndarray | None = None,
) -> None:
    for entry in entries:
        amount_usd = entry.amount_usd if amount_multiplier is None else entry.amount_usd * amount_multiplier
        _record_ledger_matrix(
            records,
            month_index=month_index,
            actor_id=entry.actor_id,
            policy_id=entry.policy_id,
            domain=entry.domain,
            category=entry.category,
            amount_usd=amount_usd,
            counterparty_actor_id=entry.counterparty_actor_id,
        )


def _ledger_amount_matrix(
    records: list[SimulationLedgerEntry], *, rollout_count: int, month_index: np.ndarray, domain: str, category: str
) -> np.ndarray:
    matrix = np.zeros((rollout_count, len(month_index)), dtype="float64")
    month_position_by_index = {int(month): position for position, month in enumerate(month_index.tolist())}
    for entry in records:
        if entry.domain != domain or entry.category != category:
            continue
        try:
            month_position = month_position_by_index[entry.month_index]
        except KeyError as exc:
            raise ValueError(f"ledger entry has month outside result horizon: {entry.month_index}") from exc
        matrix[entry.rollout_index, month_position] += entry.amount_usd
    return matrix


def _accounting_detail_amount_matrix(
    records: list[SimulationAccountingDetail],
    *,
    rollout_count: int,
    month_index: np.ndarray,
    detail_type: AccountingDetailType,
    amount_field: str,
) -> np.ndarray:
    matrix = np.zeros((rollout_count, len(month_index)), dtype="float64")
    month_position_by_index = {int(month): position for position, month in enumerate(month_index.tolist())}
    for detail in records:
        if detail.detail_type != detail_type:
            continue
        try:
            month_position = month_position_by_index[detail.month_index]
        except KeyError as exc:
            raise ValueError(f"accounting detail has month outside result horizon: {detail.month_index}") from exc
        amount = getattr(detail, amount_field)
        if not isinstance(amount, int | float):
            raise TypeError(f"accounting detail field {amount_field!r} is not numeric")
        matrix[detail.rollout_index, month_position] += float(amount)
    return matrix


def _record_ledger_matrix(
    records: list[SimulationLedgerEntry],
    *,
    month_index: np.ndarray,
    actor_id: str,
    policy_id: str | None,
    domain: str,
    category: str,
    amount_usd: np.ndarray,
    counterparty_actor_id: str | None = None,
    event_id: str | None = None,
    property_id: str | None = None,
) -> None:
    rollout_indexes, month_positions = np.nonzero(amount_usd != 0)
    for rollout_index, month_position in zip(rollout_indexes.tolist(), month_positions.tolist(), strict=True):
        records.append(
            SimulationLedgerEntry(
                rollout_index=rollout_index,
                month_index=int(month_index[month_position]),
                actor_id=actor_id,
                policy_id=policy_id,
                event_id=event_id,
                property_id=property_id,
                domain=domain,
                category=category,
                amount_usd=float(amount_usd[rollout_index, month_position]),
                counterparty_actor_id=counterparty_actor_id,
            )
        )


def _record_ledger_month_vector(
    records: list[SimulationLedgerEntry],
    *,
    month_index: int,
    actor_id: str,
    policy_id: str | None,
    domain: str,
    category: str,
    amount_usd: np.ndarray,
    counterparty_actor_id: str | None = None,
    event_id: str | None = None,
    property_id: str | None = None,
) -> None:
    active_rollouts = np.nonzero(amount_usd != 0)[0].tolist()
    records.extend(
        (
            SimulationLedgerEntry(
                rollout_index=rollout_index,
                month_index=month_index,
                actor_id=actor_id,
                policy_id=policy_id,
                event_id=event_id,
                property_id=property_id,
                domain=domain,
                category=category,
                amount_usd=float(amount_usd[rollout_index]),
                counterparty_actor_id=counterparty_actor_id,
            )
        )
        for rollout_index in active_rollouts
    )


def _record_balance_snapshot_matrix(
    records: list[SimulationBalanceSnapshot],
    *,
    month_index: np.ndarray,
    actor_id: str,
    policy_id: str | None,
    domain: str,
    category: str,
    amount_usd: np.ndarray,
    counterparty_actor_id: str | None = None,
    property_id: str | None = None,
) -> None:
    rollout_indexes, month_positions = np.nonzero(amount_usd != 0)
    for rollout_index, month_position in zip(rollout_indexes.tolist(), month_positions.tolist(), strict=True):
        records.append(
            SimulationBalanceSnapshot(
                rollout_index=rollout_index,
                month_index=int(month_index[month_position]),
                actor_id=actor_id,
                policy_id=policy_id,
                property_id=property_id,
                domain=domain,
                category=category,
                amount_usd=float(amount_usd[rollout_index, month_position]),
                counterparty_actor_id=counterparty_actor_id,
            )
        )


def _record_property_sale_ledger_entries(
    records: list[SimulationLedgerEntry],
    *,
    scenario: Scenario,
    disposition: PropertyDispositionArrays,
    tax_usd: np.ndarray,
    net_proceeds_usd: np.ndarray,
) -> None:
    if disposition.sale_event is None or disposition.sale_month is None:
        return
    sale_event = disposition.sale_event
    property_id = sale_event.property_id or scenario.property_selection.property_id
    if property_id is None:
        return
    actor_id = sale_event.actor_id or _primary_owner_actor_id(scenario)
    month_index = disposition.sale_month
    settlement = disposition.sale_settlement
    _record_ledger_month_vector(
        records,
        month_index=month_index,
        actor_id=actor_id,
        policy_id=PROPERTY_SALE_SETTLEMENT_POLICY_ID,
        event_id=sale_event.event_id,
        property_id=property_id,
        domain="property_sale",
        category="property_sale_gross",
        amount_usd=settlement.gross_usd[:, month_index],
    )
    _record_ledger_month_vector(
        records,
        month_index=month_index,
        actor_id=actor_id,
        policy_id=PROPERTY_SALE_SETTLEMENT_POLICY_ID,
        event_id=sale_event.event_id,
        property_id=property_id,
        domain="property_sale",
        category="sale_closing_cost",
        amount_usd=-settlement.selling_cost_usd[:, month_index],
    )
    _record_ledger_month_vector(
        records,
        month_index=month_index,
        actor_id=actor_id,
        policy_id=PROPERTY_SALE_SETTLEMENT_POLICY_ID,
        event_id=sale_event.event_id,
        property_id=property_id,
        domain="property_sale",
        category="property_sale_debt_payoff",
        amount_usd=-settlement.debt_payoff_usd[:, month_index],
    )
    _record_ledger_month_vector(
        records,
        month_index=month_index,
        actor_id=actor_id,
        policy_id=PROPERTY_SALE_SETTLEMENT_POLICY_ID,
        event_id=sale_event.event_id,
        property_id=property_id,
        domain="tax",
        category="property_sale_tax",
        amount_usd=-tax_usd[:, month_index],
    )
    _record_ledger_month_vector(
        records,
        month_index=month_index,
        actor_id=actor_id,
        policy_id=PROPERTY_SALE_SETTLEMENT_POLICY_ID,
        event_id=sale_event.event_id,
        property_id=property_id,
        domain="cash",
        category="property_sale_net_proceeds",
        amount_usd=net_proceeds_usd[:, month_index],
    )


def _record_property_sale_accounting_details(
    records: list[SimulationAccountingDetail], *, scenario: Scenario, disposition: PropertyDispositionArrays
) -> None:
    if disposition.sale_event is None or disposition.sale_month is None:
        return
    sale_event = disposition.sale_event
    property_id = sale_event.property_id or scenario.property_selection.property_id
    if property_id is None:
        return
    actor_id = sale_event.actor_id or _primary_owner_actor_id(scenario)
    month_position = disposition.sale_month
    settlement = disposition.sale_settlement
    active_rollouts = np.nonzero(
        (settlement.gross_usd[:, month_position] != 0)
        | (settlement.realized_property_gain_usd[:, month_position] != 0)
        | (settlement.taxable_property_gain_usd[:, month_position] != 0)
    )[0]
    records.extend(
        PropertySaleBasisGainDetail(
            rollout_index=int(rollout_index),
            month_index=int(disposition.sale_month),
            actor_id=actor_id,
            policy_id=PROPERTY_SALE_SETTLEMENT_POLICY_ID,
            event_id=sale_event.event_id,
            property_id=property_id,
            gross_sale_usd=float(settlement.gross_usd[rollout_index, month_position]),
            selling_cost_usd=float(settlement.selling_cost_usd[rollout_index, month_position]),
            debt_payoff_usd=float(settlement.debt_payoff_usd[rollout_index, month_position]),
            adjusted_basis_usd=float(settlement.adjusted_basis_usd[rollout_index, month_position]),
            realized_gain_usd=float(settlement.realized_property_gain_usd[rollout_index, month_position]),
            depreciation_recapture_usd=float(settlement.depreciation_recapture_usd[rollout_index, month_position]),
            capital_gain_usd=float(settlement.property_sale_capital_gain_usd[rollout_index, month_position]),
            capital_gain_exclusion_usd=float(
                settlement.property_sale_capital_gain_exclusion_usd[rollout_index, month_position]
            ),
            taxable_capital_gain_usd=float(settlement.taxable_property_capital_gain_usd[rollout_index, month_position]),
            taxable_gain_usd=float(settlement.taxable_property_gain_usd[rollout_index, month_position]),
        )
        for rollout_index in active_rollouts.tolist()
    )


def _record_tax_payment_allocation_details(
    records: list[SimulationAccountingDetail],
    *,
    scenario: Scenario,
    month_index: np.ndarray,
    annual_tax: AnnualSaleTaxAllocation,
    property_depreciation_recapture_usd: np.ndarray,
    taxable_property_capital_gain_usd: np.ndarray,
    generic_sp500_sale_gain_usd: np.ndarray,
    private_equity_sale_taxable_gain_usd: np.ndarray,
) -> None:
    property_recapture = np.maximum(0.0, property_depreciation_recapture_usd)
    property_capital_gain = np.maximum(0.0, taxable_property_capital_gain_usd)
    sp500_capital_gain = np.maximum(0.0, generic_sp500_sale_gain_usd)
    private_equity_capital_gain = np.maximum(0.0, private_equity_sale_taxable_gain_usd)
    total_taxable_income = property_recapture + property_capital_gain + sp500_capital_gain + private_equity_capital_gain
    active_rollouts, active_month_positions = np.nonzero(
        (annual_tax.total_income_tax_usd != 0) | (total_taxable_income != 0)
    )
    actor_id = _primary_owner_actor_id(scenario)
    for rollout_index, month_position in zip(active_rollouts.tolist(), active_month_positions.tolist(), strict=True):
        records.append(
            TaxPaymentAllocationDetail(
                rollout_index=rollout_index,
                month_index=int(month_index[month_position]),
                actor_id=actor_id,
                policy_id=ANNUAL_TAX_ACCOUNTING_POLICY_ID,
                tax_year_index=int(month_index[month_position] // MONTHS_PER_YEAR),
                federal_income_tax_usd=float(annual_tax.federal_income_tax_usd[rollout_index, month_position]),
                california_income_tax_usd=float(annual_tax.california_income_tax_usd[rollout_index, month_position]),
                total_income_tax_usd=float(annual_tax.total_income_tax_usd[rollout_index, month_position]),
                property_sale_tax_usd=float(annual_tax.property_sale_tax_usd[rollout_index, month_position]),
                generic_sp500_sale_tax_usd=float(annual_tax.generic_sp500_sale_tax_usd[rollout_index, month_position]),
                private_equity_sale_tax_usd=float(
                    annual_tax.private_equity_sale_tax_usd[rollout_index, month_position]
                ),
                property_depreciation_recapture_usd=float(property_recapture[rollout_index, month_position]),
                taxable_property_capital_gain_usd=float(property_capital_gain[rollout_index, month_position]),
                generic_sp500_taxable_gain_usd=float(sp500_capital_gain[rollout_index, month_position]),
                private_equity_taxable_gain_usd=float(private_equity_capital_gain[rollout_index, month_position]),
                total_taxable_income_usd=float(total_taxable_income[rollout_index, month_position]),
            )
        )


def _record_sp500_sale_ledger_entries(
    records: list[SimulationLedgerEntry],
    *,
    month_index: int,
    policy: Policy,
    amount_usd: np.ndarray,
    basis_usd: np.ndarray,
    tax_usd: np.ndarray,
) -> None:
    _record_ledger_month_vector(
        records,
        month_index=month_index,
        actor_id=policy.actor_id,
        policy_id=policy.policy_id,
        domain="asset",
        category="generic_sp500_sale",
        amount_usd=-amount_usd,
    )
    _record_ledger_month_vector(
        records,
        month_index=month_index,
        actor_id=policy.actor_id,
        policy_id=policy.policy_id,
        domain="basis",
        category="generic_sp500_sale_basis",
        amount_usd=-basis_usd,
    )
    _record_ledger_month_vector(
        records,
        month_index=month_index,
        actor_id=policy.actor_id,
        policy_id=policy.policy_id,
        domain="tax",
        category="generic_sp500_sale_tax",
        amount_usd=-tax_usd,
    )
    _record_ledger_month_vector(
        records,
        month_index=month_index,
        actor_id=policy.actor_id,
        policy_id=policy.policy_id,
        domain="cash",
        category="generic_sp500_after_tax_proceeds",
        amount_usd=np.maximum(0.0, amount_usd - tax_usd),
    )


def _record_private_equity_sale_ledger_entries(
    records: list[SimulationLedgerEntry],
    *,
    month_index: int,
    instruction: PrivateEquitySaleInstructionBatch,
    sale_application: PrivateEquitySaleApplication,
    tax_usd: np.ndarray,
) -> None:
    destination_domain = "asset" if instruction.proceeds_destination is AssetType.GENERIC_SP500_STOCK else "cash"
    _record_ledger_month_vector(
        records,
        month_index=month_index,
        actor_id=instruction.actor_id,
        policy_id=instruction.policy_id,
        domain="asset",
        category="private_equity_sale",
        amount_usd=-sale_application.sale_usd,
    )
    _record_ledger_month_vector(
        records,
        month_index=month_index,
        actor_id=instruction.actor_id,
        policy_id=instruction.policy_id,
        domain="basis",
        category="private_equity_sale_basis",
        amount_usd=-sale_application.basis_usd,
    )
    _record_ledger_month_vector(
        records,
        month_index=month_index,
        actor_id=instruction.actor_id,
        policy_id=instruction.policy_id,
        domain="tax",
        category="private_equity_sale_tax",
        amount_usd=-tax_usd,
    )
    _record_ledger_month_vector(
        records,
        month_index=month_index,
        actor_id=instruction.actor_id,
        policy_id=instruction.policy_id,
        domain=destination_domain,
        category="private_equity_after_tax_proceeds",
        amount_usd=np.maximum(0.0, sale_application.sale_usd - tax_usd),
    )


def _record_partner_agreement_ledger_detail(
    ledger_records: list[SimulationLedgerEntry],
    snapshot_records: list[SimulationBalanceSnapshot],
    *,
    month_index: np.ndarray,
    partner_equity: PartnerEquityArrays,
    owner_actor_id: str,
) -> None:
    if not partner_equity.agreements:
        return
    _record_ledger_matrix(
        ledger_records,
        month_index=month_index,
        actor_id=owner_actor_id,
        policy_id=None,
        domain="ownership",
        category="owner_principal_credit",
        amount_usd=partner_equity.owner_principal_usd,
    )
    _record_balance_snapshot_matrix(
        snapshot_records,
        month_index=month_index,
        actor_id=owner_actor_id,
        policy_id=None,
        domain="ownership",
        category="owner_equity_ledger",
        amount_usd=partner_equity.owner_equity_ledger_usd,
    )
    _record_balance_snapshot_matrix(
        snapshot_records,
        month_index=month_index,
        actor_id=owner_actor_id,
        policy_id=None,
        domain="ownership",
        category="owner_home_equity_claim",
        amount_usd=partner_equity.owner_home_equity_claim_usd,
    )
    for agreement in partner_equity.agreements:
        policy = agreement.policy
        _record_ledger_matrix(
            ledger_records,
            month_index=month_index,
            actor_id=policy.actor_id,
            policy_id=policy.policy_id,
            domain="cash",
            category="partner_contribution_transfer",
            amount_usd=-agreement.contribution_usd,
            counterparty_actor_id=agreement.recipient_actor_id,
            property_id=agreement.property_id,
        )
        _record_ledger_matrix(
            ledger_records,
            month_index=month_index,
            actor_id=agreement.recipient_actor_id,
            policy_id=policy.policy_id,
            domain="cash",
            category="partner_contribution_used_for_house_costs",
            amount_usd=agreement.contribution_used_usd,
            counterparty_actor_id=policy.actor_id,
            property_id=agreement.property_id,
        )
        _record_ledger_matrix(
            ledger_records,
            month_index=month_index,
            actor_id=agreement.recipient_actor_id,
            policy_id=policy.policy_id,
            domain="escrow",
            category="partner_contribution_unallocated",
            amount_usd=agreement.unallocated_excess_usd,
            counterparty_actor_id=policy.actor_id,
            property_id=agreement.property_id,
        )
        _record_ledger_matrix(
            ledger_records,
            month_index=month_index,
            actor_id=policy.actor_id,
            policy_id=policy.policy_id,
            domain="ownership",
            category="partner_principal_credit",
            amount_usd=agreement.principal_credit_usd,
            counterparty_actor_id=agreement.recipient_actor_id,
            property_id=agreement.property_id,
        )
        _record_balance_snapshot_matrix(
            snapshot_records,
            month_index=month_index,
            actor_id=policy.actor_id,
            policy_id=policy.policy_id,
            domain="ownership",
            category="partner_equity_ledger",
            amount_usd=agreement.partner_equity_ledger_usd,
            counterparty_actor_id=agreement.recipient_actor_id,
            property_id=agreement.property_id,
        )
        _record_balance_snapshot_matrix(
            snapshot_records,
            month_index=month_index,
            actor_id=policy.actor_id,
            policy_id=policy.policy_id,
            domain="ownership",
            category="partner_home_equity_claim",
            amount_usd=agreement.home_equity_claim_usd,
            counterparty_actor_id=agreement.recipient_actor_id,
            property_id=agreement.property_id,
        )


def _sorted_policy_decisions(records: list[SimulationPolicyDecision]) -> tuple[SimulationPolicyDecision, ...]:
    return tuple(
        sorted(
            records,
            key=lambda decision: (
                decision.month_index,
                decision.rollout_index,
                decision.decision_type,
                decision.actor_id,
                decision.policy_id,
            ),
        )
    )


def _sorted_market_observations(records: list[SimulationMarketObservation]) -> tuple[SimulationMarketObservation, ...]:
    return tuple(
        sorted(
            records,
            key=lambda observation: (observation.month_index, observation.rollout_index, observation.observation_type),
        )
    )


def _sorted_ledger_entries(records: list[SimulationLedgerEntry]) -> tuple[SimulationLedgerEntry, ...]:
    return tuple(
        sorted(
            records,
            key=lambda entry: (
                entry.month_index,
                entry.rollout_index,
                entry.domain,
                entry.category,
                entry.actor_id,
                entry.policy_id or "",
            ),
        )
    )


def _sorted_balance_snapshots(records: list[SimulationBalanceSnapshot]) -> tuple[SimulationBalanceSnapshot, ...]:
    return tuple(
        sorted(
            records,
            key=lambda entry: (
                entry.month_index,
                entry.rollout_index,
                entry.domain,
                entry.category,
                entry.actor_id,
                entry.policy_id or "",
            ),
        )
    )


def _sorted_accounting_details(records: list[SimulationAccountingDetail]) -> tuple[SimulationAccountingDetail, ...]:
    return tuple(
        sorted(
            records,
            key=lambda detail: (
                detail.month_index,
                detail.rollout_index,
                detail.detail_type,
                detail.actor_id,
                detail.policy_id or "",
                detail.event_id or "",
                detail.property_id or "",
            ),
        )
    )


def _record_property_sale_actions(
    actions: list[SimulationAction],
    *,
    scenario: Scenario,
    disposition: PropertyDispositionArrays,
    tax_usd: np.ndarray | None = None,
    net_proceeds_usd: np.ndarray | None = None,
) -> None:
    if disposition.sale_event is None or disposition.sale_month is None:
        return
    sale_event = disposition.sale_event
    property_id = sale_event.property_id or scenario.property_selection.property_id
    if property_id is None:
        return
    month = disposition.sale_month
    settlement = disposition.sale_settlement
    sale_tax = tax_usd if tax_usd is not None else settlement.tax_usd
    net_proceeds = net_proceeds_usd if net_proceeds_usd is not None else settlement.net_proceeds_usd
    active = (
        (settlement.gross_usd[:, month] != 0)
        | (settlement.selling_cost_usd[:, month] != 0)
        | (settlement.debt_payoff_usd[:, month] != 0)
        | (sale_tax[:, month] != 0)
        | (net_proceeds[:, month] != 0)
    )
    actor_id = sale_event.actor_id or _primary_owner_actor_id(scenario)
    actions.extend(
        SettlePropertySaleAction(
            rollout_index=rollout_index,
            month_index=month,
            actor_id=actor_id,
            policy_id=PROPERTY_SALE_SETTLEMENT_POLICY_ID,
            event_id=sale_event.event_id,
            property_id=property_id,
            gross_sale_usd=float(settlement.gross_usd[rollout_index, month]),
            selling_cost_usd=float(settlement.selling_cost_usd[rollout_index, month]),
            debt_payoff_usd=float(settlement.debt_payoff_usd[rollout_index, month]),
            adjusted_basis_usd=float(settlement.adjusted_basis_usd[rollout_index, month]),
            realized_gain_usd=float(settlement.realized_property_gain_usd[rollout_index, month]),
            depreciation_recapture_usd=float(settlement.depreciation_recapture_usd[rollout_index, month]),
            capital_gain_usd=float(settlement.property_sale_capital_gain_usd[rollout_index, month]),
            capital_gain_exclusion_usd=float(settlement.property_sale_capital_gain_exclusion_usd[rollout_index, month]),
            taxable_capital_gain_usd=float(settlement.taxable_property_capital_gain_usd[rollout_index, month]),
            taxable_gain_usd=float(settlement.taxable_property_gain_usd[rollout_index, month]),
            tax_usd=float(sale_tax[rollout_index, month]),
            net_proceeds_usd=float(net_proceeds[rollout_index, month]),
        )
        for rollout_index in np.nonzero(active)[0].tolist()
    )


def _record_sp500_sale_actions(
    actions: list[SimulationAction],
    *,
    month_index: int,
    policy: Policy,
    amount_usd: np.ndarray,
    basis_usd: np.ndarray,
    tax_usd: np.ndarray,
    shortfall_usd: np.ndarray,
) -> None:
    for rollout_index in np.nonzero((amount_usd > 0) | (shortfall_usd > 0))[0].tolist():
        amount = float(amount_usd[rollout_index])
        basis = float(basis_usd[rollout_index])
        tax = float(tax_usd[rollout_index])
        actions.append(
            SellSp500Action(
                rollout_index=rollout_index,
                month_index=month_index,
                actor_id=policy.actor_id,
                policy_id=policy.policy_id,
                amount_usd=amount,
                after_tax_proceeds_usd=max(0.0, amount - tax),
                basis_usd=basis,
                gain_usd=amount - basis,
                tax_usd=tax,
                shortfall_usd=float(shortfall_usd[rollout_index]),
            )
        )


def _record_private_equity_sale_actions(
    actions: list[SimulationAction],
    *,
    month_index: int,
    instruction: PrivateEquitySaleInstructionBatch,
    sale_application: PrivateEquitySaleApplication,
    estimated_tax_usd: np.ndarray | None = None,
) -> None:
    sale_tax = estimated_tax_usd if estimated_tax_usd is not None else sale_application.estimated_tax_usd
    actions.extend(
        SellPrivateEquityAction(
            rollout_index=rollout_index,
            month_index=month_index,
            actor_id=instruction.actor_id,
            policy_id=instruction.policy_id,
            amount_usd=float(sale_application.sale_usd[rollout_index]),
            after_tax_proceeds_usd=float(np.maximum(0.0, sale_application.sale_usd - sale_tax)[rollout_index]),
            basis_usd=float(sale_application.basis_usd[rollout_index]),
            taxable_gain_usd=float(sale_application.taxable_gain_usd[rollout_index]),
            estimated_tax_usd=float(sale_tax[rollout_index]),
            units_sold=float(sale_application.sold_units[rollout_index]),
            sold_fraction=float(sale_application.sold_fraction[rollout_index]),
            proceeds_destination=instruction.proceeds_destination,
        )
        for rollout_index in np.nonzero(sale_application.sale_usd > 0)[0].tolist()
    )


def _tax_share_for_sale_action(
    *, source_tax_usd: np.ndarray, action_taxable_income_usd: np.ndarray, source_taxable_income_usd: np.ndarray
) -> np.ndarray:
    tax_share = np.zeros_like(source_tax_usd, dtype="float64")
    np.divide(
        source_tax_usd * action_taxable_income_usd,
        source_taxable_income_usd,
        out=tax_share,
        where=source_taxable_income_usd > 0,
    )
    return tax_share


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


def _record_mortgage_payment_actions(
    actions: list[SimulationAction], *, month_index: np.ndarray, mortgage_application: MortgagePaymentApplication
) -> None:
    rollout_indexes, month_positions = np.nonzero(mortgage_application.mortgage_payment_usd > 0)
    for rollout_index, month_position in zip(rollout_indexes.tolist(), month_positions.tolist(), strict=True):
        actions.append(
            PayMortgageAction(
                rollout_index=rollout_index,
                month_index=int(month_index[month_position]),
                actor_id=mortgage_application.actor_id,
                policy_id=mortgage_application.policy_id,
                mortgage_payment_usd=float(mortgage_application.mortgage_payment_usd[rollout_index, month_position]),
                mortgage_interest_usd=float(mortgage_application.mortgage_interest_usd[rollout_index, month_position]),
                mortgage_principal_usd=float(
                    mortgage_application.mortgage_principal_usd[rollout_index, month_position]
                ),
                mortgage_balance_after_usd=float(
                    mortgage_application.mortgage_balance_after_usd[rollout_index, month_position]
                ),
            )
        )


def _record_partner_agreement_actions(
    actions: list[SimulationAction], *, month_index: np.ndarray, partner_equity: PartnerEquityArrays
) -> None:
    for agreement in partner_equity.agreements:
        policy = agreement.policy
        active = (agreement.contribution_usd > 0) | (agreement.unallocated_excess_usd > 0)
        rollout_indexes, month_positions = np.nonzero(active)
        for rollout_index, month_position in zip(rollout_indexes.tolist(), month_positions.tolist(), strict=True):
            month = int(month_index[month_position])
            contribution = float(agreement.contribution_usd[rollout_index, month_position])
            contribution_used = float(agreement.contribution_used_usd[rollout_index, month_position])
            mortgage_principal = float(agreement.mortgage_principal_usd[rollout_index, month_position])
            actions.append(
                TransferPartnerContributionAction(
                    rollout_index=rollout_index,
                    month_index=month,
                    actor_id=policy.actor_id,
                    policy_id=policy.policy_id,
                    recipient_actor_id=agreement.recipient_actor_id,
                    amount_usd=contribution,
                    applied_to_house_costs_usd=contribution_used,
                    unallocated_amount_usd=float(agreement.unallocated_excess_usd[rollout_index, month_position]),
                )
            )
            actions.append(
                AccruePartnerEquityAction(
                    rollout_index=rollout_index,
                    month_index=month,
                    actor_id=policy.actor_id,
                    policy_id=policy.policy_id,
                    beneficiary_actor_id=policy.actor_id,
                    property_id=agreement.property_id,
                    house_costs_usd=float(agreement.house_costs_usd[rollout_index, month_position]),
                    cash_transfer_used_for_house_costs_usd=contribution_used,
                    mortgage_principal_usd=mortgage_principal,
                    principal_credit_usd=float(agreement.principal_credit_usd[rollout_index, month_position]),
                    house_cost_share=float(agreement.house_cost_share[rollout_index, month_position]),
                    ownership_pct_after=float(agreement.ownership_pct[rollout_index, month_position]),
                    home_equity_claim_usd_after=float(agreement.home_equity_claim_usd[rollout_index, month_position]),
                )
            )


def _sorted_actions(actions: list[SimulationAction]) -> tuple[SimulationAction, ...]:
    return tuple(sorted(actions, key=lambda action: (action.month_index, action.rollout_index, action.action_type)))


def _property_cash_flow_arrays(
    scenario: Scenario,
    market_bundle: MarketBundle,
    *,
    location_id: str | None,
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
            ledger_entries=(),
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
    operating_cash_flow = apply_property_operating_cash_flows(
        actor_id=_primary_owner_actor_id(scenario),
        policy_id=PROPERTY_OPERATING_CASH_FLOW_POLICY_ID,
        property_tax_usd=property_tax,
        hoa_usd=hoa,
        insurance_usd=insurance,
        maintenance_usd=maintenance,
        rental_gross_income_usd=rental_gross_income,
        rental_vacancy_loss_usd=rental_vacancy_loss,
        rental_income_usd=rental_income,
        rental_management_fee_usd=rental_management_fee,
        rental_leasing_fee_usd=rental_leasing_fee,
    )
    net_property_cash_flow = operating_cash_flow.net_operating_cash_flow_usd - mortgage_payment
    return PropertyCashFlowArrays(
        mortgage_payment_usd=mortgage_payment,
        property_tax_usd=operating_cash_flow.property_tax_usd,
        hoa_usd=operating_cash_flow.hoa_usd,
        insurance_usd=operating_cash_flow.insurance_usd,
        maintenance_usd=operating_cash_flow.maintenance_usd,
        rental_gross_income_usd=operating_cash_flow.rental_gross_income_usd,
        rental_vacancy_loss_usd=operating_cash_flow.rental_vacancy_loss_usd,
        rental_income_usd=operating_cash_flow.rental_income_usd,
        rental_management_fee_usd=operating_cash_flow.rental_management_fee_usd,
        rental_leasing_fee_usd=operating_cash_flow.rental_leasing_fee_usd,
        property_carrying_cost_usd=operating_cash_flow.property_carrying_cost_usd,
        net_property_cash_flow_usd=net_property_cash_flow,
        ledger_entries=operating_cash_flow.ledger_entries,
    )


def _rental_cash_flow_arrays(
    scenario: Scenario, market_bundle: MarketBundle, *, location_id: str | None
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
    owner_equity_without_partners = float(owner_initial_equity_usd) + np.cumsum(mortgage_principal_usd, axis=1)
    empty = PartnerEquityArrays(
        contribution_usd=zeros,
        contribution_used_usd=zeros,
        unallocated_excess_usd=zeros,
        house_costs_usd=zeros,
        mortgage_payment_usd=zeros,
        mortgage_interest_usd=zeros,
        mortgage_principal_usd=zeros,
        principal_credit_usd=zeros,
        owner_principal_usd=mortgage_principal_usd,
        house_cost_share=zeros,
        partner_equity_ledger_usd=zeros,
        owner_equity_ledger_usd=owner_equity_without_partners,
        ownership_pct=zeros,
        home_equity_claim_usd=zeros,
        owner_home_equity_claim_usd=home_equity_usd,
        agreements=(),
    )
    partner_policies = enabled_rules_of_type(actor_policy_programs(scenario), PartnerEquityAccrualPolicy)
    if not partner_policies or not _has_partner(scenario):
        return empty

    month_matrix = np.broadcast_to(market_bundle.month_index[None, :], home_equity_usd.shape)
    mortgage_payment = mortgage_interest_usd + mortgage_principal_usd
    house_uses = (
        mortgage_interest_usd + mortgage_principal_usd + property_tax_usd + hoa_usd + insurance_usd + maintenance_usd
    )
    owner_actor_id = _primary_owner_actor_id(scenario)
    contribution_inputs = []
    remaining_house_uses = house_uses.copy()
    remaining_principal = mortgage_principal_usd.copy()
    for policy in partner_policies:
        property_id = _partner_equity_property_id(scenario, policy)
        if property_id is None:
            continue
        occupied_months = _partner_occupied_months(scenario, policy, market_bundle.horizon_months)
        active = (month_matrix > 0) & (month_matrix <= occupied_months)
        configured_payment = np.where(
            active, float(policy.base_monthly_payment_usd) * _partner_payment_growth(policy, market_bundle), 0.0
        )
        contribution_instruction = partner_contribution_instruction(
            policy, recipient_actor_id=owner_actor_id, contribution_usd=configured_payment
        )
        principal_available = remaining_principal.copy()
        contribution_application = apply_partner_house_cost_contribution(
            contribution_instruction, house_costs_usd=remaining_house_uses, mortgage_principal_usd=principal_available
        )
        freeze_after_month = _partner_freeze_after_month(
            scenario, policy, occupied_months, market_bundle.horizon_months
        )
        contribution_inputs.append(
            (
                policy,
                property_id,
                contribution_instruction,
                contribution_application,
                principal_available,
                freeze_after_month,
            )
        )
        remaining_house_uses = np.maximum(0.0, remaining_house_uses - contribution_application.contribution_used_usd)
        remaining_principal = np.maximum(0.0, remaining_principal - contribution_application.principal_credit_usd)
    if not contribution_inputs:
        return empty

    principal_credit = sum(
        (application.principal_credit_usd for _, _, _, application, _, _ in contribution_inputs), start=zeros.copy()
    )
    owner_principal = np.maximum(0.0, mortgage_principal_usd - principal_credit)
    owner_equity_ledger = float(owner_initial_equity_usd) + np.cumsum(owner_principal, axis=1)
    total_partner_equity_ledger = sum(
        (np.cumsum(application.principal_credit_usd, axis=1) for _, _, _, application, _, _ in contribution_inputs),
        start=zeros.copy(),
    )
    agreements = []
    for (
        policy,
        property_id,
        contribution_instruction,
        contribution_application,
        principal_available,
        freeze_after_month,
    ) in contribution_inputs:
        ownership_application = apply_partner_ownership_accrual(
            contribution_instruction,
            owner_initial_equity_usd=owner_initial_equity_usd,
            home_equity_usd=home_equity_usd,
            owner_principal_usd=owner_principal,
            partner_principal_credit_usd=contribution_application.principal_credit_usd,
            month_index=market_bundle.month_index,
            freeze_after_month=freeze_after_month,
            owner_equity_ledger_usd=owner_equity_ledger,
            total_partner_equity_ledger_usd=total_partner_equity_ledger,
        )
        agreements.append(
            PartnerEquityAgreementArrays(
                policy=policy,
                property_id=property_id,
                recipient_actor_id=owner_actor_id,
                contribution_usd=contribution_instruction.amount_usd,
                contribution_used_usd=contribution_application.contribution_used_usd,
                unallocated_excess_usd=contribution_application.unallocated_excess_usd,
                house_costs_usd=contribution_application.house_costs_usd,
                mortgage_payment_usd=mortgage_payment,
                mortgage_interest_usd=mortgage_interest_usd,
                mortgage_principal_usd=principal_available,
                principal_credit_usd=contribution_application.principal_credit_usd,
                owner_principal_usd=owner_principal,
                house_cost_share=contribution_application.house_cost_share,
                partner_equity_ledger_usd=ownership_application.partner_equity_ledger_usd,
                owner_equity_ledger_usd=owner_equity_ledger,
                ownership_pct=ownership_application.ownership_pct,
                home_equity_claim_usd=ownership_application.home_equity_claim_usd,
                owner_home_equity_claim_usd=ownership_application.owner_home_equity_claim_usd,
            )
        )

    contribution_usd = sum((agreement.contribution_usd for agreement in agreements), start=zeros.copy())
    contribution_used = sum((agreement.contribution_used_usd for agreement in agreements), start=zeros.copy())
    unallocated_excess = sum((agreement.unallocated_excess_usd for agreement in agreements), start=zeros.copy())
    home_equity_claim = sum((agreement.home_equity_claim_usd for agreement in agreements), start=zeros.copy())
    positive_home_equity = np.maximum(home_equity_usd, 0.0)
    ownership_pct = np.divide(
        home_equity_claim, positive_home_equity, out=np.zeros_like(home_equity_claim), where=positive_home_equity > 0
    )
    return PartnerEquityArrays(
        contribution_usd=contribution_usd,
        contribution_used_usd=contribution_used,
        unallocated_excess_usd=unallocated_excess,
        house_costs_usd=house_uses,
        mortgage_payment_usd=mortgage_payment,
        mortgage_interest_usd=mortgage_interest_usd,
        mortgage_principal_usd=mortgage_principal_usd,
        principal_credit_usd=principal_credit,
        owner_principal_usd=owner_principal,
        house_cost_share=np.divide(
            contribution_used, house_uses, out=np.zeros_like(contribution_used), where=house_uses > 0
        ),
        partner_equity_ledger_usd=total_partner_equity_ledger,
        owner_equity_ledger_usd=owner_equity_ledger,
        ownership_pct=ownership_pct,
        home_equity_claim_usd=home_equity_claim,
        owner_home_equity_claim_usd=home_equity_usd - home_equity_claim,
        agreements=tuple(agreements),
    )


def _settle_partner_equity_on_property_sale(
    partner_equity: PartnerEquityArrays, *, sale_month: int | None, property_sale_net_proceeds_usd: np.ndarray
) -> PartnerEquityArrays:
    if sale_month is None or not partner_equity.agreements:
        return partner_equity

    agreements = tuple(
        _settle_partner_equity_agreement_on_property_sale(
            agreement, sale_month=sale_month, property_sale_net_proceeds_usd=property_sale_net_proceeds_usd
        )
        for agreement in partner_equity.agreements
    )
    partner_home_equity_claim_usd = sum(
        (agreement.home_equity_claim_usd for agreement in agreements),
        start=np.zeros_like(partner_equity.home_equity_claim_usd),
    )
    owner_home_equity_claim_usd = partner_equity.owner_home_equity_claim_usd.copy()
    sale_net_proceeds = property_sale_net_proceeds_usd[:, sale_month]
    owner_home_equity_claim_usd[:, sale_month:] = (
        sale_net_proceeds[:, None] - partner_home_equity_claim_usd[:, sale_month:]
    )
    return replace(
        partner_equity,
        home_equity_claim_usd=partner_home_equity_claim_usd,
        owner_home_equity_claim_usd=owner_home_equity_claim_usd,
        agreements=agreements,
    )


def _settle_partner_equity_agreement_on_property_sale(
    agreement: PartnerEquityAgreementArrays, *, sale_month: int, property_sale_net_proceeds_usd: np.ndarray
) -> PartnerEquityAgreementArrays:
    home_equity_claim_usd = agreement.home_equity_claim_usd.copy()
    owner_home_equity_claim_usd = agreement.owner_home_equity_claim_usd.copy()
    sale_net_proceeds = property_sale_net_proceeds_usd[:, sale_month]
    partner_sale_claim = np.maximum(0.0, sale_net_proceeds) * agreement.ownership_pct[:, sale_month]
    home_equity_claim_usd[:, sale_month:] = partner_sale_claim[:, None]
    owner_home_equity_claim_usd[:, sale_month:] = sale_net_proceeds[:, None] - partner_sale_claim[:, None]
    return replace(
        agreement, home_equity_claim_usd=home_equity_claim_usd, owner_home_equity_claim_usd=owner_home_equity_claim_usd
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


def _property_and_mortgage_arrays(
    scenario: Scenario, market_bundle: MarketBundle, *, location_id: str | None
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


def _scenario_hoa_monthly_usd(scenario: Scenario) -> float:
    for event in scenario.events:
        if isinstance(event, PropertyPurchaseEvent) and event.hoa_monthly_usd is not None:
            return float(event.hoa_monthly_usd)
    return 0.0


def _required_local_regulation(scenario: Scenario) -> LocalRegulation:
    if scenario.property_selection.local_regulation is not None:
        return scenario.property_selection.local_regulation
    location_id = scenario.location_id
    if location_id is None:
        raise ValueError(f"scenario {scenario.scenario_id!r} has real estate but no location_id")
    return local_regulation_for_location(location_id)


def _pct_fraction(value: float, name: str) -> float:
    if value < 0 or value > 100:
        raise ValueError(f"{name} must be in [0, 100]")
    return value / 100


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
