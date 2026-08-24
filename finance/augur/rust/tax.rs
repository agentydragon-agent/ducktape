use serde::{Deserialize, Serialize};
use thiserror::Error;

use crate::money::{ArithmeticError, Money};

pub const RATE_SCALE: i64 = 1_000_000_000;

#[derive(Clone, Copy, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
pub struct TaxFacts {
    pub ordinary_income: Money,
    pub short_term_gain: Money,
    pub long_term_gain: Money,
    pub capital_loss_carryforward: Money,
    pub itemized_deduction: Money,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct TaxBracket {
    /// Inclusive upper edge. `None` is the open-ended top bracket.
    pub upper: Option<Money>,
    /// Marginal rate in parts per billion.
    pub rate_ppb: i64,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct TaxRules {
    pub jurisdiction_id: String,
    pub ordinary_brackets: Vec<TaxBracket>,
    #[serde(default)]
    pub long_term_capital_gain_brackets: Vec<TaxBracket>,
    pub standard_deduction: Money,
    pub max_capital_loss_ordinary_offset: Money,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct TaxAssessment {
    pub ordinary_taxable: Money,
    pub long_term_capital_gain_taxable: Money,
    pub ordinary_tax: Money,
    pub capital_gain_tax: Money,
    pub total_tax: Money,
    pub capital_loss_carryforward: Money,
}

#[derive(Debug, Error, Eq, PartialEq)]
pub enum TaxError {
    #[error("tax brackets are empty")]
    EmptyBrackets,
    #[error("tax bracket upper edges are not strictly increasing")]
    InvalidBrackets,
    #[error("tax rate {rate_ppb} is outside [0, {scale}]")]
    InvalidRate { rate_ppb: i64, scale: i64 },
    #[error("{field} must be nonnegative, got {value}")]
    NegativeRuleValue { field: &'static str, value: i64 },
    #[error(transparent)]
    Arithmetic(#[from] ArithmeticError),
}

pub fn validate_rules(rules: &TaxRules) -> Result<(), TaxError> {
    if rules.standard_deduction.0 < 0 {
        return Err(TaxError::NegativeRuleValue {
            field: "standard_deduction",
            value: rules.standard_deduction.0,
        });
    }
    if rules.max_capital_loss_ordinary_offset.0 < 0 {
        return Err(TaxError::NegativeRuleValue {
            field: "max_capital_loss_ordinary_offset",
            value: rules.max_capital_loss_ordinary_offset.0,
        });
    }
    validate_brackets(&rules.ordinary_brackets)?;
    if !rules.long_term_capital_gain_brackets.is_empty() {
        validate_brackets(&rules.long_term_capital_gain_brackets)?;
    }
    Ok(())
}

pub fn assess(facts: TaxFacts, rules: &TaxRules) -> Result<TaxAssessment, TaxError> {
    validate_rules(rules)?;
    let (short_term, long_term, ordinary_offset, carryforward) = net_capital_gains(
        facts.short_term_gain,
        facts.long_term_gain,
        facts.capital_loss_carryforward,
        rules.max_capital_loss_ordinary_offset,
    )?;
    let deduction = facts.itemized_deduction.max(rules.standard_deduction);
    if rules.long_term_capital_gain_brackets.is_empty() {
        let taxable = nonnegative(
            facts
                .ordinary_income
                .checked_add(short_term)?
                .checked_add(long_term)?
                .checked_sub(ordinary_offset)?
                .checked_sub(deduction)?,
        );
        let ordinary_tax = apply_brackets(taxable, &rules.ordinary_brackets)?;
        return Ok(TaxAssessment {
            ordinary_taxable: taxable,
            long_term_capital_gain_taxable: Money(0),
            ordinary_tax,
            capital_gain_tax: Money(0),
            total_tax: ordinary_tax,
            capital_loss_carryforward: carryforward,
        });
    }

    let ordinary_taxable = nonnegative(
        facts
            .ordinary_income
            .checked_add(short_term)?
            .checked_sub(ordinary_offset)?
            .checked_sub(deduction)?,
    );
    // Match the existing simulator contract: preferential gains remain fully
    // taxable after the ordinary-income deduction calculation and are stacked
    // on top of ordinary taxable income.
    let capital_taxable = nonnegative(long_term);
    let ordinary_tax = apply_brackets(ordinary_taxable, &rules.ordinary_brackets)?;
    let capital_gain_tax = apply_stacked_brackets(
        capital_taxable,
        ordinary_taxable,
        &rules.long_term_capital_gain_brackets,
    )?;
    Ok(TaxAssessment {
        ordinary_taxable,
        long_term_capital_gain_taxable: capital_taxable,
        ordinary_tax,
        capital_gain_tax,
        total_tax: ordinary_tax.checked_add(capital_gain_tax)?,
        capital_loss_carryforward: carryforward,
    })
}

pub fn apply_brackets(amount: Money, brackets: &[TaxBracket]) -> Result<Money, TaxError> {
    validate_brackets(brackets)?;
    let mut previous = 0_i64;
    let mut numerator = 0_i128;
    for bracket in brackets {
        let upper = bracket.upper.map_or(i64::MAX, |value| value.0);
        let slice = amount.0.min(upper).saturating_sub(previous).max(0);
        numerator = numerator
            .checked_add(i128::from(slice) * i128::from(bracket.rate_ppb))
            .ok_or(ArithmeticError::Overflow {
                operation: "tax bracket accumulation",
            })?;
        previous = upper;
    }
    Ok(Money(round_positive_numerator(
        numerator,
        RATE_SCALE,
        "tax bracket rounding",
    )?))
}

pub fn apply_stacked_brackets(
    amount: Money,
    lower_stack: Money,
    brackets: &[TaxBracket],
) -> Result<Money, TaxError> {
    validate_brackets(brackets)?;
    let total = lower_stack.checked_add(amount)?;
    let mut previous = 0_i64;
    let mut numerator = 0_i128;
    for bracket in brackets {
        let upper = bracket.upper.map_or(i64::MAX, |value| value.0);
        let slice_top = total.0.min(upper);
        let slice_bottom = lower_stack.0.max(previous);
        let slice = slice_top.saturating_sub(slice_bottom).max(0);
        numerator = numerator
            .checked_add(i128::from(slice) * i128::from(bracket.rate_ppb))
            .ok_or(ArithmeticError::Overflow {
                operation: "capital-gain bracket accumulation",
            })?;
        previous = upper;
    }
    Ok(Money(round_positive_numerator(
        numerator,
        RATE_SCALE,
        "capital-gain bracket rounding",
    )?))
}

pub fn net_capital_gains(
    short_term: Money,
    long_term: Money,
    carryforward_in: Money,
    maximum_ordinary_offset: Money,
) -> Result<(Money, Money, Money, Money), ArithmeticError> {
    let mut short = short_term.0;
    let mut long = long_term.0;
    let short_loss_against_long = short.saturating_neg().max(0).min(long.max(0));
    short = short
        .checked_add(short_loss_against_long)
        .ok_or(ArithmeticError::Overflow {
            operation: "short-term loss netting",
        })?;
    long = long
        .checked_sub(short_loss_against_long)
        .ok_or(ArithmeticError::Overflow {
            operation: "long-term gain netting",
        })?;
    let long_loss_against_short = long.saturating_neg().max(0).min(short.max(0));
    long = long
        .checked_add(long_loss_against_short)
        .ok_or(ArithmeticError::Overflow {
            operation: "long-term loss netting",
        })?;
    short = short
        .checked_sub(long_loss_against_short)
        .ok_or(ArithmeticError::Overflow {
            operation: "short-term gain netting",
        })?;

    let mut carry = carryforward_in.0.max(0);
    let used_short = short.max(0).min(carry);
    short -= used_short;
    carry -= used_short;
    let used_long = long.max(0).min(carry);
    long -= used_long;
    carry -= used_long;
    let net_gain = short.checked_add(long).ok_or(ArithmeticError::Overflow {
        operation: "capital-gain netting",
    })?;
    let residual_loss = net_gain
        .checked_neg()
        .ok_or(ArithmeticError::Overflow {
            operation: "capital-loss netting",
        })?
        .max(0)
        .checked_add(carry)
        .ok_or(ArithmeticError::Overflow {
            operation: "capital-loss carryforward",
        })?;
    let ordinary_offset = residual_loss.min(maximum_ordinary_offset.0.max(0));
    Ok((
        Money(short.max(0)),
        Money(long.max(0)),
        Money(ordinary_offset),
        Money(residual_loss - ordinary_offset),
    ))
}

fn validate_brackets(brackets: &[TaxBracket]) -> Result<(), TaxError> {
    if brackets.is_empty() {
        return Err(TaxError::EmptyBrackets);
    }
    let mut previous = -1_i64;
    let mut saw_open = false;
    for bracket in brackets {
        if !(0..=RATE_SCALE).contains(&bracket.rate_ppb) {
            return Err(TaxError::InvalidRate {
                rate_ppb: bracket.rate_ppb,
                scale: RATE_SCALE,
            });
        }
        match bracket.upper {
            Some(upper) if !saw_open && upper.0 > previous => previous = upper.0,
            None if !saw_open => saw_open = true,
            _ => return Err(TaxError::InvalidBrackets),
        }
    }
    if !saw_open {
        return Err(TaxError::InvalidBrackets);
    }
    Ok(())
}

fn round_positive_numerator(
    numerator: i128,
    denominator: i64,
    operation: &'static str,
) -> Result<i64, ArithmeticError> {
    debug_assert!(numerator >= 0);
    let denominator = i128::from(denominator);
    let rounded =
        numerator / denominator + i128::from(numerator % denominator >= (denominator + 1) / 2);
    i64::try_from(rounded).map_err(|_| ArithmeticError::Overflow { operation })
}

fn nonnegative(value: Money) -> Money {
    Money(value.0.max(0))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn federal() -> TaxRules {
        TaxRules {
            jurisdiction_id: "federal_us".into(),
            ordinary_brackets: vec![
                TaxBracket {
                    upper: Some(Money(1_160_000)),
                    rate_ppb: 100_000_000,
                },
                TaxBracket {
                    upper: Some(Money(4_715_000)),
                    rate_ppb: 120_000_000,
                },
                TaxBracket {
                    upper: None,
                    rate_ppb: 220_000_000,
                },
            ],
            long_term_capital_gain_brackets: vec![
                TaxBracket {
                    upper: Some(Money(4_702_500)),
                    rate_ppb: 0,
                },
                TaxBracket {
                    upper: None,
                    rate_ppb: 150_000_000,
                },
            ],
            standard_deduction: Money(1_460_000),
            max_capital_loss_ordinary_offset: Money(300_000),
        }
    }

    #[test]
    fn bracket_tax_rounds_aggregate_once() {
        let tax = apply_brackets(Money(2_000_000), &federal().ordinary_brackets).unwrap();
        assert_eq!(tax, Money(216_800));
    }

    #[test]
    fn preferential_gain_stacks_above_ordinary_income() {
        let assessment = assess(
            TaxFacts {
                ordinary_income: Money(5_000_000),
                long_term_gain: Money(2_000_000),
                ..TaxFacts::default()
            },
            &federal(),
        )
        .unwrap();
        assert_eq!(assessment.ordinary_taxable, Money(3_540_000));
        assert_eq!(assessment.capital_gain_tax, Money(125_625));
    }

    #[test]
    fn losses_cross_net_and_carry_forward() {
        let (short, long, offset, carry) =
            net_capital_gains(Money(-1_000_000), Money(200_000), Money(0), Money(300_000)).unwrap();
        assert_eq!(
            (short, long, offset, carry),
            (Money(0), Money(0), Money(300_000), Money(500_000))
        );
    }

    #[test]
    fn capital_gain_netting_reports_overflow() {
        assert_eq!(
            net_capital_gains(Money(i64::MAX), Money(i64::MAX), Money(0), Money(300_000),),
            Err(ArithmeticError::Overflow {
                operation: "capital-gain netting",
            })
        );
    }

    #[test]
    fn rejects_negative_rule_amounts() {
        let mut rules = federal();
        rules.standard_deduction = Money(-1);
        assert_eq!(
            validate_rules(&rules),
            Err(TaxError::NegativeRuleValue {
                field: "standard_deduction",
                value: -1,
            })
        );
    }
}
