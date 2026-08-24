use std::collections::{BTreeMap, BTreeSet};

use rayon::prelude::*;
use thiserror::Error;

use crate::{
    fixture::{
        AccountBalance, FIXTURE_SCHEMA_VERSION, Fixture, InitialLotSpec, LotDisposition,
        MonthOutput, ObligationOutcome, PopulationOutput, RolloutOutput, RolloutSummary,
        SeriesSpec, SimulationOutput, TaxAccrual,
    },
    ledger::{AccountRef, JournalEntry, Ledger, LedgerError, Posting},
    money::{ArithmeticError, Money, Quantity, mul_div_round_half_up},
    tax::{TaxError, TaxFacts, assess, validate_rules},
};

const EXTERNAL_AGENT: &str = "__external__";
const OPENING_EQUITY: &str = "equity:opening";

#[derive(Debug, Error)]
pub enum SimulationError {
    #[error("unsupported fixture schema version {actual}; expected {expected}")]
    SchemaVersion { actual: u32, expected: u32 },
    #[error("fixture must contain at least one rollout")]
    EmptyRollouts,
    #[error("fixture horizon must contain at least one month")]
    EmptyHorizon,
    #[error("currency code {currency_code:?} must be three uppercase ASCII letters")]
    InvalidCurrencyCode { currency_code: String },
    #[error("currency quantum {currency_quantum:?} must be a positive exact decimal")]
    InvalidCurrencyQuantum { currency_quantum: String },
    #[error("fixture dimensions overflow the supported address space")]
    FixtureDimensions,
    #[error("duplicate account {agent_id}:{account_id}")]
    DuplicateAccount {
        agent_id: String,
        account_id: String,
    },
    #[error("{context} references unknown account {agent_id}:{account_id}")]
    UnknownAccountReference {
        context: String,
        agent_id: String,
        account_id: String,
    },
    #[error("duplicate series id {series_id:?}")]
    DuplicateSeries { series_id: String },
    #[error(
        "security series {series_id:?} contains non-positive value {value} at flat index {index}"
    )]
    InvalidSecurityPrice {
        series_id: String,
        index: usize,
        value: i64,
    },
    #[error("series {series_id:?} has {actual} values; expected {expected}")]
    SeriesShape {
        series_id: String,
        actual: usize,
        expected: usize,
    },
    #[error("missing series {series_id:?}")]
    MissingSeries { series_id: String },
    #[error("missing value {series_id:?} for rollout {rollout}, snapshot {snapshot}")]
    MissingSeriesValue {
        series_id: String,
        rollout: u32,
        snapshot: u32,
    },
    #[error("lot {lot_id:?} has invalid quantity scale {quantity_scale}")]
    InvalidQuantityScale { lot_id: String, quantity_scale: i64 },
    #[error("lot {lot_id:?} has non-positive units {units} or negative basis {basis}")]
    InvalidLot {
        lot_id: String,
        units: i64,
        basis: i64,
    },
    #[error(
        "FIFO pool {agent_id}:{account_id}:{asset_id} mixes quantity scales {first_scale} and {second_scale}"
    )]
    MixedQuantityScale {
        agent_id: String,
        account_id: String,
        asset_id: String,
        first_scale: i64,
        second_scale: i64,
    },
    #[error("duplicate lot id {lot_id:?}")]
    DuplicateLot { lot_id: String },
    #[error("sale {cause_id:?} has non-positive units {units}")]
    InvalidSaleUnits { cause_id: String, units: i64 },
    #[error("{kind} {cause_id:?} has non-positive amount {amount}")]
    InvalidAmount {
        kind: &'static str,
        cause_id: String,
        amount: i64,
    },
    #[error("{kind} {cause_id:?} is scheduled at month {month}, outside horizon {horizon}")]
    EventOutsideHorizon {
        kind: &'static str,
        cause_id: String,
        month: u32,
        horizon: u32,
    },
    #[error("recurring transfer {cause_id:?} ends at {end_month} before starting at {start_month}")]
    InvalidRecurringRange {
        cause_id: String,
        start_month: u32,
        end_month: u32,
    },
    #[error("{kind} identifier must not be empty")]
    EmptyIdentifier { kind: &'static str },
    #[error("unsupported income category {category:?}; only ordinary is implemented")]
    UnsupportedIncomeCategory { category: String },
    #[error("duplicate tax profile jurisdiction {agent_id}:{jurisdiction_id}")]
    DuplicateTaxJurisdiction {
        agent_id: String,
        jurisdiction_id: String,
    },
    #[error("sale {cause_id:?} references no lots for {agent_id}:{account_id}:{asset_id}")]
    MissingSalePool {
        cause_id: String,
        agent_id: String,
        account_id: String,
        asset_id: String,
    },
    #[error("sale {cause_id:?} requests {requested} units but only {available} are available")]
    InsufficientLotUnits {
        cause_id: String,
        requested: i64,
        available: i64,
    },
    #[error(transparent)]
    Ledger(#[from] LedgerError),
    #[error(transparent)]
    Arithmetic(#[from] ArithmeticError),
    #[error(transparent)]
    Tax(#[from] TaxError),
}

#[derive(Clone, Debug)]
struct LotState {
    spec: InitialLotSpec,
    units_remaining: Quantity,
    basis_remaining: Money,
}

#[derive(Clone, Debug)]
struct PlannedDisposition {
    lot_index: usize,
    units: Quantity,
    basis: Money,
    proceeds: Money,
    realized_gain: Money,
}

#[derive(Clone, Copy, Debug)]
struct ActiveObligation<'a> {
    authored_id: &'a str,
    obligation_type: &'a str,
    from: &'a AccountRef,
    to: &'a AccountRef,
    amount_due: Money,
}

#[derive(Debug)]
struct Recorder {
    capture_trace: bool,
    months: Vec<MonthOutput>,
    journal: Vec<JournalEntry>,
    dispositions: Vec<LotDisposition>,
    obligations: Vec<ObligationOutcome>,
    tax_accruals: Vec<TaxAccrual>,
    journal_entry_count: u64,
    disposition_count: u64,
    tax_accrual_count: u64,
}

impl Recorder {
    fn new(capture_trace: bool) -> Self {
        Self {
            capture_trace,
            months: Vec::new(),
            journal: Vec::new(),
            dispositions: Vec::new(),
            obligations: Vec::new(),
            tax_accruals: Vec::new(),
            journal_entry_count: 0,
            disposition_count: 0,
            tax_accrual_count: 0,
        }
    }

    fn apply_entry(
        &mut self,
        ledger: &mut Ledger,
        entry: JournalEntry,
    ) -> Result<(), SimulationError> {
        ledger.apply(&entry)?;
        self.journal_entry_count =
            self.journal_entry_count
                .checked_add(1)
                .ok_or(ArithmeticError::Overflow {
                    operation: "journal entry count",
                })?;
        if self.capture_trace {
            self.journal.push(entry);
        }
        Ok(())
    }

    fn record_disposition(&mut self, disposition: LotDisposition) -> Result<(), SimulationError> {
        self.disposition_count =
            self.disposition_count
                .checked_add(1)
                .ok_or(ArithmeticError::Overflow {
                    operation: "disposition count",
                })?;
        if self.capture_trace {
            self.dispositions.push(disposition);
        }
        Ok(())
    }

    fn record_obligation(&mut self, obligation: ObligationOutcome) {
        if self.capture_trace {
            self.obligations.push(obligation);
        }
    }

    fn record_tax_accrual(&mut self, accrual: TaxAccrual) -> Result<(), SimulationError> {
        self.tax_accrual_count =
            self.tax_accrual_count
                .checked_add(1)
                .ok_or(ArithmeticError::Overflow {
                    operation: "tax accrual count",
                })?;
        if self.capture_trace {
            self.tax_accruals.push(accrual);
        }
        Ok(())
    }

    fn record_month(&mut self, month: MonthOutput) {
        if self.capture_trace {
            self.months.push(month);
        }
    }
}

#[derive(Debug)]
struct RolloutComputation {
    rollout_id: u32,
    ending_balances: Vec<AccountBalance>,
    recorder: Recorder,
    failed_month: Option<u32>,
}

impl RolloutComputation {
    fn into_output(self) -> RolloutOutput {
        RolloutOutput {
            rollout_id: self.rollout_id,
            months: self.recorder.months,
            journal: self.recorder.journal,
            dispositions: self.recorder.dispositions,
            obligations: self.recorder.obligations,
            tax_accruals: self.recorder.tax_accruals,
            failed_month: self.failed_month,
        }
    }

    fn into_summary(self) -> RolloutSummary {
        RolloutSummary {
            rollout_id: self.rollout_id,
            ending_balances: self.ending_balances,
            journal_entry_count: self.recorder.journal_entry_count,
            disposition_count: self.recorder.disposition_count,
            tax_accrual_count: self.recorder.tax_accrual_count,
            failed_month: self.failed_month,
        }
    }
}

#[derive(Clone, Copy, Debug)]
pub struct ValidatedFixture<'a> {
    fixture: &'a Fixture,
}

impl<'a> ValidatedFixture<'a> {
    pub fn new(fixture: &'a Fixture) -> Result<Self, SimulationError> {
        validate_fixture(fixture)?;
        Ok(Self { fixture })
    }
}

pub fn simulate(fixture: &Fixture) -> Result<SimulationOutput, SimulationError> {
    simulate_validated(ValidatedFixture::new(fixture)?)
}

fn simulate_validated(fixture: ValidatedFixture<'_>) -> Result<SimulationOutput, SimulationError> {
    let rollouts: Result<Vec<_>, _> = (0..fixture.fixture.rollout_count)
        .into_par_iter()
        .map(|rollout_id| {
            simulate_rollout(fixture.fixture, rollout_id, true).map(RolloutComputation::into_output)
        })
        .collect();
    Ok(SimulationOutput {
        schema_version: FIXTURE_SCHEMA_VERSION,
        rollouts: rollouts?,
    })
}

/// Run every rollout while retaining only fixed-size per-rollout summaries.
///
/// This is the population/benchmark path. It executes the same state machine
/// as [`simulate`] without allocating monthly snapshots, journals, or event
/// traces for every rollout.
pub fn simulate_summaries(fixture: &Fixture) -> Result<PopulationOutput, SimulationError> {
    simulate_summaries_validated(ValidatedFixture::new(fixture)?)
}

pub fn simulate_summaries_validated(
    fixture: ValidatedFixture<'_>,
) -> Result<PopulationOutput, SimulationError> {
    let rollouts: Result<Vec<_>, _> = (0..fixture.fixture.rollout_count)
        .into_par_iter()
        .map(|rollout_id| {
            simulate_rollout(fixture.fixture, rollout_id, false)
                .map(RolloutComputation::into_summary)
        })
        .collect();
    Ok(PopulationOutput {
        schema_version: FIXTURE_SCHEMA_VERSION,
        rollouts: rollouts?,
    })
}

fn validate_fixture(fixture: &Fixture) -> Result<(), SimulationError> {
    if fixture.schema_version != FIXTURE_SCHEMA_VERSION {
        return Err(SimulationError::SchemaVersion {
            actual: fixture.schema_version,
            expected: FIXTURE_SCHEMA_VERSION,
        });
    }
    if fixture.rollout_count == 0 {
        return Err(SimulationError::EmptyRollouts);
    }
    if fixture.scenario.horizon_months == 0 {
        return Err(SimulationError::EmptyHorizon);
    }
    if fixture.currency_code.len() != 3
        || !fixture
            .currency_code
            .bytes()
            .all(|byte| byte.is_ascii_uppercase())
    {
        return Err(SimulationError::InvalidCurrencyCode {
            currency_code: fixture.currency_code.clone(),
        });
    }
    if !is_positive_decimal(&fixture.currency_quantum) {
        return Err(SimulationError::InvalidCurrencyQuantum {
            currency_quantum: fixture.currency_quantum.clone(),
        });
    }
    let snapshots = fixture
        .scenario
        .horizon_months
        .checked_add(1)
        .ok_or(SimulationError::FixtureDimensions)?;
    let expected = usize::try_from(u64::from(fixture.rollout_count) * u64::from(snapshots))
        .map_err(|_| SimulationError::FixtureDimensions)?;
    let mut series_ids = BTreeSet::new();
    for series in &fixture.series {
        validate_identifier("series", &series.series_id)?;
        if !series_ids.insert(series.series_id.clone()) {
            return Err(SimulationError::DuplicateSeries {
                series_id: series.series_id.clone(),
            });
        }
        if series.snapshots != snapshots || series.values.len() != expected {
            return Err(SimulationError::SeriesShape {
                series_id: series.series_id.clone(),
                actual: series.values.len(),
                expected,
            });
        }
        if series.series_id.starts_with("security:")
            && let Some((index, value)) = series
                .values
                .iter()
                .copied()
                .enumerate()
                .find(|(_, value)| *value <= 0)
        {
            return Err(SimulationError::InvalidSecurityPrice {
                series_id: series.series_id.clone(),
                index,
                value,
            });
        }
    }

    let mut accounts = BTreeSet::new();
    let mut agents = BTreeSet::new();
    for account in &fixture.scenario.accounts {
        agents.insert(account.account.agent_id.clone());
        if !accounts.insert(account.account.clone()) {
            return Err(SimulationError::DuplicateAccount {
                agent_id: account.account.agent_id.clone(),
                account_id: account.account.account_id.clone(),
            });
        }
    }
    for transfer in &fixture.scenario.scheduled_transfers {
        validate_identifier("scheduled transfer", &transfer.cause_id)?;
        validate_event_month(
            "scheduled transfer",
            &transfer.cause_id,
            transfer.month,
            fixture.scenario.horizon_months,
        )?;
        validate_positive_amount("scheduled transfer", &transfer.cause_id, transfer.amount)?;
        validate_income_category(transfer.income_category.as_deref())?;
        validate_account(&accounts, &transfer.from, &transfer.cause_id)?;
        validate_account(&accounts, &transfer.to, &transfer.cause_id)?;
    }
    for transfer in &fixture.scenario.recurring_transfers {
        validate_identifier("recurring transfer", &transfer.cause_id)?;
        validate_event_month(
            "recurring transfer",
            &transfer.cause_id,
            transfer.start_month,
            fixture.scenario.horizon_months,
        )?;
        if let Some(end_month) = transfer.end_month
            && end_month < transfer.start_month
        {
            return Err(SimulationError::InvalidRecurringRange {
                cause_id: transfer.cause_id.clone(),
                start_month: transfer.start_month,
                end_month,
            });
        }
        validate_positive_amount("recurring transfer", &transfer.cause_id, transfer.amount)?;
        validate_income_category(transfer.income_category.as_deref())?;
        validate_account(&accounts, &transfer.from, &transfer.cause_id)?;
        validate_account(&accounts, &transfer.to, &transfer.cause_id)?;
    }
    for obligation in &fixture.scenario.obligations {
        validate_identifier("obligation", &obligation.obligation_id)?;
        validate_identifier("obligation type", &obligation.obligation_type)?;
        validate_event_month(
            "obligation",
            &obligation.obligation_id,
            obligation.month,
            fixture.scenario.horizon_months,
        )?;
        validate_positive_amount(
            "obligation",
            &obligation.obligation_id,
            obligation.amount_due,
        )?;
        validate_account(&accounts, &obligation.from, &obligation.obligation_id)?;
        validate_account(&accounts, &obligation.to, &obligation.obligation_id)?;
    }
    for obligation in &fixture.scenario.recurring_obligations {
        validate_identifier("recurring obligation", &obligation.obligation_id)?;
        validate_identifier("obligation type", &obligation.obligation_type)?;
        validate_event_month(
            "recurring obligation",
            &obligation.obligation_id,
            obligation.start_month,
            fixture.scenario.horizon_months,
        )?;
        if let Some(end_month) = obligation.end_month
            && end_month < obligation.start_month
        {
            return Err(SimulationError::InvalidRecurringRange {
                cause_id: obligation.obligation_id.clone(),
                start_month: obligation.start_month,
                end_month,
            });
        }
        validate_positive_amount(
            "recurring obligation",
            &obligation.obligation_id,
            obligation.amount_due,
        )?;
        validate_account(&accounts, &obligation.from, &obligation.obligation_id)?;
        validate_account(&accounts, &obligation.to, &obligation.obligation_id)?;
    }

    let mut lots = BTreeSet::new();
    let mut pool_scales = BTreeMap::new();
    for lot in &fixture.scenario.initial_lots {
        validate_identifier("lot", &lot.lot_id)?;
        validate_identifier("asset", &lot.asset_id)?;
        if lot.quantity_scale <= 0 {
            return Err(SimulationError::InvalidQuantityScale {
                lot_id: lot.lot_id.clone(),
                quantity_scale: lot.quantity_scale,
            });
        }
        if lot.units.0 <= 0 || lot.basis.0 < 0 {
            return Err(SimulationError::InvalidLot {
                lot_id: lot.lot_id.clone(),
                units: lot.units.0,
                basis: lot.basis.0,
            });
        }
        if !lots.insert(lot.lot_id.clone()) {
            return Err(SimulationError::DuplicateLot {
                lot_id: lot.lot_id.clone(),
            });
        }
        let pool = (
            lot.agent_id.clone(),
            lot.account_id.clone(),
            lot.asset_id.clone(),
        );
        if let Some(first_scale) = pool_scales.insert(pool, lot.quantity_scale)
            && first_scale != lot.quantity_scale
        {
            return Err(SimulationError::MixedQuantityScale {
                agent_id: lot.agent_id.clone(),
                account_id: lot.account_id.clone(),
                asset_id: lot.asset_id.clone(),
                first_scale,
                second_scale: lot.quantity_scale,
            });
        }
        if !agents.contains(&lot.agent_id) {
            return Err(SimulationError::UnknownAccountReference {
                context: format!("lot {:?}", lot.lot_id),
                agent_id: lot.agent_id.clone(),
                account_id: lot.account_id.clone(),
            });
        }
    }
    for sale in &fixture.scenario.scheduled_sales {
        validate_identifier("sale", &sale.cause_id)?;
        validate_identifier("asset", &sale.asset_id)?;
        validate_event_month(
            "sale",
            &sale.cause_id,
            sale.month,
            fixture.scenario.horizon_months,
        )?;
        if sale.units.0 <= 0 {
            return Err(SimulationError::InvalidSaleUnits {
                cause_id: sale.cause_id.clone(),
                units: sale.units.0,
            });
        }
        validate_account(
            &accounts,
            &AccountRef::new(&sale.agent_id, &sale.proceeds_account_id),
            &sale.cause_id,
        )?;
        if !pool_scales.contains_key(&(
            sale.agent_id.clone(),
            sale.account_id.clone(),
            sale.asset_id.clone(),
        )) {
            return Err(SimulationError::MissingSalePool {
                cause_id: sale.cause_id.clone(),
                agent_id: sale.agent_id.clone(),
                account_id: sale.account_id.clone(),
                asset_id: sale.asset_id.clone(),
            });
        }
        let series_id = format!("security:{}", sale.asset_id);
        if !series_ids.contains(&series_id) {
            return Err(SimulationError::MissingSeries { series_id });
        }
    }
    let mut tax_jurisdictions = BTreeSet::new();
    for profile in &fixture.scenario.tax_profiles {
        validate_identifier("tax profile agent", &profile.agent_id)?;
        if !agents.contains(&profile.agent_id) {
            return Err(SimulationError::UnknownAccountReference {
                context: "tax profile".into(),
                agent_id: profile.agent_id.clone(),
                account_id: "checking".into(),
            });
        }
        validate_account(
            &accounts,
            &AccountRef::new(&profile.agent_id, &profile.payment_account_id),
            "tax profile payment account",
        )?;
        validate_account(
            &accounts,
            &AccountRef::new(
                &profile.tax_authority_agent_id,
                &profile.tax_authority_account_id,
            ),
            "tax profile authority account",
        )?;
        for rules in &profile.jurisdictions {
            validate_identifier("tax jurisdiction", &rules.jurisdiction_id)?;
            validate_rules(rules)?;
            if !tax_jurisdictions.insert((profile.agent_id.clone(), rules.jurisdiction_id.clone()))
            {
                return Err(SimulationError::DuplicateTaxJurisdiction {
                    agent_id: profile.agent_id.clone(),
                    jurisdiction_id: rules.jurisdiction_id.clone(),
                });
            }
        }
    }
    Ok(())
}

fn validate_event_month(
    kind: &'static str,
    cause_id: &str,
    month: u32,
    horizon: u32,
) -> Result<(), SimulationError> {
    if month >= horizon {
        return Err(SimulationError::EventOutsideHorizon {
            kind,
            cause_id: cause_id.into(),
            month,
            horizon,
        });
    }
    Ok(())
}

fn validate_identifier(kind: &'static str, value: &str) -> Result<(), SimulationError> {
    if value.trim().is_empty() {
        return Err(SimulationError::EmptyIdentifier { kind });
    }
    Ok(())
}

fn is_positive_decimal(value: &str) -> bool {
    let mut saw_digit = false;
    let mut saw_nonzero = false;
    let mut saw_dot = false;
    let bytes = value.as_bytes();
    if bytes.is_empty() || bytes.first() == Some(&b'.') || bytes.last() == Some(&b'.') {
        return false;
    }
    for byte in bytes {
        match byte {
            b'0'..=b'9' => {
                saw_digit = true;
                saw_nonzero |= *byte != b'0';
            }
            b'.' if !saw_dot => saw_dot = true,
            _ => return false,
        }
    }
    saw_digit && saw_nonzero
}

fn validate_positive_amount(
    kind: &'static str,
    cause_id: &str,
    amount: Money,
) -> Result<(), SimulationError> {
    if amount.0 <= 0 {
        return Err(SimulationError::InvalidAmount {
            kind,
            cause_id: cause_id.into(),
            amount: amount.0,
        });
    }
    Ok(())
}

fn validate_income_category(category: Option<&str>) -> Result<(), SimulationError> {
    if let Some(category) = category
        && category != "ordinary"
    {
        return Err(SimulationError::UnsupportedIncomeCategory {
            category: category.into(),
        });
    }
    Ok(())
}

fn validate_account(
    accounts: &BTreeSet<AccountRef>,
    account: &AccountRef,
    context: &str,
) -> Result<(), SimulationError> {
    if !accounts.contains(account) {
        return Err(SimulationError::UnknownAccountReference {
            context: context.into(),
            agent_id: account.agent_id.clone(),
            account_id: account.account_id.clone(),
        });
    }
    Ok(())
}

fn simulate_rollout(
    fixture: &Fixture,
    rollout_id: u32,
    capture_trace: bool,
) -> Result<RolloutComputation, SimulationError> {
    let mut accounts: Vec<AccountRef> = fixture
        .scenario
        .accounts
        .iter()
        .map(|spec| spec.account.clone())
        .collect();
    for spec in &fixture.scenario.accounts {
        accounts.push(AccountRef::new(&spec.account.agent_id, OPENING_EQUITY));
    }
    accounts.push(AccountRef::new(EXTERNAL_AGENT, "boundary"));
    for lot in &fixture.scenario.initial_lots {
        accounts.push(asset_basis_account(lot));
        accounts.push(realized_gain_account(&lot.agent_id));
        accounts.push(AccountRef::new(&lot.agent_id, OPENING_EQUITY));
    }
    for profile in &fixture.scenario.tax_profiles {
        for rules in &profile.jurisdictions {
            accounts.push(tax_expense_account(
                &profile.agent_id,
                &rules.jurisdiction_id,
            ));
            accounts.push(tax_liability_account(
                &profile.agent_id,
                &rules.jurisdiction_id,
            ));
        }
    }
    accounts.sort();
    accounts.dedup();
    let mut ledger = Ledger::with_accounts(accounts);
    let mut recorder = Recorder::new(capture_trace);
    let mut tax_facts: BTreeMap<(String, String), TaxFacts> = fixture
        .scenario
        .tax_profiles
        .iter()
        .flat_map(|profile| {
            profile.jurisdictions.iter().map(|rules| {
                (
                    (profile.agent_id.clone(), rules.jurisdiction_id.clone()),
                    TaxFacts::default(),
                )
            })
        })
        .collect();

    for spec in &fixture.scenario.accounts {
        if spec.opening_balance != Money(0) {
            recorder.apply_entry(
                &mut ledger,
                JournalEntry {
                    month: 0,
                    cause_id: format!(
                        "opening:{}:{}",
                        spec.account.agent_id, spec.account.account_id
                    ),
                    postings: vec![
                        Posting {
                            account: spec.account.clone(),
                            amount: spec.opening_balance,
                        },
                        Posting {
                            account: AccountRef::new(&spec.account.agent_id, OPENING_EQUITY),
                            amount: spec.opening_balance.checked_neg()?,
                        },
                    ],
                },
            )?;
        }
    }

    let mut lots = Vec::with_capacity(fixture.scenario.initial_lots.len());
    for spec in &fixture.scenario.initial_lots {
        if spec.basis != Money(0) {
            recorder.apply_entry(
                &mut ledger,
                JournalEntry {
                    month: 0,
                    cause_id: format!("opening-lot:{}", spec.lot_id),
                    postings: vec![
                        Posting {
                            account: asset_basis_account(spec),
                            amount: spec.basis,
                        },
                        Posting {
                            account: AccountRef::new(&spec.agent_id, OPENING_EQUITY),
                            amount: spec.basis.checked_neg()?,
                        },
                    ],
                },
            )?;
        }
        lots.push(LotState {
            spec: spec.clone(),
            units_remaining: spec.units,
            basis_remaining: spec.basis,
        });
    }

    let mut failed_month = None;
    recorder.record_month(month_output(0, &ledger, false));
    for month in 0..fixture.scenario.horizon_months {
        if failed_month.is_some() {
            recorder.record_month(month_output(month + 1, &ledger, true));
            continue;
        }
        for transfer in fixture
            .scenario
            .scheduled_transfers
            .iter()
            .filter(|transfer| transfer.month == month)
        {
            transfer_money(
                &mut ledger,
                &mut recorder,
                month,
                &transfer.cause_id,
                &transfer.from,
                &transfer.to,
                transfer.amount,
            )?;
            record_transfer_income(
                &mut tax_facts,
                &transfer.to.agent_id,
                transfer.income_category.as_deref(),
                transfer.amount,
            )?;
        }
        for transfer in fixture
            .scenario
            .recurring_transfers
            .iter()
            .filter(|transfer| {
                transfer.start_month <= month && transfer.end_month.is_none_or(|end| month <= end)
            })
        {
            transfer_money(
                &mut ledger,
                &mut recorder,
                month,
                &transfer.cause_id,
                &transfer.from,
                &transfer.to,
                transfer.amount,
            )?;
            record_transfer_income(
                &mut tax_facts,
                &transfer.to.agent_id,
                transfer.income_category.as_deref(),
                transfer.amount,
            )?;
        }
        for sale in fixture
            .scenario
            .scheduled_sales
            .iter()
            .filter(|sale| sale.month == month)
        {
            execute_sale(
                fixture,
                rollout_id,
                &mut ledger,
                &mut recorder,
                &mut lots,
                &mut tax_facts,
                sale,
            )?;
        }
        let active_obligations: Vec<_> = fixture
            .scenario
            .obligations
            .iter()
            .filter(|obligation| obligation.month == month)
            .map(|obligation| ActiveObligation {
                authored_id: &obligation.obligation_id,
                obligation_type: &obligation.obligation_type,
                from: &obligation.from,
                to: &obligation.to,
                amount_due: obligation.amount_due,
            })
            .chain(
                fixture
                    .scenario
                    .recurring_obligations
                    .iter()
                    .filter(|obligation| {
                        obligation.start_month <= month
                            && obligation.end_month.is_none_or(|end| month <= end)
                    })
                    .map(|obligation| ActiveObligation {
                        authored_id: &obligation.obligation_id,
                        obligation_type: &obligation.obligation_type,
                        from: &obligation.from,
                        to: &obligation.to,
                        amount_due: obligation.amount_due,
                    }),
            )
            .collect();
        if settle_obligations(&mut ledger, &mut recorder, month, &active_obligations)? {
            failed_month = Some(month);
        }
        if failed_month.is_none() && (month + 1) % 12 == 0 {
            accrue_year_end_taxes(fixture, &mut ledger, &mut recorder, &mut tax_facts, month)?;
        }
        recorder.record_month(month_output(month + 1, &ledger, failed_month.is_some()));
    }
    debug_assert_eq!(ledger.trial_balance(), 0);
    Ok(RolloutComputation {
        rollout_id,
        ending_balances: account_balances(&ledger, failed_month.is_some()),
        recorder,
        failed_month,
    })
}

fn record_transfer_income(
    tax_facts: &mut BTreeMap<(String, String), TaxFacts>,
    recipient_agent_id: &str,
    income_category: Option<&str>,
    amount: Money,
) -> Result<(), SimulationError> {
    if income_category != Some("ordinary") {
        return Ok(());
    }
    for ((agent_id, _), facts) in tax_facts {
        if agent_id == recipient_agent_id {
            facts.ordinary_income = facts.ordinary_income.checked_add(amount)?;
        }
    }
    Ok(())
}

fn record_capital_gain(
    tax_facts: &mut BTreeMap<(String, String), TaxFacts>,
    agent_id: &str,
    gain: Money,
    long_term: bool,
) -> Result<(), SimulationError> {
    for ((taxpayer, _), facts) in tax_facts {
        if taxpayer != agent_id {
            continue;
        }
        if long_term {
            facts.long_term_gain = facts.long_term_gain.checked_add(gain)?;
        } else {
            facts.short_term_gain = facts.short_term_gain.checked_add(gain)?;
        }
    }
    Ok(())
}

fn accrue_year_end_taxes(
    fixture: &Fixture,
    ledger: &mut Ledger,
    recorder: &mut Recorder,
    tax_facts: &mut BTreeMap<(String, String), TaxFacts>,
    month: u32,
) -> Result<(), SimulationError> {
    for profile in &fixture.scenario.tax_profiles {
        for rules in &profile.jurisdictions {
            let key = (profile.agent_id.clone(), rules.jurisdiction_id.clone());
            let facts = *tax_facts
                .get(&key)
                .expect("validated tax profile has initialized facts");
            let assessment = assess(facts, rules)?;
            if assessment.total_tax != Money(0) {
                recorder.apply_entry(
                    ledger,
                    JournalEntry {
                        month,
                        cause_id: format!(
                            "tax-accrual:{}:{}:{month}",
                            profile.agent_id, rules.jurisdiction_id
                        ),
                        postings: vec![
                            Posting {
                                account: tax_expense_account(
                                    &profile.agent_id,
                                    &rules.jurisdiction_id,
                                ),
                                amount: assessment.total_tax,
                            },
                            Posting {
                                account: tax_liability_account(
                                    &profile.agent_id,
                                    &rules.jurisdiction_id,
                                ),
                                amount: assessment.total_tax.checked_neg()?,
                            },
                        ],
                    },
                )?;
            }
            recorder.record_tax_accrual(TaxAccrual {
                month,
                agent_id: profile.agent_id.clone(),
                jurisdiction_id: rules.jurisdiction_id.clone(),
                ordinary_income: facts.ordinary_income,
                short_term_gain: facts.short_term_gain,
                long_term_gain: facts.long_term_gain,
                ordinary_taxable: assessment.ordinary_taxable,
                long_term_capital_gain_taxable: assessment.long_term_capital_gain_taxable,
                ordinary_tax: assessment.ordinary_tax,
                capital_gain_tax: assessment.capital_gain_tax,
                total_tax: assessment.total_tax,
                capital_loss_carryforward: assessment.capital_loss_carryforward,
            })?;
            tax_facts.insert(
                key,
                TaxFacts {
                    capital_loss_carryforward: assessment.capital_loss_carryforward,
                    ..TaxFacts::default()
                },
            );
        }
    }
    Ok(())
}

fn settle_obligations(
    ledger: &mut Ledger,
    recorder: &mut Recorder,
    month: u32,
    obligations: &[ActiveObligation<'_>],
) -> Result<bool, SimulationError> {
    let mut due_by_source = BTreeMap::<AccountRef, Money>::new();
    for obligation in obligations {
        let due = due_by_source
            .get(obligation.from)
            .copied()
            .unwrap_or_default()
            .checked_add(obligation.amount_due)?;
        due_by_source.insert(obligation.from.clone(), due);
    }
    let funded_by_source: BTreeMap<_, _> = due_by_source
        .into_iter()
        .map(|(account, due)| {
            let funded = ledger
                .balance(&account)
                .map(|available| available.0 >= due.0)?;
            Ok((account, funded))
        })
        .collect::<Result<_, LedgerError>>()?;

    let mut any_failure = false;
    for obligation in obligations {
        let funded = funded_by_source[obligation.from];
        let firing_id = format!("{}_m{month}", obligation.authored_id);
        let (amount_paid, shortfall) = if funded {
            transfer_money(
                ledger,
                recorder,
                month,
                &firing_id,
                obligation.from,
                obligation.to,
                obligation.amount_due,
            )?;
            (obligation.amount_due, Money(0))
        } else {
            any_failure = true;
            (Money(0), obligation.amount_due)
        };
        recorder.record_obligation(ObligationOutcome {
            month,
            obligation_id: firing_id,
            obligation_type: obligation.obligation_type.into(),
            from: obligation.from.clone(),
            to: obligation.to.clone(),
            amount_due: obligation.amount_due,
            amount_paid,
            shortfall,
            failure_active: !funded,
        });
    }
    Ok(any_failure)
}

fn transfer_money(
    ledger: &mut Ledger,
    recorder: &mut Recorder,
    month: u32,
    cause_id: &str,
    from: &AccountRef,
    to: &AccountRef,
    amount: Money,
) -> Result<(), SimulationError> {
    recorder.apply_entry(
        ledger,
        JournalEntry {
            month,
            cause_id: cause_id.into(),
            postings: vec![
                Posting {
                    account: from.clone(),
                    amount: amount.checked_neg()?,
                },
                Posting {
                    account: to.clone(),
                    amount,
                },
            ],
        },
    )
}

fn execute_sale(
    fixture: &Fixture,
    rollout_id: u32,
    ledger: &mut Ledger,
    recorder: &mut Recorder,
    lots: &mut [LotState],
    tax_facts: &mut BTreeMap<(String, String), TaxFacts>,
    sale: &crate::fixture::ScheduledSaleSpec,
) -> Result<(), SimulationError> {
    let mut candidates: Vec<usize> = lots
        .iter()
        .enumerate()
        .filter(|(_, lot)| {
            lot.spec.agent_id == sale.agent_id
                && lot.spec.account_id == sale.account_id
                && lot.spec.asset_id == sale.asset_id
                && lot.units_remaining.0 > 0
        })
        .map(|(index, _)| index)
        .collect();
    if candidates.is_empty() {
        return Err(SimulationError::MissingSalePool {
            cause_id: sale.cause_id.clone(),
            agent_id: sale.agent_id.clone(),
            account_id: sale.account_id.clone(),
            asset_id: sale.asset_id.clone(),
        });
    }
    candidates.sort_by_key(|index| {
        (
            lots[*index].spec.purchase_month,
            lots[*index].spec.lot_id.clone(),
        )
    });
    let available = candidates.iter().try_fold(0_i64, |total, index| {
        total
            .checked_add(lots[*index].units_remaining.0)
            .ok_or(ArithmeticError::Overflow {
                operation: "sale pool quantity",
            })
    })?;
    if sale.units.0 > available {
        return Err(SimulationError::InsufficientLotUnits {
            cause_id: sale.cause_id.clone(),
            requested: sale.units.0,
            available,
        });
    }
    let series_id = format!("security:{}", sale.asset_id);
    let price = Money(series_value(fixture, &series_id, rollout_id, sale.month)?);
    let mut remaining = sale.units.0;
    let mut planned = Vec::new();
    let mut total_proceeds = Money(0);
    let mut total_gain = Money(0);
    for index in candidates {
        if remaining == 0 {
            break;
        }
        let lot = &lots[index];
        let units = remaining.min(lot.units_remaining.0);
        let basis = Money(mul_div_round_half_up(
            lot.basis_remaining.0,
            units,
            lot.units_remaining.0,
            "FIFO basis allocation",
        )?);
        let proceeds = Money(mul_div_round_half_up(
            price.0,
            units,
            lot.spec.quantity_scale,
            "sale proceeds",
        )?);
        let realized_gain = proceeds.checked_sub(basis)?;
        total_proceeds = total_proceeds.checked_add(proceeds)?;
        total_gain = total_gain.checked_add(realized_gain)?;
        planned.push(PlannedDisposition {
            lot_index: index,
            units: Quantity(units),
            basis,
            proceeds,
            realized_gain,
        });
        remaining -= units;
    }
    debug_assert_eq!(remaining, 0);

    let mut postings = Vec::with_capacity(planned.len() + 2);
    postings.push(Posting {
        account: AccountRef::new(&sale.agent_id, &sale.proceeds_account_id),
        amount: total_proceeds,
    });
    for item in &planned {
        postings.push(Posting {
            account: asset_basis_account(&lots[item.lot_index].spec),
            amount: item.basis.checked_neg()?,
        });
    }
    postings.push(Posting {
        account: realized_gain_account(&sale.agent_id),
        amount: total_gain.checked_neg()?,
    });
    recorder.apply_entry(
        ledger,
        JournalEntry {
            month: sale.month,
            cause_id: sale.cause_id.clone(),
            postings,
        },
    )?;

    for item in planned {
        let lot = &mut lots[item.lot_index];
        let long_term = i64::from(sale.month) - i64::from(lot.spec.purchase_month) >= 12;
        lot.units_remaining.0 -= item.units.0;
        lot.basis_remaining = lot.basis_remaining.checked_sub(item.basis)?;
        record_capital_gain(tax_facts, &sale.agent_id, item.realized_gain, long_term)?;
        recorder.record_disposition(LotDisposition {
            month: sale.month,
            cause_id: sale.cause_id.clone(),
            lot_id: lot.spec.lot_id.clone(),
            units: item.units,
            basis: item.basis,
            proceeds: item.proceeds,
            realized_gain: item.realized_gain,
        })?;
    }
    Ok(())
}

fn series_value(
    fixture: &Fixture,
    series_id: &str,
    rollout: u32,
    snapshot: u32,
) -> Result<i64, SimulationError> {
    let series: &SeriesSpec = fixture
        .series
        .iter()
        .find(|series| series.series_id == series_id)
        .ok_or_else(|| SimulationError::MissingSeries {
            series_id: series_id.into(),
        })?;
    series
        .value(rollout, snapshot)
        .ok_or_else(|| SimulationError::MissingSeriesValue {
            series_id: series_id.into(),
            rollout,
            snapshot,
        })
}

fn asset_basis_account(lot: &InitialLotSpec) -> AccountRef {
    AccountRef::new(
        &lot.agent_id,
        format!("asset-basis:{}:{}", lot.account_id, lot.asset_id),
    )
}

fn realized_gain_account(agent_id: &str) -> AccountRef {
    AccountRef::new(agent_id, "income:realized-gain")
}

fn tax_expense_account(agent_id: &str, jurisdiction_id: &str) -> AccountRef {
    AccountRef::new(agent_id, format!("expense:tax:{jurisdiction_id}"))
}

fn tax_liability_account(agent_id: &str, jurisdiction_id: &str) -> AccountRef {
    AccountRef::new(agent_id, format!("liability:tax:{jurisdiction_id}"))
}

fn month_output(month: u32, ledger: &Ledger, failed: bool) -> MonthOutput {
    MonthOutput {
        month,
        balances: account_balances(ledger, failed),
        failed,
    }
}

fn account_balances(ledger: &Ledger, failed: bool) -> Vec<AccountBalance> {
    ledger
        .balances()
        .iter()
        .map(|(account, balance)| AccountBalance {
            account: account.clone(),
            balance: if failed { Money(0) } else { *balance },
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use crate::fixture::{
        AccountSpec, InitialLotSpec, ObligationSpec, RecurringObligationSpec, ScenarioSpec,
        ScheduledSaleSpec, ScheduledTransferSpec, SeriesSpec,
    };

    use super::*;

    fn minimal_fixture() -> Fixture {
        Fixture {
            schema_version: FIXTURE_SCHEMA_VERSION,
            currency_code: "USD".into(),
            currency_quantum: "0.01".into(),
            rollout_count: 1,
            scenario: ScenarioSpec {
                horizon_months: 1,
                accounts: vec![AccountSpec {
                    account: AccountRef::new("alice", "checking"),
                    opening_balance: Money(0),
                }],
                scheduled_transfers: vec![],
                recurring_transfers: vec![],
                obligations: vec![],
                recurring_obligations: vec![],
                initial_lots: vec![],
                scheduled_sales: vec![],
                tax_profiles: vec![],
            },
            series: vec![],
        }
    }

    #[test]
    fn rejects_invalid_fixture_metadata() {
        let mut fixture = minimal_fixture();
        fixture.rollout_count = 0;
        assert!(matches!(
            simulate(&fixture),
            Err(SimulationError::EmptyRollouts)
        ));

        let mut fixture = minimal_fixture();
        fixture.scenario.horizon_months = 0;
        assert!(matches!(
            simulate(&fixture),
            Err(SimulationError::EmptyHorizon)
        ));

        let mut fixture = minimal_fixture();
        fixture.currency_code = "usd".into();
        assert!(matches!(
            simulate(&fixture),
            Err(SimulationError::InvalidCurrencyCode { .. })
        ));

        let mut fixture = minimal_fixture();
        fixture.currency_quantum = "0".into();
        assert!(matches!(
            simulate(&fixture),
            Err(SimulationError::InvalidCurrencyQuantum { .. })
        ));
    }

    #[test]
    fn rejects_invalid_references_before_rollout_execution() {
        let mut fixture = minimal_fixture();
        fixture
            .scenario
            .scheduled_transfers
            .push(ScheduledTransferSpec {
                month: 0,
                cause_id: "unknown-source".into(),
                from: AccountRef::new("missing", "checking"),
                to: AccountRef::new("alice", "checking"),
                amount: Money(1),
                income_category: None,
            });
        assert!(matches!(
            simulate(&fixture),
            Err(SimulationError::UnknownAccountReference { .. })
        ));
    }

    #[test]
    fn rejects_mixed_quantity_scales_and_invalid_security_prices() {
        let mut fixture = minimal_fixture();
        fixture.scenario.initial_lots = vec![
            InitialLotSpec {
                lot_id: "a".into(),
                agent_id: "alice".into(),
                account_id: "brokerage".into(),
                asset_id: "vti".into(),
                purchase_month: -2,
                quantity_scale: 1_000_000,
                units: Quantity(1_000_000),
                basis: Money(1),
            },
            InitialLotSpec {
                lot_id: "b".into(),
                agent_id: "alice".into(),
                account_id: "brokerage".into(),
                asset_id: "vti".into(),
                purchase_month: -1,
                quantity_scale: 1_000,
                units: Quantity(1_000),
                basis: Money(1),
            },
        ];
        assert!(matches!(
            simulate(&fixture),
            Err(SimulationError::MixedQuantityScale { .. })
        ));

        let mut fixture = minimal_fixture();
        fixture.series.push(SeriesSpec {
            series_id: "security:vti".into(),
            snapshots: 2,
            values: vec![100, -1],
        });
        assert!(matches!(
            simulate(&fixture),
            Err(SimulationError::InvalidSecurityPrice {
                index: 1,
                value: -1,
                ..
            })
        ));
    }

    #[test]
    fn transfer_and_fifo_sale_remain_balanced() {
        let alice_cash = AccountRef::new("alice", "checking");
        let bob_cash = AccountRef::new("bob", "checking");
        let fixture = Fixture {
            schema_version: FIXTURE_SCHEMA_VERSION,
            currency_code: "USD".into(),
            currency_quantum: "0.01".into(),
            rollout_count: 2,
            scenario: ScenarioSpec {
                horizon_months: 2,
                accounts: vec![
                    AccountSpec {
                        account: alice_cash.clone(),
                        opening_balance: Money(1_000),
                    },
                    AccountSpec {
                        account: bob_cash.clone(),
                        opening_balance: Money(2_000),
                    },
                ],
                scheduled_transfers: vec![ScheduledTransferSpec {
                    month: 0,
                    cause_id: "gift".into(),
                    from: bob_cash,
                    to: alice_cash,
                    amount: Money(500),
                    income_category: None,
                }],
                recurring_transfers: vec![],
                obligations: vec![],
                recurring_obligations: vec![],
                initial_lots: vec![InitialLotSpec {
                    lot_id: "lot-1".into(),
                    agent_id: "alice".into(),
                    account_id: "brokerage".into(),
                    asset_id: "vti".into(),
                    purchase_month: -12,
                    quantity_scale: 1_000_000,
                    units: Quantity(2_000_000),
                    basis: Money(20_000),
                }],
                scheduled_sales: vec![ScheduledSaleSpec {
                    month: 1,
                    cause_id: "sell-vti".into(),
                    agent_id: "alice".into(),
                    account_id: "brokerage".into(),
                    asset_id: "vti".into(),
                    units: Quantity(1_000_000),
                    proceeds_account_id: "checking".into(),
                }],
                tax_profiles: vec![],
            },
            series: vec![SeriesSpec {
                series_id: "security:vti".into(),
                snapshots: 3,
                values: vec![10_000, 15_000, 15_000, 10_000, 20_000, 20_000],
            }],
        };
        let output = simulate(&fixture).unwrap();
        let summaries = simulate_summaries(&fixture).unwrap();
        assert_eq!(output.rollouts.len(), 2);
        assert_eq!(summaries.rollouts.len(), 2);
        assert_eq!(output.rollouts[0].dispositions[0].proceeds, Money(15_000));
        assert_eq!(output.rollouts[1].dispositions[0].proceeds, Money(20_000));
        for (rollout, summary) in output.rollouts.iter().zip(&summaries.rollouts) {
            assert_eq!(summary.rollout_id, rollout.rollout_id);
            assert_eq!(
                summary.ending_balances,
                rollout.months.last().unwrap().balances
            );
            assert_eq!(summary.journal_entry_count, rollout.journal.len() as u64);
            assert_eq!(summary.disposition_count, rollout.dispositions.len() as u64);
            assert_eq!(summary.tax_accrual_count, rollout.tax_accruals.len() as u64);
            assert_eq!(summary.failed_month, rollout.failed_month);
        }
        for rollout in output.rollouts {
            for entry in rollout.journal {
                assert_eq!(
                    entry
                        .postings
                        .iter()
                        .map(|posting| i128::from(posting.amount.0))
                        .sum::<i128>(),
                    0
                );
            }
        }
    }

    #[test]
    fn oversell_is_rejected_before_any_disposition() {
        let alice_cash = AccountRef::new("alice", "checking");
        let fixture = Fixture {
            schema_version: FIXTURE_SCHEMA_VERSION,
            currency_code: "USD".into(),
            currency_quantum: "0.01".into(),
            rollout_count: 1,
            scenario: ScenarioSpec {
                horizon_months: 1,
                accounts: vec![AccountSpec {
                    account: alice_cash,
                    opening_balance: Money(0),
                }],
                scheduled_transfers: vec![],
                recurring_transfers: vec![],
                obligations: vec![],
                recurring_obligations: vec![],
                initial_lots: vec![InitialLotSpec {
                    lot_id: "lot-1".into(),
                    agent_id: "alice".into(),
                    account_id: "brokerage".into(),
                    asset_id: "vti".into(),
                    purchase_month: -1,
                    quantity_scale: 1_000_000,
                    units: Quantity(1_000_000),
                    basis: Money(10_000),
                }],
                scheduled_sales: vec![ScheduledSaleSpec {
                    month: 0,
                    cause_id: "oversell".into(),
                    agent_id: "alice".into(),
                    account_id: "brokerage".into(),
                    asset_id: "vti".into(),
                    units: Quantity(1_000_001),
                    proceeds_account_id: "checking".into(),
                }],
                tax_profiles: vec![],
            },
            series: vec![SeriesSpec {
                series_id: "security:vti".into(),
                snapshots: 2,
                values: vec![10_000, 10_000],
            }],
        };
        assert!(matches!(
            simulate(&fixture),
            Err(SimulationError::InsufficientLotUnits {
                requested: 1_000_001,
                available: 1_000_000,
                ..
            })
        ));
    }

    #[test]
    fn failure_stops_future_actions_and_zeroes_value_state() {
        let alice_cash = AccountRef::new("alice", "checking");
        let bob_cash = AccountRef::new("bob", "checking");
        let fixture = Fixture {
            schema_version: FIXTURE_SCHEMA_VERSION,
            currency_code: "USD".into(),
            currency_quantum: "0.01".into(),
            rollout_count: 1,
            scenario: ScenarioSpec {
                horizon_months: 2,
                accounts: vec![
                    AccountSpec {
                        account: alice_cash.clone(),
                        opening_balance: Money(100),
                    },
                    AccountSpec {
                        account: bob_cash.clone(),
                        opening_balance: Money(0),
                    },
                ],
                scheduled_transfers: vec![ScheduledTransferSpec {
                    month: 1,
                    cause_id: "must-not-run".into(),
                    from: alice_cash.clone(),
                    to: bob_cash.clone(),
                    amount: Money(1),
                    income_category: None,
                }],
                recurring_transfers: vec![],
                obligations: vec![ObligationSpec {
                    month: 0,
                    obligation_id: "too-large".into(),
                    obligation_type: "cash_spend".into(),
                    from: alice_cash,
                    to: bob_cash,
                    amount_due: Money(101),
                }],
                recurring_obligations: vec![],
                initial_lots: vec![],
                scheduled_sales: vec![],
                tax_profiles: vec![],
            },
            series: vec![],
        };
        let rollout = simulate(&fixture).unwrap().rollouts.remove(0);
        assert_eq!(rollout.failed_month, Some(0));
        assert!(!rollout.months[0].failed);
        assert!(rollout.months[1].failed);
        assert!(rollout.months[2].failed);
        assert!(
            rollout.months[1..]
                .iter()
                .flat_map(|month| &month.balances)
                .all(|balance| balance.balance == Money(0))
        );
        assert!(
            rollout
                .journal
                .iter()
                .all(|entry| entry.cause_id != "must-not-run")
        );
    }

    #[test]
    fn same_source_recurring_obligations_settle_all_or_none() {
        let alice_cash = AccountRef::new("alice", "checking");
        let landlord_cash = AccountRef::new("landlord", "checking");
        let utility_cash = AccountRef::new("utility", "checking");
        let fixture = Fixture {
            schema_version: FIXTURE_SCHEMA_VERSION,
            currency_code: "USD".into(),
            currency_quantum: "0.01".into(),
            rollout_count: 1,
            scenario: ScenarioSpec {
                horizon_months: 3,
                accounts: vec![
                    AccountSpec {
                        account: alice_cash.clone(),
                        opening_balance: Money(100_000),
                    },
                    AccountSpec {
                        account: landlord_cash.clone(),
                        opening_balance: Money(0),
                    },
                    AccountSpec {
                        account: utility_cash.clone(),
                        opening_balance: Money(0),
                    },
                ],
                scheduled_transfers: vec![],
                recurring_transfers: vec![],
                obligations: vec![],
                recurring_obligations: vec![
                    RecurringObligationSpec {
                        start_month: 0,
                        end_month: Some(2),
                        obligation_id: "rent".into(),
                        obligation_type: "cash_spend".into(),
                        from: alice_cash.clone(),
                        to: landlord_cash,
                        amount_due: Money(60_000),
                    },
                    RecurringObligationSpec {
                        start_month: 1,
                        end_month: Some(2),
                        obligation_id: "utility".into(),
                        obligation_type: "cash_spend".into(),
                        from: alice_cash,
                        to: utility_cash,
                        amount_due: Money(1),
                    },
                ],
                initial_lots: vec![],
                scheduled_sales: vec![],
                tax_profiles: vec![],
            },
            series: vec![],
        };
        let rollout = simulate(&fixture).unwrap().rollouts.remove(0);
        assert_eq!(rollout.failed_month, Some(1));
        assert_eq!(
            rollout
                .journal
                .iter()
                .filter(|entry| entry.cause_id.starts_with("rent_m"))
                .map(|entry| entry.cause_id.as_str())
                .collect::<Vec<_>>(),
            vec!["rent_m0"]
        );
        assert!(
            rollout
                .journal
                .iter()
                .all(|entry| entry.cause_id != "utility_m1")
        );
        assert_eq!(rollout.obligations.len(), 3);
        assert_eq!(rollout.obligations[0].amount_paid, Money(60_000));
        assert_eq!(rollout.obligations[0].shortfall, Money(0));
        assert_eq!(rollout.obligations[1].obligation_id, "rent_m1");
        assert_eq!(rollout.obligations[1].amount_paid, Money(0));
        assert_eq!(rollout.obligations[1].shortfall, Money(60_000));
        assert!(rollout.obligations[1].failure_active);
        assert_eq!(rollout.obligations[2].obligation_id, "utility_m1");
        assert_eq!(rollout.obligations[2].amount_paid, Money(0));
        assert_eq!(rollout.obligations[2].shortfall, Money(1));
        assert!(rollout.obligations[2].failure_active);
    }
}
