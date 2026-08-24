use serde::{Deserialize, Serialize};

use crate::{
    ledger::{AccountRef, JournalEntry},
    money::{Money, Quantity},
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
    pub scheduled_transfers: Vec<ScheduledTransferSpec>,
    #[serde(default)]
    pub recurring_transfers: Vec<RecurringTransferSpec>,
    #[serde(default)]
    pub obligations: Vec<ObligationSpec>,
    #[serde(default)]
    pub recurring_obligations: Vec<RecurringObligationSpec>,
    #[serde(default)]
    pub initial_lots: Vec<InitialLotSpec>,
    #[serde(default)]
    pub scheduled_sales: Vec<ScheduledSaleSpec>,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AccountSpec {
    pub account: AccountRef,
    pub opening_balance: Money,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ScheduledTransferSpec {
    pub month: u32,
    pub cause_id: String,
    pub from: AccountRef,
    pub to: AccountRef,
    pub amount: Money,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RecurringTransferSpec {
    pub start_month: u32,
    pub end_month: Option<u32>,
    pub cause_id: String,
    pub from: AccountRef,
    pub to: AccountRef,
    pub amount: Money,
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
    pub amount_due: Money,
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
    pub amount_due: Money,
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
    pub failed: bool,
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
pub struct RolloutOutput {
    pub rollout_id: u32,
    pub months: Vec<MonthOutput>,
    pub journal: Vec<JournalEntry>,
    pub dispositions: Vec<LotDisposition>,
    pub obligations: Vec<ObligationOutcome>,
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
    pub journal_entry_count: u64,
    pub disposition_count: u64,
    pub failed_month: Option<u32>,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct PopulationOutput {
    pub schema_version: u32,
    pub rollouts: Vec<RolloutSummary>,
}
