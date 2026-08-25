use std::collections::{BTreeMap, BTreeSet};

use rayon::prelude::*;
use thiserror::Error;

use crate::{
    fixture::{
        AccountBalance, CapitalImprovementOutcome, DistributionOutcome, FIXTURE_SCHEMA_VERSION,
        Fixture, InitialLotSpec, LotDisposition, MonthOutput, MortgageOriginationOutcome,
        MortgagePaymentOutcome, MortgageState, ObligationOutcome, PopulationOutput,
        PropertyPurchaseOutcome, PropertyRentedFractionOutcome, PropertySaleOutcome,
        PropertySaleSpec, PropertyState, RolloutOutput, RolloutSummary, SeriesSpec,
        SimulationOutput, TaxAccrual,
    },
    ledger::{AccountRef, JournalEntry, Ledger, LedgerError, Posting},
    money::{ArithmeticError, Money, Quantity, mul_div_i128_round_half_up, mul_div_round_half_up},
    tax::{TaxError, TaxFacts, assess, validate_rules},
};

const EXTERNAL_AGENT: &str = "__external__";
const OPENING_EQUITY: &str = "equity:opening";
const RATE_SCALE_PPB: i64 = 1_000_000_000;
const CONTRACT_SCALE: i128 = 1_000_000_000_000_000_000;

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
    #[error("{kind} {cause_id:?} ends at {end_month} before starting at {start_month}")]
    InvalidRecurringRange {
        kind: &'static str,
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
    #[error("distribution references no lots for {agent_id}:{account_id}:{asset_id}")]
    MissingDistributionPool {
        agent_id: String,
        account_id: String,
        asset_id: String,
    },
    #[error("duplicate distribution for {agent_id}:{account_id}:{asset_id}")]
    DuplicateDistribution {
        agent_id: String,
        account_id: String,
        asset_id: String,
    },
    #[error("duplicate location id {location_id:?}")]
    DuplicateLocation { location_id: String },
    #[error("property purchase {cause_id:?} references unknown location {location_id:?}")]
    UnknownLocation {
        cause_id: String,
        location_id: String,
    },
    #[error("duplicate property id {property_id:?}")]
    DuplicateProperty { property_id: String },
    #[error("duplicate mortgage liability id {liability_id:?}")]
    DuplicateMortgage { liability_id: String },
    #[error("property purchase {cause_id:?} has invalid monetary terms")]
    InvalidPropertyTerms { cause_id: String },
    #[error("mortgage {liability_id:?} has invalid principal, rate, or term")]
    InvalidMortgageTerms { liability_id: String },
    #[error("property tax policy references unknown property {property_id:?}")]
    UnknownPropertyTaxProperty { property_id: String },
    #[error("property cashflow {cause_id:?} references unknown property {property_id:?}")]
    UnknownPropertyCashflow {
        cause_id: String,
        property_id: String,
    },
    #[error("property sale references unknown property {property_id:?}")]
    UnknownPropertySale { property_id: String },
    #[error("property {property_id:?} has multiple sale events")]
    DuplicatePropertySale { property_id: String },
    #[error("property sale for {property_id:?} has invalid month or closing costs")]
    InvalidPropertySale { property_id: String },
    #[error("property lifecycle event references unknown property {property_id:?}")]
    UnknownPropertyLifecycle { property_id: String },
    #[error("property lifecycle event for {property_id:?} has invalid month or value")]
    InvalidPropertyLifecycle { property_id: String },
    #[error("property lifecycle event for {property_id:?} occurs at or after its sale")]
    PropertyLifecycleAfterSale { property_id: String },
    #[error("mortgage-interest policy references unknown liability {liability_id:?}")]
    UnknownMortgageInterestPolicy { liability_id: String },
    #[error("mortgage-interest policy owner does not match liability {liability_id:?}")]
    InvalidMortgageInterestPolicy { liability_id: String },
    #[error("property tax policy for {property_id:?} has invalid rate or range")]
    InvalidPropertyTaxPolicy { property_id: String },
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

#[derive(Clone, Debug)]
enum ObligationEffect {
    None,
    Mortgage {
        mortgage_index: usize,
        interest: Money,
        principal: Money,
    },
}

#[derive(Clone, Debug)]
struct ActiveObligation {
    authored_id: String,
    obligation_type: String,
    from: AccountRef,
    to: AccountRef,
    amount_due: Money,
    effect: ObligationEffect,
}

#[derive(Debug)]
struct Recorder {
    capture_trace: bool,
    months: Vec<MonthOutput>,
    journal: Vec<JournalEntry>,
    dispositions: Vec<LotDisposition>,
    obligations: Vec<ObligationOutcome>,
    tax_accruals: Vec<TaxAccrual>,
    distributions: Vec<DistributionOutcome>,
    property_purchases: Vec<PropertyPurchaseOutcome>,
    property_rented_fraction_events: Vec<PropertyRentedFractionOutcome>,
    capital_improvements: Vec<CapitalImprovementOutcome>,
    property_sales: Vec<PropertySaleOutcome>,
    mortgage_originations: Vec<MortgageOriginationOutcome>,
    mortgage_payments: Vec<MortgagePaymentOutcome>,
    journal_entry_count: u64,
    disposition_count: u64,
    tax_accrual_count: u64,
    distribution_count: u64,
    property_purchase_count: u64,
    property_rented_fraction_event_count: u64,
    capital_improvement_count: u64,
    property_sale_count: u64,
    mortgage_payment_count: u64,
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
            distributions: Vec::new(),
            property_purchases: Vec::new(),
            property_rented_fraction_events: Vec::new(),
            capital_improvements: Vec::new(),
            property_sales: Vec::new(),
            mortgage_originations: Vec::new(),
            mortgage_payments: Vec::new(),
            journal_entry_count: 0,
            disposition_count: 0,
            tax_accrual_count: 0,
            distribution_count: 0,
            property_purchase_count: 0,
            property_rented_fraction_event_count: 0,
            capital_improvement_count: 0,
            property_sale_count: 0,
            mortgage_payment_count: 0,
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

    fn record_distribution(
        &mut self,
        distribution: DistributionOutcome,
    ) -> Result<(), SimulationError> {
        self.distribution_count =
            self.distribution_count
                .checked_add(1)
                .ok_or(ArithmeticError::Overflow {
                    operation: "distribution count",
                })?;
        if self.capture_trace {
            self.distributions.push(distribution);
        }
        Ok(())
    }

    fn record_property_purchase(
        &mut self,
        purchase: PropertyPurchaseOutcome,
        origination: Option<MortgageOriginationOutcome>,
    ) -> Result<(), SimulationError> {
        self.property_purchase_count =
            self.property_purchase_count
                .checked_add(1)
                .ok_or(ArithmeticError::Overflow {
                    operation: "property purchase count",
                })?;
        if self.capture_trace {
            self.property_purchases.push(purchase);
            if let Some(origination) = origination {
                self.mortgage_originations.push(origination);
            }
        }
        Ok(())
    }

    fn record_property_sale(&mut self, sale: PropertySaleOutcome) -> Result<(), SimulationError> {
        self.property_sale_count =
            self.property_sale_count
                .checked_add(1)
                .ok_or(ArithmeticError::Overflow {
                    operation: "property sale count",
                })?;
        if self.capture_trace {
            self.property_sales.push(sale);
        }
        Ok(())
    }

    fn record_property_rented_fraction(
        &mut self,
        event: PropertyRentedFractionOutcome,
    ) -> Result<(), SimulationError> {
        self.property_rented_fraction_event_count = self
            .property_rented_fraction_event_count
            .checked_add(1)
            .ok_or(ArithmeticError::Overflow {
                operation: "property rented-fraction event count",
            })?;
        if self.capture_trace {
            self.property_rented_fraction_events.push(event);
        }
        Ok(())
    }

    fn record_capital_improvement(
        &mut self,
        event: CapitalImprovementOutcome,
    ) -> Result<(), SimulationError> {
        self.capital_improvement_count =
            self.capital_improvement_count
                .checked_add(1)
                .ok_or(ArithmeticError::Overflow {
                    operation: "capital improvement count",
                })?;
        if self.capture_trace {
            self.capital_improvements.push(event);
        }
        Ok(())
    }

    fn record_mortgage_payment(
        &mut self,
        payment: MortgagePaymentOutcome,
    ) -> Result<(), SimulationError> {
        self.mortgage_payment_count =
            self.mortgage_payment_count
                .checked_add(1)
                .ok_or(ArithmeticError::Overflow {
                    operation: "mortgage payment count",
                })?;
        if self.capture_trace {
            self.mortgage_payments.push(payment);
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
    ending_properties: Vec<PropertyState>,
    ending_mortgages: Vec<MortgageState>,
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
            distributions: self.recorder.distributions,
            property_purchases: self.recorder.property_purchases,
            property_rented_fraction_events: self.recorder.property_rented_fraction_events,
            capital_improvements: self.recorder.capital_improvements,
            property_sales: self.recorder.property_sales,
            mortgage_originations: self.recorder.mortgage_originations,
            mortgage_payments: self.recorder.mortgage_payments,
            failed_month: self.failed_month,
        }
    }

    fn into_summary(self) -> RolloutSummary {
        RolloutSummary {
            rollout_id: self.rollout_id,
            ending_balances: self.ending_balances,
            ending_properties: self.ending_properties,
            ending_mortgages: self.ending_mortgages,
            journal_entry_count: self.recorder.journal_entry_count,
            disposition_count: self.recorder.disposition_count,
            tax_accrual_count: self.recorder.tax_accrual_count,
            distribution_count: self.recorder.distribution_count,
            property_purchase_count: self.recorder.property_purchase_count,
            property_rented_fraction_event_count: self
                .recorder
                .property_rented_fraction_event_count,
            capital_improvement_count: self.recorder.capital_improvement_count,
            property_sale_count: self.recorder.property_sale_count,
            mortgage_payment_count: self.recorder.mortgage_payment_count,
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
        if (series.series_id.starts_with("security:")
            || series.series_id.starts_with("security_distribution:")
            || series.series_id.starts_with("home_value:"))
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
        validate_income_category(transfer.deduction_category.as_deref())?;
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
                kind: "recurring transfer",
                cause_id: transfer.cause_id.clone(),
                start_month: transfer.start_month,
                end_month,
            });
        }
        validate_positive_amount("recurring transfer", &transfer.cause_id, transfer.amount)?;
        validate_income_category(transfer.income_category.as_deref())?;
        validate_income_category(transfer.deduction_category.as_deref())?;
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
                kind: "recurring obligation",
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
    let mut distributions = BTreeSet::new();
    for distribution in &fixture.scenario.distributions {
        validate_identifier("distribution asset", &distribution.asset_id)?;
        let pool = (
            distribution.agent_id.clone(),
            distribution.holding_account_id.clone(),
            distribution.asset_id.clone(),
        );
        if !distributions.insert(pool.clone()) {
            return Err(SimulationError::DuplicateDistribution {
                agent_id: pool.0,
                account_id: pool.1,
                asset_id: pool.2,
            });
        }
        if !pool_scales.contains_key(&pool) {
            return Err(SimulationError::MissingDistributionPool {
                agent_id: pool.0,
                account_id: pool.1,
                asset_id: pool.2,
            });
        }
        validate_account(
            &accounts,
            &AccountRef::new(&distribution.agent_id, &distribution.to_account_id),
            "distribution destination",
        )?;
        let series_id = format!("security_distribution:{}", distribution.asset_id);
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
    let mut locations = BTreeSet::new();
    for location in &fixture.scenario.locations {
        validate_identifier("location", &location.location_id)?;
        if !locations.insert(location.location_id.clone()) {
            return Err(SimulationError::DuplicateLocation {
                location_id: location.location_id.clone(),
            });
        }
        if location.annual_property_tax_rate_ppb < 0 || location.annual_special_assessment.0 < 0 {
            return Err(SimulationError::InvalidPropertyTaxPolicy {
                property_id: location.location_id.clone(),
            });
        }
    }
    let mut properties = BTreeMap::new();
    let mut mortgages = BTreeSet::new();
    let mut mortgage_owners = BTreeMap::new();
    for purchase in &fixture.scenario.scheduled_property_purchases {
        validate_identifier("property purchase", &purchase.cause_id)?;
        validate_identifier("property", &purchase.property_id)?;
        validate_event_month(
            "property purchase",
            &purchase.cause_id,
            purchase.month,
            fixture.scenario.horizon_months,
        )?;
        if !locations.contains(&purchase.location_id) {
            return Err(SimulationError::UnknownLocation {
                cause_id: purchase.cause_id.clone(),
                location_id: purchase.location_id.clone(),
            });
        }
        if properties
            .insert(purchase.property_id.clone(), purchase)
            .is_some()
        {
            return Err(SimulationError::DuplicateProperty {
                property_id: purchase.property_id.clone(),
            });
        }
        validate_account(
            &accounts,
            &AccountRef::new(&purchase.buyer_agent_id, &purchase.buyer_account_id),
            &purchase.cause_id,
        )?;
        validate_account(
            &accounts,
            &AccountRef::new(&purchase.seller_agent_id, &purchase.seller_account_id),
            &purchase.cause_id,
        )?;
        let principal = purchase
            .mortgage
            .as_ref()
            .map_or(Money(0), |mortgage| mortgage.principal);
        if purchase.purchase_price.0 <= 0
            || purchase.down_payment.0 < 0
            || purchase.buyer_closing_cost.0 < 0
            || !(0..=RATE_SCALE_PPB).contains(&purchase.rented_fraction_ppb)
            || !(0..=RATE_SCALE_PPB).contains(&purchase.land_value_fraction_ppb)
            || purchase.down_payment.checked_add(principal)? != purchase.purchase_price
        {
            return Err(SimulationError::InvalidPropertyTerms {
                cause_id: purchase.cause_id.clone(),
            });
        }
        if let Some(mortgage) = &purchase.mortgage {
            validate_identifier("mortgage", &mortgage.liability_id)?;
            if !mortgages.insert(mortgage.liability_id.clone()) {
                return Err(SimulationError::DuplicateMortgage {
                    liability_id: mortgage.liability_id.clone(),
                });
            }
            mortgage_owners.insert(
                mortgage.liability_id.clone(),
                purchase.buyer_agent_id.clone(),
            );
            if mortgage.principal.0 <= 0
                || mortgage.annual_interest_rate_ppb < 0
                || mortgage.annual_interest_rate_ppb > RATE_SCALE_PPB
                || mortgage.term_months == 0
            {
                return Err(SimulationError::InvalidMortgageTerms {
                    liability_id: mortgage.liability_id.clone(),
                });
            }
            validate_account(
                &accounts,
                &AccountRef::new(&mortgage.lender_agent_id, &mortgage.lender_account_id),
                &mortgage.liability_id,
            )?;
            mortgage_monthly_payment(
                mortgage.principal,
                mortgage.annual_interest_rate_ppb,
                mortgage.term_months,
            )?;
        }
    }
    let mut mortgage_interest_policies = BTreeSet::new();
    for policy in &fixture.scenario.mortgage_interest_deduction_policies {
        let Some(owner_agent_id) = mortgage_owners.get(&policy.liability_id) else {
            return Err(SimulationError::UnknownMortgageInterestPolicy {
                liability_id: policy.liability_id.clone(),
            });
        };
        if owner_agent_id != &policy.owner_agent_id {
            return Err(SimulationError::InvalidMortgageInterestPolicy {
                liability_id: policy.liability_id.clone(),
            });
        }
        if !mortgage_interest_policies.insert(policy.liability_id.clone()) {
            return Err(SimulationError::InvalidMortgageInterestPolicy {
                liability_id: policy.liability_id.clone(),
            });
        }
    }
    let mut property_sales = BTreeSet::new();
    for sale in &fixture.scenario.property_sales {
        validate_identifier("property sale", &sale.property_id)?;
        validate_event_month(
            "property sale",
            &sale.property_id,
            sale.month,
            fixture.scenario.horizon_months,
        )?;
        let Some(purchase) = properties.get(&sale.property_id) else {
            return Err(SimulationError::UnknownPropertySale {
                property_id: sale.property_id.clone(),
            });
        };
        if !property_sales.insert(sale.property_id.clone()) {
            return Err(SimulationError::DuplicatePropertySale {
                property_id: sale.property_id.clone(),
            });
        }
        if sale.month <= purchase.month || sale.closing_cost_bps > 10_000 {
            return Err(SimulationError::InvalidPropertySale {
                property_id: sale.property_id.clone(),
            });
        }
        let series_id = format!("home_value:{}", purchase.location_id);
        if !series_ids.contains(&series_id) {
            return Err(SimulationError::MissingSeries { series_id });
        }
    }
    for event in &fixture.scenario.property_rented_fraction_events {
        validate_property_lifecycle_event(
            &properties,
            &fixture.scenario.property_sales,
            &event.property_id,
            event.month,
            fixture.scenario.horizon_months,
        )?;
        if !(0..=RATE_SCALE_PPB).contains(&event.rented_fraction_ppb) {
            return Err(SimulationError::InvalidPropertyLifecycle {
                property_id: event.property_id.clone(),
            });
        }
    }
    for event in &fixture.scenario.capital_improvement_events {
        validate_property_lifecycle_event(
            &properties,
            &fixture.scenario.property_sales,
            &event.property_id,
            event.month,
            fixture.scenario.horizon_months,
        )?;
        if event.amount.0 <= 0 {
            return Err(SimulationError::InvalidPropertyLifecycle {
                property_id: event.property_id.clone(),
            });
        }
    }
    let mut property_tax_months = BTreeSet::new();
    for policy in &fixture.scenario.property_tax_policies {
        let Some(purchase) = properties.get(&policy.property_id) else {
            return Err(SimulationError::UnknownPropertyTaxProperty {
                property_id: policy.property_id.clone(),
            });
        };
        if purchase.buyer_agent_id != policy.owner_agent_id
            || policy.annual_tax_rate_ppb.is_some_and(|rate| rate < 0)
            || policy.start_month >= fixture.scenario.horizon_months
            || policy.end_month.is_some_and(|end| {
                end < policy.start_month || end >= fixture.scenario.horizon_months
            })
        {
            return Err(SimulationError::InvalidPropertyTaxPolicy {
                property_id: policy.property_id.clone(),
            });
        }
        validate_account(
            &accounts,
            &AccountRef::new(&policy.owner_agent_id, &policy.from_account_id),
            "property tax payer",
        )?;
        validate_account(
            &accounts,
            &AccountRef::new(
                &policy.tax_authority_agent_id,
                &policy.tax_authority_account_id,
            ),
            "property tax authority",
        )?;
        let end = policy
            .end_month
            .unwrap_or(fixture.scenario.horizon_months - 1);
        for month in policy.start_month..=end {
            if !property_tax_months.insert((policy.property_id.clone(), month)) {
                return Err(SimulationError::InvalidPropertyTaxPolicy {
                    property_id: policy.property_id.clone(),
                });
            }
        }
    }
    for cashflow in &fixture.scenario.scheduled_property_cashflows {
        validate_identifier("scheduled property cashflow", &cashflow.cause_id)?;
        validate_event_month(
            "scheduled property cashflow",
            &cashflow.cause_id,
            cashflow.month,
            fixture.scenario.horizon_months,
        )?;
        validate_positive_amount(
            "scheduled property cashflow",
            &cashflow.cause_id,
            cashflow.amount,
        )?;
        validate_income_category(cashflow.income_category.as_deref())?;
        validate_income_category(cashflow.deduction_category.as_deref())?;
        validate_account(&accounts, &cashflow.from, &cashflow.cause_id)?;
        validate_account(&accounts, &cashflow.to, &cashflow.cause_id)?;
        if !properties.contains_key(&cashflow.property_id) {
            return Err(SimulationError::UnknownPropertyCashflow {
                cause_id: cashflow.cause_id.clone(),
                property_id: cashflow.property_id.clone(),
            });
        }
    }
    for cashflow in &fixture.scenario.recurring_property_cashflows {
        validate_identifier("recurring property cashflow", &cashflow.cause_id)?;
        validate_event_month(
            "recurring property cashflow",
            &cashflow.cause_id,
            cashflow.start_month,
            fixture.scenario.horizon_months,
        )?;
        if let Some(end_month) = cashflow.end_month
            && end_month < cashflow.start_month
        {
            return Err(SimulationError::InvalidRecurringRange {
                kind: "recurring property cashflow",
                cause_id: cashflow.cause_id.clone(),
                start_month: cashflow.start_month,
                end_month,
            });
        }
        validate_positive_amount(
            "recurring property cashflow",
            &cashflow.cause_id,
            cashflow.amount,
        )?;
        validate_income_category(cashflow.income_category.as_deref())?;
        validate_income_category(cashflow.deduction_category.as_deref())?;
        validate_account(&accounts, &cashflow.from, &cashflow.cause_id)?;
        validate_account(&accounts, &cashflow.to, &cashflow.cause_id)?;
        if !properties.contains_key(&cashflow.property_id) {
            return Err(SimulationError::UnknownPropertyCashflow {
                cause_id: cashflow.cause_id.clone(),
                property_id: cashflow.property_id.clone(),
            });
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

fn validate_property_lifecycle_event(
    properties: &BTreeMap<String, &crate::fixture::ScheduledPropertyPurchaseSpec>,
    sales: &[PropertySaleSpec],
    property_id: &str,
    month: u32,
    horizon: u32,
) -> Result<(), SimulationError> {
    validate_identifier("property lifecycle", property_id)?;
    validate_event_month("property lifecycle", property_id, month, horizon)?;
    let Some(purchase) = properties.get(property_id) else {
        return Err(SimulationError::UnknownPropertyLifecycle {
            property_id: property_id.into(),
        });
    };
    if month <= purchase.month {
        return Err(SimulationError::InvalidPropertyLifecycle {
            property_id: property_id.into(),
        });
    }
    if sales
        .iter()
        .any(|sale| sale.property_id == property_id && month >= sale.month)
    {
        return Err(SimulationError::PropertyLifecycleAfterSale {
            property_id: property_id.into(),
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
    for purchase in &fixture.scenario.scheduled_property_purchases {
        accounts.push(property_asset_account(
            &purchase.buyer_agent_id,
            &purchase.property_id,
        ));
        accounts.push(realized_gain_account(&purchase.buyer_agent_id));
        accounts.push(property_basis_writeoff_account(
            &purchase.buyer_agent_id,
            &purchase.property_id,
        ));
        accounts.push(property_sale_clearing_account(
            &purchase.seller_agent_id,
            &purchase.property_id,
        ));
        if let Some(mortgage) = &purchase.mortgage {
            accounts.push(mortgage_liability_account(
                &purchase.buyer_agent_id,
                &mortgage.liability_id,
            ));
            accounts.push(mortgage_interest_expense_account(
                &purchase.buyer_agent_id,
                &mortgage.liability_id,
            ));
            accounts.push(mortgage_receivable_account(
                &mortgage.lender_agent_id,
                &mortgage.liability_id,
            ));
            accounts.push(mortgage_interest_income_account(
                &mortgage.lender_agent_id,
                &mortgage.liability_id,
            ));
            accounts.push(mortgage_funding_account(
                &mortgage.lender_agent_id,
                &mortgage.liability_id,
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

    let mut properties = Vec::<PropertyState>::new();
    let mut mortgages = Vec::<MortgageState>::new();

    let mut failed_month = None;
    if recorder.capture_trace {
        recorder.record_month(month_output(0, &ledger, &properties, &mortgages, false));
    }
    for month in 0..fixture.scenario.horizon_months {
        if failed_month.is_some() {
            if recorder.capture_trace {
                recorder.record_month(month_output(
                    month + 1,
                    &ledger,
                    &properties,
                    &mortgages,
                    true,
                ));
            }
            continue;
        }
        execute_property_lifecycle_events(
            fixture,
            rollout_id,
            &mut ledger,
            &mut recorder,
            &mut tax_facts,
            &mut properties,
            &mut mortgages,
            month,
        )?;
        execute_distributions(
            fixture,
            rollout_id,
            &mut ledger,
            &mut recorder,
            &lots,
            month,
        )?;
        execute_property_purchases(
            fixture,
            &mut ledger,
            &mut recorder,
            &mut properties,
            &mut mortgages,
            month,
        )?;
        execute_cashflows(
            fixture,
            &mut ledger,
            &mut recorder,
            &mut tax_facts,
            &properties,
            month,
        )?;
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
                authored_id: obligation.obligation_id.clone(),
                obligation_type: obligation.obligation_type.clone(),
                from: obligation.from.clone(),
                to: obligation.to.clone(),
                amount_due: obligation.amount_due,
                effect: ObligationEffect::None,
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
                        authored_id: obligation.obligation_id.clone(),
                        obligation_type: obligation.obligation_type.clone(),
                        from: obligation.from.clone(),
                        to: obligation.to.clone(),
                        amount_due: obligation.amount_due,
                        effect: ObligationEffect::None,
                    }),
            )
            .chain(property_obligations(
                fixture,
                &properties,
                &mortgages,
                month,
            )?)
            .collect();
        if settle_obligations(
            fixture,
            &mut ledger,
            &mut recorder,
            &mut tax_facts,
            &properties,
            &mut mortgages,
            month,
            &active_obligations,
        )? {
            failed_month = Some(month);
        }
        if failed_month.is_none() {
            accrue_property_depreciation(&mut tax_facts, &mut properties)?;
        }
        if failed_month.is_none() && (month + 1) % 12 == 0 {
            accrue_year_end_taxes(fixture, &mut ledger, &mut recorder, &mut tax_facts, month)?;
            reset_property_tax_year_state(&mut properties, &mut mortgages);
        }
        if recorder.capture_trace {
            recorder.record_month(month_output(
                month + 1,
                &ledger,
                &properties,
                &mortgages,
                failed_month.is_some(),
            ));
        }
    }
    debug_assert_eq!(ledger.trial_balance(), 0);
    Ok(RolloutComputation {
        rollout_id,
        ending_balances: account_balances(&ledger, failed_month.is_some()),
        ending_properties: property_states(&properties, failed_month.is_some()),
        ending_mortgages: mortgage_states(&mortgages, failed_month.is_some()),
        recorder,
        failed_month,
    })
}

fn execute_distributions(
    fixture: &Fixture,
    rollout_id: u32,
    ledger: &mut Ledger,
    recorder: &mut Recorder,
    lots: &[LotState],
    month: u32,
) -> Result<(), SimulationError> {
    for distribution in &fixture.scenario.distributions {
        let pool_lots: Vec<_> = lots
            .iter()
            .filter(|lot| {
                lot.spec.agent_id == distribution.agent_id
                    && lot.spec.account_id == distribution.holding_account_id
                    && lot.spec.asset_id == distribution.asset_id
            })
            .collect();
        let scale = pool_lots[0].spec.quantity_scale;
        let units = pool_lots.iter().try_fold(0_i64, |total, lot| {
            total
                .checked_add(lot.units_remaining.0)
                .ok_or(ArithmeticError::Overflow {
                    operation: "distribution pool quantity",
                })
        })?;
        let per_unit = series_value(
            fixture,
            &format!("security_distribution:{}", distribution.asset_id),
            rollout_id,
            month,
        )?;
        let amount = Money(mul_div_round_half_up(
            per_unit,
            units,
            scale,
            "security distribution",
        )?);
        let cause_id = format!(
            "distribution:{}:{}:m{month}",
            distribution.agent_id, distribution.asset_id
        );
        transfer_money(
            ledger,
            recorder,
            month,
            &cause_id,
            &AccountRef::new(EXTERNAL_AGENT, "boundary"),
            &AccountRef::new(&distribution.agent_id, &distribution.to_account_id),
            amount,
        )?;
        recorder.record_distribution(DistributionOutcome {
            month,
            agent_id: distribution.agent_id.clone(),
            holding_account_id: distribution.holding_account_id.clone(),
            asset_id: distribution.asset_id.clone(),
            units: Quantity(units),
            amount,
        })?;
    }
    Ok(())
}

#[allow(clippy::too_many_arguments)]
fn execute_property_lifecycle_events(
    fixture: &Fixture,
    rollout_id: u32,
    ledger: &mut Ledger,
    recorder: &mut Recorder,
    tax_facts: &mut BTreeMap<(String, String), TaxFacts>,
    properties: &mut [PropertyState],
    mortgages: &mut [MortgageState],
    month: u32,
) -> Result<(), SimulationError> {
    let property_ids: BTreeSet<_> = fixture
        .scenario
        .property_rented_fraction_events
        .iter()
        .filter(|event| event.month == month)
        .map(|event| event.property_id.as_str())
        .chain(
            fixture
                .scenario
                .capital_improvement_events
                .iter()
                .filter(|event| event.month == month)
                .map(|event| event.property_id.as_str()),
        )
        .chain(
            fixture
                .scenario
                .property_sales
                .iter()
                .filter(|event| event.month == month)
                .map(|event| event.property_id.as_str()),
        )
        .collect();
    for property_id in property_ids {
        for event in fixture
            .scenario
            .property_rented_fraction_events
            .iter()
            .filter(|event| event.month == month && event.property_id == property_id)
        {
            let Some(property) = properties
                .iter_mut()
                .find(|property| property.property_id == event.property_id && property.active)
            else {
                continue;
            };
            property.rented_fraction_ppb = event.rented_fraction_ppb;
            recorder.record_property_rented_fraction(PropertyRentedFractionOutcome {
                month,
                property_id: event.property_id.clone(),
                rented_fraction_ppb: event.rented_fraction_ppb,
            })?;
        }
        for event in fixture
            .scenario
            .capital_improvement_events
            .iter()
            .filter(|event| event.month == month && event.property_id == property_id)
        {
            let Some(property) = properties
                .iter_mut()
                .find(|property| property.property_id == event.property_id && property.active)
            else {
                continue;
            };
            let purchase = fixture
                .scenario
                .scheduled_property_purchases
                .iter()
                .find(|purchase| purchase.property_id == event.property_id)
                .expect("validated improvement has a purchase");
            recorder.apply_entry(
                ledger,
                JournalEntry {
                    month,
                    cause_id: format!("capital-improvement:{}:{month}", event.property_id),
                    postings: vec![
                        Posting {
                            account: AccountRef::new(
                                &purchase.buyer_agent_id,
                                &purchase.buyer_account_id,
                            ),
                            amount: event.amount.checked_neg()?,
                        },
                        Posting {
                            account: property_asset_account(
                                &purchase.buyer_agent_id,
                                &purchase.property_id,
                            ),
                            amount: event.amount,
                        },
                    ],
                },
            )?;
            property.building_basis = property.building_basis.checked_add(event.amount)?;
            recorder.record_capital_improvement(CapitalImprovementOutcome {
                month,
                property_id: event.property_id.clone(),
                amount: event.amount,
                // The existing lifecycle codec currently emits an empty
                // description for compiled improvement rows.
                description: String::new(),
            })?;
        }
        execute_property_sales(
            fixture,
            rollout_id,
            ledger,
            recorder,
            tax_facts,
            properties,
            mortgages,
            month,
            property_id,
        )?;
    }
    Ok(())
}

#[allow(clippy::too_many_arguments)]
fn execute_property_sales(
    fixture: &Fixture,
    rollout_id: u32,
    ledger: &mut Ledger,
    recorder: &mut Recorder,
    tax_facts: &mut BTreeMap<(String, String), TaxFacts>,
    properties: &mut [PropertyState],
    mortgages: &mut [MortgageState],
    month: u32,
    property_id: &str,
) -> Result<(), SimulationError> {
    let mut sales: Vec<&PropertySaleSpec> = fixture
        .scenario
        .property_sales
        .iter()
        .filter(|sale| sale.month == month && sale.property_id == property_id)
        .collect();
    sales.sort_by_key(|sale| &sale.property_id);
    for sale in sales {
        let Some(property_index) = properties
            .iter()
            .position(|property| property.property_id == sale.property_id && property.active)
        else {
            continue;
        };
        let property = &properties[property_index];
        let purchase = fixture
            .scenario
            .scheduled_property_purchases
            .iter()
            .find(|purchase| purchase.property_id == sale.property_id)
            .expect("validated property sale has a purchase");
        let series_id = format!("home_value:{}", purchase.location_id);
        let base_value = series_value(fixture, &series_id, rollout_id, 0)?;
        let sale_value = series_value(fixture, &series_id, rollout_id, month)?;
        let market_value = Money(mul_div_round_half_up(
            purchase.purchase_price.0,
            sale_value,
            base_value,
            "property market value",
        )?);
        let gross_proceeds = Money(mul_div_round_half_up(
            market_value.0,
            i64::from(10_000 - sale.closing_cost_bps),
            10_000,
            "property sale proceeds",
        )?);
        let mortgage_indices: Vec<_> = mortgages
            .iter()
            .enumerate()
            .filter(|(_, mortgage)| mortgage.property_id == sale.property_id && mortgage.active)
            .map(|(index, _)| index)
            .collect();
        let mortgage_payoff = mortgage_indices.iter().try_fold(Money(0), |total, index| {
            total.checked_add(mortgages[*index].principal)
        })?;
        let net_cash = gross_proceeds.checked_sub(mortgage_payoff)?;
        // Match the legacy contract exactly: capitalized buyer closing costs
        // enter the depreciable building basis, but the sale-gain formula uses
        // purchase price + later capex - cumulative depreciation.
        let capital_improvements = property
            .building_basis
            .checked_sub(property.building_basis_initial)?;
        let tax_adjusted_basis = purchase
            .purchase_price
            .checked_add(capital_improvements)?
            .checked_sub(property.cumulative_depreciation)?;
        let realized_gain = gross_proceeds.checked_sub(tax_adjusted_basis)?;
        let depreciation_recapture = Money(
            realized_gain
                .0
                .max(0)
                .min(property.cumulative_depreciation.0),
        );
        let long_term_capital_gain =
            Money(realized_gain.checked_sub(depreciation_recapture)?.0.max(0));
        let property_asset_balance = property.adjusted_basis.checked_add(capital_improvements)?;
        let basis_writeoff = property
            .adjusted_basis
            .checked_sub(purchase.purchase_price)?
            .checked_add(property.cumulative_depreciation)?;
        let mut postings = vec![
            Posting {
                account: AccountRef::new(&purchase.buyer_agent_id, &purchase.buyer_account_id),
                amount: net_cash,
            },
            Posting {
                account: property_asset_account(&purchase.buyer_agent_id, &purchase.property_id),
                amount: property_asset_balance.checked_neg()?,
            },
            Posting {
                account: property_basis_writeoff_account(
                    &purchase.buyer_agent_id,
                    &purchase.property_id,
                ),
                amount: basis_writeoff,
            },
            Posting {
                account: realized_gain_account(&purchase.buyer_agent_id),
                amount: realized_gain.checked_neg()?,
            },
        ];
        for index in &mortgage_indices {
            let mortgage = &mortgages[*index];
            postings.extend([
                Posting {
                    account: mortgage_liability_account(&mortgage.agent_id, &mortgage.liability_id),
                    amount: mortgage.principal,
                },
                Posting {
                    account: mortgage_receivable_account(
                        &mortgage.counterparty_agent_id,
                        &mortgage.liability_id,
                    ),
                    amount: mortgage.principal.checked_neg()?,
                },
                Posting {
                    account: mortgage_funding_account(
                        &mortgage.counterparty_agent_id,
                        &mortgage.liability_id,
                    ),
                    amount: mortgage.principal,
                },
            ]);
        }
        recorder.apply_entry(
            ledger,
            JournalEntry {
                month,
                cause_id: format!("property-sale:{}", sale.property_id),
                postings,
            },
        )?;
        properties[property_index].active = false;
        properties[property_index].rented_fraction_ppb = 0;
        properties[property_index].building_basis = Money(0);
        for index in mortgage_indices {
            mortgages[index].principal = Money(0);
            mortgages[index].active = false;
        }
        record_capital_gain(
            tax_facts,
            &purchase.buyer_agent_id,
            long_term_capital_gain,
            true,
        )?;
        record_section_1250_recapture(tax_facts, &purchase.buyer_agent_id, depreciation_recapture)?;
        recorder.record_property_sale(PropertySaleOutcome {
            month,
            property_id: sale.property_id.clone(),
            gross_proceeds,
            mortgage_payoff,
            net_cash_to_owner: net_cash,
            realized_gain,
            depreciation_recapture,
            section_121_exclusion: Money(0),
            long_term_capital_gain,
        })?;
    }
    Ok(())
}

fn execute_property_purchases(
    fixture: &Fixture,
    ledger: &mut Ledger,
    recorder: &mut Recorder,
    properties: &mut Vec<PropertyState>,
    mortgages: &mut Vec<MortgageState>,
    month: u32,
) -> Result<(), SimulationError> {
    for purchase in fixture
        .scenario
        .scheduled_property_purchases
        .iter()
        .filter(|purchase| purchase.month == month)
    {
        let principal = purchase
            .mortgage
            .as_ref()
            .map_or(Money(0), |mortgage| mortgage.principal);
        let adjusted_basis = purchase
            .purchase_price
            .checked_add(purchase.buyer_closing_cost)?;
        let building_basis_initial = Money(mul_div_round_half_up(
            purchase.purchase_price.0,
            RATE_SCALE_PPB - purchase.land_value_fraction_ppb,
            RATE_SCALE_PPB,
            "property building basis",
        )?)
        .checked_add(purchase.buyer_closing_cost)?;
        let stake = purchase
            .down_payment
            .checked_add(purchase.buyer_closing_cost)?;
        let equity = purchase.purchase_price.checked_sub(principal)?;
        let buyer_cash = AccountRef::new(&purchase.buyer_agent_id, &purchase.buyer_account_id);
        let seller_cash = AccountRef::new(&purchase.seller_agent_id, &purchase.seller_account_id);
        let mut postings = vec![
            Posting {
                account: buyer_cash,
                amount: stake.checked_neg()?,
            },
            Posting {
                account: seller_cash,
                amount: stake,
            },
            Posting {
                account: property_asset_account(&purchase.buyer_agent_id, &purchase.property_id),
                amount: adjusted_basis,
            },
            Posting {
                account: property_sale_clearing_account(
                    &purchase.seller_agent_id,
                    &purchase.property_id,
                ),
                amount: stake.checked_neg()?,
            },
        ];
        let mut origination = None;
        if let Some(mortgage) = &purchase.mortgage {
            let monthly_payment = mortgage_monthly_payment(
                mortgage.principal,
                mortgage.annual_interest_rate_ppb,
                mortgage.term_months,
            )?;
            postings.extend([
                Posting {
                    account: mortgage_liability_account(
                        &purchase.buyer_agent_id,
                        &mortgage.liability_id,
                    ),
                    amount: mortgage.principal.checked_neg()?,
                },
                Posting {
                    account: mortgage_receivable_account(
                        &mortgage.lender_agent_id,
                        &mortgage.liability_id,
                    ),
                    amount: mortgage.principal,
                },
                Posting {
                    account: mortgage_funding_account(
                        &mortgage.lender_agent_id,
                        &mortgage.liability_id,
                    ),
                    amount: mortgage.principal.checked_neg()?,
                },
            ]);
            mortgages.push(MortgageState {
                liability_id: mortgage.liability_id.clone(),
                property_id: purchase.property_id.clone(),
                agent_id: purchase.buyer_agent_id.clone(),
                payment_account_id: purchase.buyer_account_id.clone(),
                counterparty_agent_id: mortgage.lender_agent_id.clone(),
                counterparty_account_id: mortgage.lender_account_id.clone(),
                origination_month: month,
                annual_interest_rate_ppb: mortgage.annual_interest_rate_ppb,
                term_months: mortgage.term_months,
                monthly_payment,
                principal: mortgage.principal,
                interest_paid_ytd: Money(0),
                rental_interest_paid_ytd: Money(0),
                principal_paid_ytd: Money(0),
                active: true,
            });
            origination = Some(MortgageOriginationOutcome {
                month,
                cause_id: purchase.cause_id.clone(),
                liability_id: mortgage.liability_id.clone(),
                agent_id: purchase.buyer_agent_id.clone(),
                payment_account_id: purchase.buyer_account_id.clone(),
                counterparty_agent_id: mortgage.lender_agent_id.clone(),
                counterparty_account_id: mortgage.lender_account_id.clone(),
                property_id: purchase.property_id.clone(),
                principal: mortgage.principal,
                annual_interest_rate_ppb: mortgage.annual_interest_rate_ppb,
                term_months: mortgage.term_months,
                monthly_payment,
            });
        } else {
            postings.push(Posting {
                account: property_sale_clearing_account(
                    &purchase.seller_agent_id,
                    &purchase.property_id,
                ),
                amount: principal,
            });
        }
        recorder.apply_entry(
            ledger,
            JournalEntry {
                month,
                cause_id: purchase.cause_id.clone(),
                postings,
            },
        )?;
        properties.push(PropertyState {
            property_id: purchase.property_id.clone(),
            location_id: purchase.location_id.clone(),
            owner_agent_id: purchase.buyer_agent_id.clone(),
            purchase_month: month,
            adjusted_basis,
            rented_fraction_ppb: purchase.rented_fraction_ppb,
            building_basis_initial,
            building_basis: building_basis_initial,
            cumulative_depreciation: Money(0),
            depreciation_ytd: Money(0),
            contribution_used: stake,
            equity_ledger: equity,
            active: true,
        });
        recorder.record_property_purchase(
            PropertyPurchaseOutcome {
                month,
                cause_id: purchase.cause_id.clone(),
                property_id: purchase.property_id.clone(),
                location_id: purchase.location_id.clone(),
                buyer_agent_id: purchase.buyer_agent_id.clone(),
                purchase_price: purchase.purchase_price,
                closing_cost: purchase.buyer_closing_cost,
                adjusted_basis,
                stake_contribution: stake,
                equity_ledger: equity,
            },
            origination,
        )?;
    }
    Ok(())
}

fn execute_cashflows(
    fixture: &Fixture,
    ledger: &mut Ledger,
    recorder: &mut Recorder,
    tax_facts: &mut BTreeMap<(String, String), TaxFacts>,
    properties: &[PropertyState],
    month: u32,
) -> Result<(), SimulationError> {
    for cashflow in fixture
        .scenario
        .scheduled_transfers
        .iter()
        .filter(|cashflow| cashflow.month == month)
    {
        apply_cashflow(
            ledger,
            recorder,
            tax_facts,
            month,
            &cashflow.cause_id,
            &cashflow.from,
            &cashflow.to,
            cashflow.amount,
            cashflow.income_category.as_deref(),
            cashflow.deduction_category.as_deref(),
        )?;
    }
    for cashflow in fixture
        .scenario
        .recurring_transfers
        .iter()
        .filter(|cashflow| {
            cashflow.start_month <= month && cashflow.end_month.is_none_or(|end| month <= end)
        })
    {
        apply_cashflow(
            ledger,
            recorder,
            tax_facts,
            month,
            &cashflow.cause_id,
            &cashflow.from,
            &cashflow.to,
            cashflow.amount,
            cashflow.income_category.as_deref(),
            cashflow.deduction_category.as_deref(),
        )?;
    }
    for cashflow in fixture
        .scenario
        .scheduled_property_cashflows
        .iter()
        .filter(|cashflow| cashflow.month == month)
    {
        if properties
            .iter()
            .any(|property| property.property_id == cashflow.property_id && property.active)
        {
            apply_cashflow(
                ledger,
                recorder,
                tax_facts,
                month,
                &cashflow.cause_id,
                &cashflow.from,
                &cashflow.to,
                cashflow.amount,
                cashflow.income_category.as_deref(),
                cashflow.deduction_category.as_deref(),
            )?;
        }
    }
    for cashflow in fixture
        .scenario
        .recurring_property_cashflows
        .iter()
        .filter(|cashflow| {
            cashflow.start_month <= month && cashflow.end_month.is_none_or(|end| month <= end)
        })
    {
        if properties
            .iter()
            .any(|property| property.property_id == cashflow.property_id && property.active)
        {
            apply_cashflow(
                ledger,
                recorder,
                tax_facts,
                month,
                &cashflow.cause_id,
                &cashflow.from,
                &cashflow.to,
                cashflow.amount,
                cashflow.income_category.as_deref(),
                cashflow.deduction_category.as_deref(),
            )?;
        }
    }
    Ok(())
}

#[allow(clippy::too_many_arguments)]
fn apply_cashflow(
    ledger: &mut Ledger,
    recorder: &mut Recorder,
    tax_facts: &mut BTreeMap<(String, String), TaxFacts>,
    month: u32,
    cause_id: &str,
    from: &AccountRef,
    to: &AccountRef,
    amount: Money,
    income_category: Option<&str>,
    deduction_category: Option<&str>,
) -> Result<(), SimulationError> {
    transfer_money(ledger, recorder, month, cause_id, from, to, amount)?;
    record_transfer_income(tax_facts, &to.agent_id, income_category, amount)?;
    record_transfer_deduction(tax_facts, &from.agent_id, deduction_category, amount)
}

fn property_obligations(
    fixture: &Fixture,
    properties: &[PropertyState],
    mortgages: &[MortgageState],
    month: u32,
) -> Result<Vec<ActiveObligation>, SimulationError> {
    let mut obligations = Vec::new();
    for (index, mortgage) in mortgages.iter().enumerate() {
        if !mortgage.active || mortgage.origination_month >= month || mortgage.principal.0 <= 0 {
            continue;
        }
        let interest = Money(mul_div_round_half_up(
            mortgage.principal.0,
            mortgage.annual_interest_rate_ppb,
            12 * RATE_SCALE_PPB,
            "mortgage monthly interest",
        )?);
        let due = Money(
            mortgage
                .monthly_payment
                .0
                .min(mortgage.principal.checked_add(interest)?.0),
        );
        let principal = Money((due.0 - interest.0).max(0).min(mortgage.principal.0));
        obligations.push(ActiveObligation {
            authored_id: format!("{}_payment", mortgage.liability_id),
            obligation_type: "mortgage_payment".into(),
            from: AccountRef::new(&mortgage.agent_id, &mortgage.payment_account_id),
            to: AccountRef::new(
                &mortgage.counterparty_agent_id,
                &mortgage.counterparty_account_id,
            ),
            amount_due: due,
            effect: ObligationEffect::Mortgage {
                mortgage_index: index,
                interest,
                principal,
            },
        });
    }
    for policy in &fixture.scenario.property_tax_policies {
        let Some(property) = properties
            .iter()
            .find(|property| property.property_id == policy.property_id && property.active)
        else {
            continue;
        };
        if property.purchase_month >= month
            || policy.start_month > month
            || policy.end_month.is_some_and(|end| month > end)
        {
            continue;
        }
        let purchase = fixture
            .scenario
            .scheduled_property_purchases
            .iter()
            .find(|purchase| purchase.property_id == policy.property_id)
            .expect("validated property has a purchase");
        let location = fixture
            .scenario
            .locations
            .iter()
            .find(|location| location.location_id == property.location_id)
            .expect("validated property has a location");
        let rate = policy
            .annual_tax_rate_ppb
            .unwrap_or(location.annual_property_tax_rate_ppb);
        let annual_tax_numerator = i128::from(purchase.purchase_price.0)
            .checked_mul(i128::from(rate))
            .and_then(|value| {
                i128::from(location.annual_special_assessment.0)
                    .checked_mul(i128::from(RATE_SCALE_PPB))
                    .and_then(|special| value.checked_add(special))
            })
            .ok_or(ArithmeticError::Overflow {
                operation: "property tax",
            })?;
        let amount_due = Money(
            i64::try_from(mul_div_i128_round_half_up(
                annual_tax_numerator,
                1,
                12 * i128::from(RATE_SCALE_PPB),
                "property tax",
            )?)
            .map_err(|_| ArithmeticError::Overflow {
                operation: "property tax",
            })?,
        );
        obligations.push(ActiveObligation {
            authored_id: format!("{}_property_tax", policy.property_id),
            obligation_type: "property_tax".into(),
            from: AccountRef::new(&policy.owner_agent_id, &policy.from_account_id),
            to: AccountRef::new(
                &policy.tax_authority_agent_id,
                &policy.tax_authority_account_id,
            ),
            amount_due,
            effect: ObligationEffect::None,
        });
    }
    Ok(obligations)
}

fn mortgage_monthly_payment(
    principal: Money,
    annual_rate_ppb: i64,
    term_months: u32,
) -> Result<Money, SimulationError> {
    if annual_rate_ppb == 0 {
        return Ok(Money(mul_div_round_half_up(
            principal.0,
            1,
            i64::from(term_months),
            "zero-rate mortgage payment",
        )?));
    }
    let monthly_rate = mul_div_i128_round_half_up(
        i128::from(annual_rate_ppb),
        CONTRACT_SCALE,
        12 * i128::from(RATE_SCALE_PPB),
        "mortgage monthly rate",
    )?;
    let factor = CONTRACT_SCALE
        .checked_add(monthly_rate)
        .ok_or(ArithmeticError::Overflow {
            operation: "mortgage rate factor",
        })?;
    let mut discount = CONTRACT_SCALE;
    for _ in 0..term_months {
        discount = mul_div_i128_round_half_up(
            discount,
            CONTRACT_SCALE,
            factor,
            "mortgage discount factor",
        )?;
    }
    let denominator = CONTRACT_SCALE
        .checked_sub(discount)
        .ok_or(ArithmeticError::Overflow {
            operation: "mortgage annuity denominator",
        })?;
    let payment = mul_div_i128_round_half_up(
        i128::from(principal.0),
        monthly_rate,
        denominator,
        "mortgage payment",
    )?;
    Ok(Money(i64::try_from(payment).map_err(|_| {
        ArithmeticError::Overflow {
            operation: "mortgage payment",
        }
    })?))
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

fn record_transfer_deduction(
    tax_facts: &mut BTreeMap<(String, String), TaxFacts>,
    payer_agent_id: &str,
    deduction_category: Option<&str>,
    amount: Money,
) -> Result<(), SimulationError> {
    if deduction_category != Some("ordinary") {
        return Ok(());
    }
    for ((agent_id, _), facts) in tax_facts {
        if agent_id == payer_agent_id {
            facts.ordinary_income = facts.ordinary_income.checked_sub(amount)?;
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

fn record_section_1250_recapture(
    tax_facts: &mut BTreeMap<(String, String), TaxFacts>,
    agent_id: &str,
    amount: Money,
) -> Result<(), SimulationError> {
    for ((taxpayer, _), facts) in tax_facts {
        if taxpayer == agent_id {
            facts.section_1250_recapture = facts.section_1250_recapture.checked_add(amount)?;
        }
    }
    Ok(())
}

fn record_rental_interest_deduction(
    tax_facts: &mut BTreeMap<(String, String), TaxFacts>,
    agent_id: &str,
    amount: Money,
) -> Result<(), SimulationError> {
    for ((taxpayer, _), facts) in tax_facts {
        if taxpayer == agent_id {
            facts.ordinary_income = facts.ordinary_income.checked_sub(amount)?;
            facts.rental_interest_deduction =
                facts.rental_interest_deduction.checked_add(amount)?;
        }
    }
    Ok(())
}

fn record_mortgage_interest_deduction(
    tax_facts: &mut BTreeMap<(String, String), TaxFacts>,
    agent_id: &str,
    amount: Money,
) -> Result<(), SimulationError> {
    for ((taxpayer, _), facts) in tax_facts {
        if taxpayer == agent_id {
            facts.mortgage_interest_deduction =
                facts.mortgage_interest_deduction.checked_add(amount)?;
            facts.itemized_deduction = facts.itemized_deduction.checked_add(amount)?;
        }
    }
    Ok(())
}

fn accrue_property_depreciation(
    tax_facts: &mut BTreeMap<(String, String), TaxFacts>,
    properties: &mut [PropertyState],
) -> Result<(), SimulationError> {
    for property in properties
        .iter_mut()
        .filter(|property| property.active && property.rented_fraction_ppb > 0)
    {
        let monthly_factor_ppb = mul_div_round_half_up(
            property.rented_fraction_ppb,
            1,
            330,
            "property monthly depreciation factor",
        )?;
        let depreciation = Money(mul_div_round_half_up(
            property.building_basis.0,
            monthly_factor_ppb,
            RATE_SCALE_PPB,
            "property monthly depreciation",
        )?);
        property.cumulative_depreciation =
            property.cumulative_depreciation.checked_add(depreciation)?;
        property.depreciation_ytd = property.depreciation_ytd.checked_add(depreciation)?;
        for ((taxpayer, _), facts) in tax_facts.iter_mut() {
            if taxpayer == &property.owner_agent_id {
                facts.ordinary_income = facts.ordinary_income.checked_sub(depreciation)?;
                facts.depreciation_deduction =
                    facts.depreciation_deduction.checked_add(depreciation)?;
            }
        }
    }
    Ok(())
}

fn reset_property_tax_year_state(
    properties: &mut [PropertyState],
    mortgages: &mut [MortgageState],
) {
    for property in properties {
        property.depreciation_ytd = Money(0);
    }
    for mortgage in mortgages {
        mortgage.interest_paid_ytd = Money(0);
        mortgage.rental_interest_paid_ytd = Money(0);
        mortgage.principal_paid_ytd = Money(0);
    }
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
                section_1250_recapture: facts.section_1250_recapture,
                rental_interest_deduction: facts.rental_interest_deduction,
                depreciation_deduction: facts.depreciation_deduction,
                mortgage_interest_deduction: facts.mortgage_interest_deduction,
                itemized_deduction: facts.itemized_deduction,
                ordinary_taxable: assessment.ordinary_taxable,
                long_term_capital_gain_taxable: assessment.long_term_capital_gain_taxable,
                ordinary_tax: assessment.ordinary_tax,
                capital_gain_tax: assessment.capital_gain_tax,
                section_1250_tax: assessment.section_1250_tax,
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

#[allow(clippy::too_many_arguments)]
fn settle_obligations(
    fixture: &Fixture,
    ledger: &mut Ledger,
    recorder: &mut Recorder,
    tax_facts: &mut BTreeMap<(String, String), TaxFacts>,
    properties: &[PropertyState],
    mortgages: &mut [MortgageState],
    month: u32,
    obligations: &[ActiveObligation],
) -> Result<bool, SimulationError> {
    let mut due_by_source = BTreeMap::<AccountRef, Money>::new();
    for obligation in obligations {
        let due = due_by_source
            .get(&obligation.from)
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
        let funded = funded_by_source[&obligation.from];
        let firing_id = format!("{}_m{month}", obligation.authored_id);
        let (amount_paid, shortfall) = if funded {
            match obligation.effect {
                ObligationEffect::None => transfer_money(
                    ledger,
                    recorder,
                    month,
                    &firing_id,
                    &obligation.from,
                    &obligation.to,
                    obligation.amount_due,
                )?,
                ObligationEffect::Mortgage {
                    mortgage_index,
                    interest,
                    principal,
                } => {
                    let mortgage = &mut mortgages[mortgage_index];
                    recorder.apply_entry(
                        ledger,
                        JournalEntry {
                            month,
                            cause_id: firing_id.clone(),
                            postings: vec![
                                Posting {
                                    account: obligation.from.clone(),
                                    amount: obligation.amount_due.checked_neg()?,
                                },
                                Posting {
                                    account: obligation.to.clone(),
                                    amount: obligation.amount_due,
                                },
                                Posting {
                                    account: mortgage_liability_account(
                                        &mortgage.agent_id,
                                        &mortgage.liability_id,
                                    ),
                                    amount: principal,
                                },
                                Posting {
                                    account: mortgage_interest_expense_account(
                                        &mortgage.agent_id,
                                        &mortgage.liability_id,
                                    ),
                                    amount: interest,
                                },
                                Posting {
                                    account: mortgage_receivable_account(
                                        &mortgage.counterparty_agent_id,
                                        &mortgage.liability_id,
                                    ),
                                    amount: principal.checked_neg()?,
                                },
                                Posting {
                                    account: mortgage_interest_income_account(
                                        &mortgage.counterparty_agent_id,
                                        &mortgage.liability_id,
                                    ),
                                    amount: interest.checked_neg()?,
                                },
                            ],
                        },
                    )?;
                    mortgage.principal = mortgage.principal.checked_sub(principal)?;
                    mortgage.interest_paid_ytd =
                        mortgage.interest_paid_ytd.checked_add(interest)?;
                    let rented_fraction_ppb = properties
                        .iter()
                        .find(|property| property.property_id == mortgage.property_id)
                        .map_or(0, |property| property.rented_fraction_ppb);
                    let rental_interest = Money(mul_div_round_half_up(
                        interest.0,
                        rented_fraction_ppb,
                        RATE_SCALE_PPB,
                        "rental mortgage interest",
                    )?);
                    let owner_interest = interest.checked_sub(rental_interest)?;
                    mortgage.rental_interest_paid_ytd = mortgage
                        .rental_interest_paid_ytd
                        .checked_add(rental_interest)?;
                    record_rental_interest_deduction(
                        tax_facts,
                        &mortgage.agent_id,
                        rental_interest,
                    )?;
                    if fixture
                        .scenario
                        .mortgage_interest_deduction_policies
                        .iter()
                        .any(|policy| {
                            policy.liability_id == mortgage.liability_id
                                && policy.owner_agent_id == mortgage.agent_id
                        })
                    {
                        record_mortgage_interest_deduction(
                            tax_facts,
                            &mortgage.agent_id,
                            owner_interest,
                        )?;
                    }
                    mortgage.principal_paid_ytd =
                        mortgage.principal_paid_ytd.checked_add(principal)?;
                    if mortgage.principal == Money(0) {
                        mortgage.active = false;
                    }
                    recorder.record_mortgage_payment(MortgagePaymentOutcome {
                        month,
                        cause_id: firing_id.clone(),
                        liability_id: mortgage.liability_id.clone(),
                        agent_id: mortgage.agent_id.clone(),
                        counterparty_agent_id: mortgage.counterparty_agent_id.clone(),
                        property_id: mortgage.property_id.clone(),
                        from_account_id: mortgage.payment_account_id.clone(),
                        to_account_id: mortgage.counterparty_account_id.clone(),
                        interest,
                        principal,
                        total_payment: obligation.amount_due,
                    })?;
                }
            }
            (obligation.amount_due, Money(0))
        } else {
            any_failure = true;
            (Money(0), obligation.amount_due)
        };
        recorder.record_obligation(ObligationOutcome {
            month,
            obligation_id: firing_id,
            obligation_type: obligation.obligation_type.clone(),
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

fn property_basis_writeoff_account(agent_id: &str, property_id: &str) -> AccountRef {
    AccountRef::new(agent_id, format!("expense:property-basis:{property_id}"))
}

fn tax_expense_account(agent_id: &str, jurisdiction_id: &str) -> AccountRef {
    AccountRef::new(agent_id, format!("expense:tax:{jurisdiction_id}"))
}

fn tax_liability_account(agent_id: &str, jurisdiction_id: &str) -> AccountRef {
    AccountRef::new(agent_id, format!("liability:tax:{jurisdiction_id}"))
}

fn property_asset_account(agent_id: &str, property_id: &str) -> AccountRef {
    AccountRef::new(agent_id, format!("asset:property:{property_id}"))
}

fn property_sale_clearing_account(agent_id: &str, property_id: &str) -> AccountRef {
    AccountRef::new(agent_id, format!("equity:property-sale:{property_id}"))
}

fn mortgage_liability_account(agent_id: &str, liability_id: &str) -> AccountRef {
    AccountRef::new(agent_id, format!("liability:mortgage:{liability_id}"))
}

fn mortgage_interest_expense_account(agent_id: &str, liability_id: &str) -> AccountRef {
    AccountRef::new(
        agent_id,
        format!("expense:mortgage-interest:{liability_id}"),
    )
}

fn mortgage_receivable_account(agent_id: &str, liability_id: &str) -> AccountRef {
    AccountRef::new(
        agent_id,
        format!("asset:mortgage-receivable:{liability_id}"),
    )
}

fn mortgage_interest_income_account(agent_id: &str, liability_id: &str) -> AccountRef {
    AccountRef::new(agent_id, format!("income:mortgage-interest:{liability_id}"))
}

fn mortgage_funding_account(agent_id: &str, liability_id: &str) -> AccountRef {
    AccountRef::new(agent_id, format!("equity:mortgage-funding:{liability_id}"))
}

fn month_output(
    month: u32,
    ledger: &Ledger,
    properties: &[PropertyState],
    mortgages: &[MortgageState],
    failed: bool,
) -> MonthOutput {
    MonthOutput {
        month,
        balances: account_balances(ledger, failed),
        properties: property_states(properties, failed),
        mortgages: mortgage_states(mortgages, failed),
        failed,
    }
}

fn property_states(properties: &[PropertyState], failed: bool) -> Vec<PropertyState> {
    properties
        .iter()
        .cloned()
        .map(|mut property| {
            if failed {
                property.adjusted_basis = Money(0);
                property.contribution_used = Money(0);
                property.equity_ledger = Money(0);
            }
            property
        })
        .collect()
}

fn mortgage_states(mortgages: &[MortgageState], failed: bool) -> Vec<MortgageState> {
    mortgages
        .iter()
        .cloned()
        .map(|mut mortgage| {
            if failed {
                mortgage.monthly_payment = Money(0);
                mortgage.principal = Money(0);
                mortgage.interest_paid_ytd = Money(0);
                mortgage.principal_paid_ytd = Money(0);
            }
            mortgage
        })
        .collect()
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
        AccountSpec, InitialLotSpec, LocationSpec, MortgageFinancingSpec, ObligationSpec,
        PropertyTaxPolicySpec, RecurringObligationSpec, ScenarioSpec,
        ScheduledPropertyPurchaseSpec, ScheduledSaleSpec, ScheduledTransferSpec, SeriesSpec,
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
                locations: vec![],
                scheduled_transfers: vec![],
                recurring_transfers: vec![],
                scheduled_property_cashflows: vec![],
                recurring_property_cashflows: vec![],
                obligations: vec![],
                recurring_obligations: vec![],
                initial_lots: vec![],
                scheduled_sales: vec![],
                tax_profiles: vec![],
                distributions: vec![],
                scheduled_property_purchases: vec![],
                property_rented_fraction_events: vec![],
                capital_improvement_events: vec![],
                property_sales: vec![],
                mortgage_interest_deduction_policies: vec![],
                property_tax_policies: vec![],
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
                deduction_category: None,
            });
        assert!(matches!(
            simulate(&fixture),
            Err(SimulationError::UnknownAccountReference { .. })
        ));
    }

    #[test]
    fn rejects_invalid_property_contracts_before_rollout_execution() {
        let mut fixture = minimal_fixture();
        fixture.scenario.accounts.push(AccountSpec {
            account: AccountRef::new("seller", "checking"),
            opening_balance: Money(0),
        });
        fixture.scenario.scheduled_property_purchases = vec![ScheduledPropertyPurchaseSpec {
            month: 0,
            cause_id: "buy-home".into(),
            property_id: "home".into(),
            location_id: "missing".into(),
            buyer_agent_id: "alice".into(),
            buyer_account_id: "checking".into(),
            seller_agent_id: "seller".into(),
            seller_account_id: "checking".into(),
            purchase_price: Money(10),
            down_payment: Money(10),
            buyer_closing_cost: Money(0),
            rented_fraction_ppb: 0,
            land_value_fraction_ppb: 200_000_000,
            mortgage: None,
        }];
        assert!(matches!(
            simulate(&fixture),
            Err(SimulationError::UnknownLocation { .. })
        ));

        fixture.scenario.locations.push(LocationSpec {
            location_id: "missing".into(),
            display_name: "Known now".into(),
            jurisdiction_ids: vec![],
            annual_property_tax_rate_ppb: 0,
            annual_special_assessment: Money(0),
        });
        fixture.scenario.scheduled_property_purchases[0].down_payment = Money(9);
        assert!(matches!(
            simulate(&fixture),
            Err(SimulationError::InvalidPropertyTerms { .. })
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
                locations: vec![],
                scheduled_transfers: vec![ScheduledTransferSpec {
                    month: 0,
                    cause_id: "gift".into(),
                    from: bob_cash,
                    to: alice_cash,
                    amount: Money(500),
                    income_category: None,
                    deduction_category: None,
                }],
                recurring_transfers: vec![],
                scheduled_property_cashflows: vec![],
                recurring_property_cashflows: vec![],
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
                distributions: vec![],
                scheduled_property_purchases: vec![],
                property_rented_fraction_events: vec![],
                capital_improvement_events: vec![],
                property_sales: vec![],
                mortgage_interest_deduction_policies: vec![],
                property_tax_policies: vec![],
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
            assert_eq!(
                summary.ending_properties,
                rollout.months.last().unwrap().properties
            );
            assert_eq!(
                summary.ending_mortgages,
                rollout.months.last().unwrap().mortgages
            );
            assert_eq!(summary.journal_entry_count, rollout.journal.len() as u64);
            assert_eq!(summary.disposition_count, rollout.dispositions.len() as u64);
            assert_eq!(summary.tax_accrual_count, rollout.tax_accruals.len() as u64);
            assert_eq!(
                summary.distribution_count,
                rollout.distributions.len() as u64
            );
            assert_eq!(
                summary.property_purchase_count,
                rollout.property_purchases.len() as u64
            );
            assert_eq!(
                summary.mortgage_payment_count,
                rollout.mortgage_payments.len() as u64
            );
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
    fn financed_property_purchase_and_first_monthly_carry_match_contract() {
        let mut fixture = minimal_fixture();
        fixture.scenario.horizon_months = 2;
        fixture.scenario.accounts = vec![
            AccountSpec {
                account: AccountRef::new("alice", "checking"),
                opening_balance: Money(12_000_000),
            },
            AccountSpec {
                account: AccountRef::new("seller", "checking"),
                opening_balance: Money(0),
            },
            AccountSpec {
                account: AccountRef::new("bank", "checking"),
                opening_balance: Money(0),
            },
            AccountSpec {
                account: AccountRef::new("county", "checking"),
                opening_balance: Money(0),
            },
        ];
        fixture.scenario.locations = vec![LocationSpec {
            location_id: "sf".into(),
            display_name: "San Francisco".into(),
            jurisdiction_ids: vec![],
            annual_property_tax_rate_ppb: 11_800_000,
            annual_special_assessment: Money(0),
        }];
        fixture.scenario.scheduled_property_purchases = vec![ScheduledPropertyPurchaseSpec {
            month: 0,
            cause_id: "alice-buys-home".into(),
            property_id: "home".into(),
            location_id: "sf".into(),
            buyer_agent_id: "alice".into(),
            buyer_account_id: "checking".into(),
            seller_agent_id: "seller".into(),
            seller_account_id: "checking".into(),
            purchase_price: Money(50_000_000),
            down_payment: Money(10_000_000),
            buyer_closing_cost: Money(1_000_000),
            rented_fraction_ppb: 0,
            land_value_fraction_ppb: 200_000_000,
            mortgage: Some(MortgageFinancingSpec {
                liability_id: "home-mortgage".into(),
                lender_agent_id: "bank".into(),
                lender_account_id: "checking".into(),
                principal: Money(40_000_000),
                annual_interest_rate_ppb: 60_000_000,
                term_months: 360,
            }),
        }];
        fixture.scenario.property_tax_policies = vec![PropertyTaxPolicySpec {
            property_id: "home".into(),
            owner_agent_id: "alice".into(),
            from_account_id: "checking".into(),
            tax_authority_agent_id: "county".into(),
            tax_authority_account_id: "checking".into(),
            annual_tax_rate_ppb: Some(12_000_000),
            start_month: 0,
            end_month: None,
        }];

        let rollout = simulate(&fixture).unwrap().rollouts.remove(0);
        let month_zero = &rollout.months[1];
        assert_eq!(month_zero.properties[0].adjusted_basis, Money(51_000_000));
        assert_eq!(
            month_zero.properties[0].contribution_used,
            Money(11_000_000)
        );
        assert_eq!(month_zero.properties[0].equity_ledger, Money(10_000_000));
        assert_eq!(month_zero.mortgages[0].monthly_payment, Money(239_820));
        assert_eq!(month_zero.mortgages[0].principal, Money(40_000_000));

        let final_month = &rollout.months[2];
        assert_eq!(final_month.mortgages[0].interest_paid_ytd, Money(200_000));
        assert_eq!(final_month.mortgages[0].principal_paid_ytd, Money(39_820));
        assert_eq!(final_month.mortgages[0].principal, Money(39_960_180));
        let cash: BTreeMap<_, _> = final_month
            .balances
            .iter()
            .filter(|balance| balance.account.account_id == "checking")
            .map(|balance| (balance.account.agent_id.as_str(), balance.balance))
            .collect();
        assert_eq!(cash["alice"], Money(710_180));
        assert_eq!(cash["seller"], Money(11_000_000));
        assert_eq!(cash["bank"], Money(239_820));
        assert_eq!(cash["county"], Money(50_000));
        assert_eq!(rollout.property_purchases.len(), 1);
        assert_eq!(rollout.mortgage_originations.len(), 1);
        assert_eq!(rollout.mortgage_payments.len(), 1);
        assert!(rollout.journal.iter().all(|entry| {
            entry
                .postings
                .iter()
                .map(|posting| i128::from(posting.amount.0))
                .sum::<i128>()
                == 0
        }));
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
                locations: vec![],
                scheduled_transfers: vec![],
                recurring_transfers: vec![],
                scheduled_property_cashflows: vec![],
                recurring_property_cashflows: vec![],
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
                distributions: vec![],
                scheduled_property_purchases: vec![],
                property_rented_fraction_events: vec![],
                capital_improvement_events: vec![],
                property_sales: vec![],
                mortgage_interest_deduction_policies: vec![],
                property_tax_policies: vec![],
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
                locations: vec![],
                scheduled_transfers: vec![ScheduledTransferSpec {
                    month: 1,
                    cause_id: "must-not-run".into(),
                    from: alice_cash.clone(),
                    to: bob_cash.clone(),
                    amount: Money(1),
                    income_category: None,
                    deduction_category: None,
                }],
                recurring_transfers: vec![],
                scheduled_property_cashflows: vec![],
                recurring_property_cashflows: vec![],
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
                distributions: vec![],
                scheduled_property_purchases: vec![],
                property_rented_fraction_events: vec![],
                capital_improvement_events: vec![],
                property_sales: vec![],
                mortgage_interest_deduction_policies: vec![],
                property_tax_policies: vec![],
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
                locations: vec![],
                scheduled_transfers: vec![],
                recurring_transfers: vec![],
                scheduled_property_cashflows: vec![],
                recurring_property_cashflows: vec![],
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
                distributions: vec![],
                scheduled_property_purchases: vec![],
                property_rented_fraction_events: vec![],
                capital_improvement_events: vec![],
                property_sales: vec![],
                mortgage_interest_deduction_policies: vec![],
                property_tax_policies: vec![],
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
