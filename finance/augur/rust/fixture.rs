use serde::{Deserialize, Serialize};

use crate::{
    ledger::{AccountRef, JournalEntry},
    money::{Money, Quantity},
    tax::TaxRules,
};

pub const FIXTURE_SCHEMA_VERSION: u32 = 1;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Fixture {
    pub schema_version: u32,
    pub currency_code: String,
    /// Exact decimal spelling of one money quantum, for example `"0.01"`.
    pub currency_quantum: String,
    pub rollout_count: u32,
    pub scenario: ScenarioSpec,
    pub series: Vec<SeriesSpec>,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ScenarioSpec {
    pub horizon_months: u32,
    pub accounts: Vec<AccountSpec>,
    #[serde(default)]
    pub locations: Vec<LocationSpec>,
    #[serde(default)]
    pub scheduled_transfers: Vec<ScheduledTransferSpec>,
    #[serde(default)]
    pub recurring_transfers: Vec<RecurringTransferSpec>,
    #[serde(default)]
    pub scheduled_property_cashflows: Vec<ScheduledPropertyCashflowSpec>,
    #[serde(default)]
    pub recurring_property_cashflows: Vec<RecurringPropertyCashflowSpec>,
    #[serde(default)]
    pub obligations: Vec<ObligationSpec>,
    #[serde(default)]
    pub recurring_obligations: Vec<RecurringObligationSpec>,
    #[serde(default)]
    pub initial_lots: Vec<InitialLotSpec>,
    #[serde(default)]
    pub scheduled_sales: Vec<ScheduledSaleSpec>,
    #[serde(default)]
    pub tax_profiles: Vec<TaxProfileSpec>,
    #[serde(default)]
    pub distributions: Vec<DistributionSpec>,
    #[serde(default)]
    pub scheduled_property_purchases: Vec<ScheduledPropertyPurchaseSpec>,
    #[serde(default)]
    pub property_rented_fraction_events: Vec<PropertyRentedFractionSpec>,
    #[serde(default)]
    pub capital_improvement_events: Vec<CapitalImprovementSpec>,
    #[serde(default)]
    pub property_sales: Vec<PropertySaleSpec>,
    #[serde(default)]
    pub mortgage_interest_deduction_policies: Vec<MortgageInterestDeductionSpec>,
    #[serde(default)]
    pub property_tax_policies: Vec<PropertyTaxPolicySpec>,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct LocationSpec {
    pub location_id: String,
    pub display_name: String,
    #[serde(default)]
    pub jurisdiction_ids: Vec<String>,
    pub annual_property_tax_rate_ppb: i64,
    #[serde(default)]
    pub annual_special_assessment: Money,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AccountSpec {
    pub account: AccountRef,
    pub opening_balance: Money,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(untagged)]
pub enum AmountSpec {
    Fixed(Money),
    FixedSchedule(FixedAmountSpec),
    SeriesIndexed(SeriesIndexedAmountSpec),
}

impl AmountSpec {
    pub fn base_amount(&self) -> Money {
        match self {
            Self::Fixed(amount) => *amount,
            Self::FixedSchedule(amount) => amount.amount,
            Self::SeriesIndexed(amount) => amount.base_amount,
        }
    }
}

impl From<Money> for AmountSpec {
    fn from(value: Money) -> Self {
        Self::Fixed(value)
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct FixedAmountSpec {
    pub kind: FixedAmountKind,
    pub amount: Money,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub enum FixedAmountKind {
    #[serde(rename = "fixed")]
    Fixed,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SeriesIndexedAmountSpec {
    pub kind: SeriesIndexedAmountKind,
    pub base_amount: Money,
    pub series_id: String,
    #[serde(default)]
    pub base_month_index: u32,
    #[serde(default = "default_adjustment_period_months")]
    pub adjustment_period_months: u32,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub enum SeriesIndexedAmountKind {
    #[serde(rename = "series_indexed")]
    SeriesIndexed,
}

fn default_adjustment_period_months() -> u32 {
    1
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ScheduledTransferSpec {
    pub month: u32,
    pub cause_id: String,
    pub from: AccountRef,
    pub to: AccountRef,
    pub amount: AmountSpec,
    #[serde(default)]
    pub income_category: Option<String>,
    #[serde(default)]
    pub deduction_category: Option<String>,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RecurringTransferSpec {
    pub start_month: u32,
    pub end_month: Option<u32>,
    pub cause_id: String,
    pub from: AccountRef,
    pub to: AccountRef,
    pub amount: AmountSpec,
    #[serde(default)]
    pub income_category: Option<String>,
    #[serde(default)]
    pub deduction_category: Option<String>,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ScheduledPropertyCashflowSpec {
    pub month: u32,
    pub property_id: String,
    pub cause_id: String,
    pub from: AccountRef,
    pub to: AccountRef,
    pub amount: AmountSpec,
    #[serde(default)]
    pub income_category: Option<String>,
    #[serde(default)]
    pub deduction_category: Option<String>,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RecurringPropertyCashflowSpec {
    pub start_month: u32,
    pub end_month: Option<u32>,
    pub property_id: String,
    pub cause_id: String,
    pub from: AccountRef,
    pub to: AccountRef,
    pub amount: AmountSpec,
    #[serde(default)]
    pub income_category: Option<String>,
    #[serde(default)]
    pub deduction_category: Option<String>,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ObligationSpec {
    pub month: u32,
    pub obligation_id: String,
    #[serde(default = "default_obligation_type")]
    pub obligation_type: String,
    pub from: AccountRef,
    pub to: AccountRef,
    pub amount_due: AmountSpec,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RecurringObligationSpec {
    pub start_month: u32,
    pub end_month: Option<u32>,
    pub obligation_id: String,
    #[serde(default = "default_obligation_type")]
    pub obligation_type: String,
    pub from: AccountRef,
    pub to: AccountRef,
    pub amount_due: AmountSpec,
}

fn default_obligation_type() -> String {
    "cash_spend".into()
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct InitialLotSpec {
    pub lot_id: String,
    pub agent_id: String,
    pub account_id: String,
    pub asset_id: String,
    pub purchase_month: i32,
    pub quantity_scale: i64,
    pub units: Quantity,
    pub basis: Money,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ScheduledSaleSpec {
    pub month: u32,
    pub cause_id: String,
    pub agent_id: String,
    pub account_id: String,
    pub asset_id: String,
    pub units: Quantity,
    pub proceeds_account_id: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct TaxProfileSpec {
    pub agent_id: String,
    pub tax_authority_agent_id: String,
    #[serde(default = "default_account_id")]
    pub payment_account_id: String,
    #[serde(default = "default_account_id")]
    pub tax_authority_account_id: String,
    #[serde(default)]
    pub prior_year_tax: Money,
    pub jurisdictions: Vec<TaxRules>,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct DistributionSpec {
    pub agent_id: String,
    pub holding_account_id: String,
    pub asset_id: String,
    pub to_account_id: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct MortgageFinancingSpec {
    pub liability_id: String,
    pub lender_agent_id: String,
    #[serde(default = "default_account_id")]
    pub lender_account_id: String,
    pub principal: Money,
    pub annual_interest_rate_ppb: i64,
    pub term_months: u32,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ScheduledPropertyPurchaseSpec {
    pub month: u32,
    pub cause_id: String,
    pub property_id: String,
    pub location_id: String,
    pub buyer_agent_id: String,
    pub buyer_account_id: String,
    pub seller_agent_id: String,
    #[serde(default = "default_account_id")]
    pub seller_account_id: String,
    pub purchase_price: Money,
    pub down_payment: Money,
    #[serde(default)]
    pub buyer_closing_cost: Money,
    #[serde(default)]
    pub rented_fraction_ppb: i64,
    #[serde(default = "default_land_value_fraction_ppb")]
    pub land_value_fraction_ppb: i64,
    #[serde(default)]
    pub mortgage: Option<MortgageFinancingSpec>,
}

fn default_land_value_fraction_ppb() -> i64 {
    200_000_000
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct PropertyRentedFractionSpec {
    pub month: u32,
    pub property_id: String,
    pub rented_fraction_ppb: i64,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CapitalImprovementSpec {
    pub month: u32,
    pub property_id: String,
    pub amount: Money,
    #[serde(default)]
    pub description: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct PropertySaleSpec {
    pub month: u32,
    pub property_id: String,
    /// Seller closing costs in basis points, where 10_000 is 100%.
    pub closing_cost_bps: u32,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct MortgageInterestDeductionSpec {
    pub liability_id: String,
    pub owner_agent_id: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct PropertyTaxPolicySpec {
    pub property_id: String,
    pub owner_agent_id: String,
    #[serde(default = "default_account_id")]
    pub from_account_id: String,
    pub tax_authority_agent_id: String,
    #[serde(default = "default_account_id")]
    pub tax_authority_account_id: String,
    #[serde(default)]
    pub annual_tax_rate_ppb: Option<i64>,
    #[serde(default)]
    pub start_month: u32,
    #[serde(default)]
    pub end_month: Option<u32>,
}

fn default_account_id() -> String {
    "checking".into()
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SeriesSpec {
    pub series_id: String,
    pub snapshots: u32,
    /// Flattened row-major `[rollout][snapshot]` integer values.
    pub values: Vec<i64>,
}

impl SeriesSpec {
    pub fn value(&self, rollout: u32, snapshot: u32) -> Option<i64> {
        if snapshot >= self.snapshots {
            return None;
        }
        let index =
            usize::try_from(u64::from(rollout) * u64::from(self.snapshots) + u64::from(snapshot))
                .ok()?;
        self.values.get(index).copied()
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct AccountBalance {
    pub account: AccountRef,
    pub balance: Money,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct MonthOutput {
    pub month: u32,
    pub balances: Vec<AccountBalance>,
    pub properties: Vec<PropertyState>,
    pub mortgages: Vec<MortgageState>,
    pub tax_liabilities: Vec<TaxLiabilityState>,
    pub failed: bool,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct TaxLiabilityState {
    pub agent_id: String,
    pub jurisdiction_id: String,
    pub tax_year_end_month: u32,
    pub amount_owed: Money,
    pub active: bool,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct PropertyState {
    pub property_id: String,
    pub location_id: String,
    pub owner_agent_id: String,
    pub purchase_month: u32,
    pub adjusted_basis: Money,
    pub rented_fraction_ppb: i64,
    pub building_basis_initial: Money,
    pub building_basis: Money,
    pub cumulative_depreciation: Money,
    pub depreciation_ytd: Money,
    pub contribution_used: Money,
    pub equity_ledger: Money,
    pub active: bool,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct MortgageState {
    pub liability_id: String,
    pub property_id: String,
    pub agent_id: String,
    pub payment_account_id: String,
    pub counterparty_agent_id: String,
    pub counterparty_account_id: String,
    pub origination_month: u32,
    pub annual_interest_rate_ppb: i64,
    pub term_months: u32,
    pub monthly_payment: Money,
    pub principal: Money,
    pub interest_paid_ytd: Money,
    pub rental_interest_paid_ytd: Money,
    pub principal_paid_ytd: Money,
    pub active: bool,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct LotDisposition {
    pub month: u32,
    pub cause_id: String,
    pub lot_id: String,
    pub units: Quantity,
    pub basis: Money,
    pub proceeds: Money,
    pub realized_gain: Money,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct ObligationOutcome {
    pub month: u32,
    pub obligation_id: String,
    pub obligation_type: String,
    pub from: AccountRef,
    pub to: AccountRef,
    pub amount_due: Money,
    pub amount_paid: Money,
    pub shortfall: Money,
    pub failure_active: bool,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct TaxAccrual {
    pub month: u32,
    pub agent_id: String,
    pub jurisdiction_id: String,
    pub ordinary_income: Money,
    pub short_term_gain: Money,
    pub long_term_gain: Money,
    pub section_1250_recapture: Money,
    pub rental_interest_deduction: Money,
    pub depreciation_deduction: Money,
    pub mortgage_interest_deduction: Money,
    pub itemized_deduction: Money,
    pub ordinary_taxable: Money,
    pub long_term_capital_gain_taxable: Money,
    pub ordinary_tax: Money,
    pub capital_gain_tax: Money,
    pub section_1250_tax: Money,
    pub total_tax: Money,
    pub capital_loss_carryforward: Money,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct TaxPaymentOutcome {
    pub month: u32,
    pub cause_id: String,
    pub agent_id: String,
    pub obligation_type: String,
    pub amount_due: Money,
    pub amount_paid: Money,
    pub shortfall: Money,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct TaxSettlementOutcome {
    pub month: u32,
    pub cause_id: String,
    pub agent_id: String,
    pub tax_year_end_month: u32,
    pub amount: Money,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct DistributionOutcome {
    pub month: u32,
    pub agent_id: String,
    pub holding_account_id: String,
    pub asset_id: String,
    pub units: Quantity,
    pub amount: Money,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct PropertyPurchaseOutcome {
    pub month: u32,
    pub cause_id: String,
    pub property_id: String,
    pub location_id: String,
    pub buyer_agent_id: String,
    pub purchase_price: Money,
    pub closing_cost: Money,
    pub adjusted_basis: Money,
    pub stake_contribution: Money,
    pub equity_ledger: Money,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct PropertySaleOutcome {
    pub month: u32,
    pub property_id: String,
    pub gross_proceeds: Money,
    pub mortgage_payoff: Money,
    pub net_cash_to_owner: Money,
    pub realized_gain: Money,
    pub depreciation_recapture: Money,
    pub section_121_exclusion: Money,
    pub long_term_capital_gain: Money,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct PropertyRentedFractionOutcome {
    pub month: u32,
    pub property_id: String,
    pub rented_fraction_ppb: i64,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct CapitalImprovementOutcome {
    pub month: u32,
    pub property_id: String,
    pub amount: Money,
    pub description: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct MortgageOriginationOutcome {
    pub month: u32,
    pub cause_id: String,
    pub liability_id: String,
    pub agent_id: String,
    pub payment_account_id: String,
    pub counterparty_agent_id: String,
    pub counterparty_account_id: String,
    pub property_id: String,
    pub principal: Money,
    pub annual_interest_rate_ppb: i64,
    pub term_months: u32,
    pub monthly_payment: Money,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct MortgagePaymentOutcome {
    pub month: u32,
    pub cause_id: String,
    pub liability_id: String,
    pub agent_id: String,
    pub counterparty_agent_id: String,
    pub property_id: String,
    pub from_account_id: String,
    pub to_account_id: String,
    pub interest: Money,
    pub principal: Money,
    pub total_payment: Money,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct RolloutOutput {
    pub rollout_id: u32,
    pub months: Vec<MonthOutput>,
    pub journal: Vec<JournalEntry>,
    pub dispositions: Vec<LotDisposition>,
    pub obligations: Vec<ObligationOutcome>,
    pub tax_accruals: Vec<TaxAccrual>,
    pub tax_payments: Vec<TaxPaymentOutcome>,
    pub tax_settlements: Vec<TaxSettlementOutcome>,
    pub distributions: Vec<DistributionOutcome>,
    pub property_purchases: Vec<PropertyPurchaseOutcome>,
    pub property_rented_fraction_events: Vec<PropertyRentedFractionOutcome>,
    pub capital_improvements: Vec<CapitalImprovementOutcome>,
    pub property_sales: Vec<PropertySaleOutcome>,
    pub mortgage_originations: Vec<MortgageOriginationOutcome>,
    pub mortgage_payments: Vec<MortgagePaymentOutcome>,
    pub failed_month: Option<u32>,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct SimulationOutput {
    pub schema_version: u32,
    pub rollouts: Vec<RolloutOutput>,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct RolloutSummary {
    pub rollout_id: u32,
    pub ending_balances: Vec<AccountBalance>,
    pub ending_properties: Vec<PropertyState>,
    pub ending_mortgages: Vec<MortgageState>,
    pub ending_tax_liabilities: Vec<TaxLiabilityState>,
    pub journal_entry_count: u64,
    pub disposition_count: u64,
    pub tax_accrual_count: u64,
    pub tax_payment_count: u64,
    pub tax_settlement_count: u64,
    pub distribution_count: u64,
    pub property_purchase_count: u64,
    pub property_rented_fraction_event_count: u64,
    pub capital_improvement_count: u64,
    pub property_sale_count: u64,
    pub mortgage_payment_count: u64,
    pub failed_month: Option<u32>,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct PopulationOutput {
    pub schema_version: u32,
    pub rollouts: Vec<RolloutSummary>,
}
