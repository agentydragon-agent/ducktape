use std::cmp::Ordering;

use thiserror::Error;

use crate::money::ArithmeticError;

#[derive(Debug, Error)]
pub enum AllocationError {
    #[error("allocation weights and values must be non-empty and have the same length")]
    Shape,
    #[error("allocation weights must all be positive")]
    InvalidWeight,
    #[error(transparent)]
    Arithmetic(#[from] ArithmeticError),
}

pub fn withdrawal_by_sleeve(
    values: &[i64],
    weights: &[i64],
    raise: i64,
) -> Result<Vec<i64>, AllocationError> {
    validate(values, weights)?;
    let available = values.iter().try_fold(0_i64, |sum, value| {
        sum.checked_add(*value).ok_or(ArithmeticError::Overflow {
            operation: "allocation available value",
        })
    })?;
    let wanted = raise.max(0).min(available);
    if wanted == 0 {
        return Ok(vec![0; values.len()]);
    }

    let mut order: Vec<usize> = (0..values.len()).collect();
    order.sort_by(|left, right| {
        ratio_cmp(
            values[*right],
            weights[*right],
            values[*left],
            weights[*left],
        )
        .then_with(|| left.cmp(right))
    });

    let mut value_prefix = 0_i128;
    let mut weight_prefix = 0_i128;
    let mut chosen = values.len() - 1;
    for (rank, index) in order.iter().copied().enumerate() {
        value_prefix = value_prefix.checked_add(i128::from(values[index])).ok_or(
            ArithmeticError::Overflow {
                operation: "allocation value prefix",
            },
        )?;
        weight_prefix = weight_prefix
            .checked_add(i128::from(weights[index]))
            .ok_or(ArithmeticError::Overflow {
                operation: "allocation weight prefix",
            })?;
        let feasible = if let Some(next) = order.get(rank + 1).copied() {
            (value_prefix - i128::from(wanted)) * i128::from(weights[next])
                >= i128::from(values[next]) * weight_prefix
        } else {
            true
        };
        if feasible {
            chosen = rank;
            break;
        }
    }

    value_prefix = order[..=chosen]
        .iter()
        .map(|index| i128::from(values[*index]))
        .sum();
    weight_prefix = order[..=chosen]
        .iter()
        .map(|index| i128::from(weights[*index]))
        .sum();
    let level_numerator = value_prefix - i128::from(wanted);
    let mut taken = values
        .iter()
        .zip(weights)
        .map(|(value, weight)| {
            let remaining = round_half_up_nonnegative(
                level_numerator * i128::from(*weight),
                weight_prefix,
                "allocation withdrawal water level",
            )?;
            Ok((*value - remaining).clamp(0, *value))
        })
        .collect::<Result<Vec<_>, AllocationError>>()?;
    settle_residual(&mut taken, values, wanted)?;
    Ok(taken)
}

pub fn deposit_by_sleeve(
    values: &[i64],
    weights: &[i64],
    invest: i64,
) -> Result<Vec<i64>, AllocationError> {
    validate(values, weights)?;
    let wanted = invest.max(0);
    if wanted == 0 {
        return Ok(vec![0; values.len()]);
    }

    let mut order: Vec<usize> = (0..values.len()).collect();
    order.sort_by(|left, right| {
        ratio_cmp(
            values[*left],
            weights[*left],
            values[*right],
            weights[*right],
        )
        .then_with(|| left.cmp(right))
    });

    let mut value_prefix = 0_i128;
    let mut weight_prefix = 0_i128;
    let mut chosen = values.len() - 1;
    for (rank, index) in order.iter().copied().enumerate() {
        value_prefix = value_prefix.checked_add(i128::from(values[index])).ok_or(
            ArithmeticError::Overflow {
                operation: "allocation value prefix",
            },
        )?;
        weight_prefix = weight_prefix
            .checked_add(i128::from(weights[index]))
            .ok_or(ArithmeticError::Overflow {
                operation: "allocation weight prefix",
            })?;
        let feasible = if let Some(next) = order.get(rank + 1).copied() {
            (value_prefix + i128::from(wanted)) * i128::from(weights[next])
                <= i128::from(values[next]) * weight_prefix
        } else {
            true
        };
        if feasible {
            chosen = rank;
            break;
        }
    }

    value_prefix = order[..=chosen]
        .iter()
        .map(|index| i128::from(values[*index]))
        .sum();
    weight_prefix = order[..=chosen]
        .iter()
        .map(|index| i128::from(weights[*index]))
        .sum();
    let level_numerator = value_prefix + i128::from(wanted);
    let mut given = values
        .iter()
        .zip(weights)
        .map(|(value, weight)| {
            let target = round_half_up_nonnegative(
                level_numerator * i128::from(*weight),
                weight_prefix,
                "allocation deposit water level",
            )?;
            Ok((target - *value).max(0))
        })
        .collect::<Result<Vec<_>, AllocationError>>()?;
    let caps = given
        .iter()
        .map(|value| {
            value.checked_add(wanted).ok_or(ArithmeticError::Overflow {
                operation: "allocation deposit residual cap",
            })
        })
        .collect::<Result<Vec<_>, _>>()?;
    settle_residual(&mut given, &caps, wanted)?;
    Ok(given)
}

pub fn quantity_for_value(
    value: i64,
    price: i64,
    quantity_scale: i64,
    round_up: bool,
) -> Result<i64, AllocationError> {
    if value <= 0 || price <= 0 {
        return Ok(0);
    }
    let scaled = i128::from(value)
        .checked_mul(i128::from(quantity_scale))
        .ok_or(ArithmeticError::Overflow {
            operation: "allocation quantity conversion",
        })?;
    let divisor = i128::from(price);
    let quantity = if round_up {
        scaled
            .checked_add(divisor - 1)
            .ok_or(ArithmeticError::Overflow {
                operation: "allocation quantity ceiling",
            })?
            / divisor
    } else {
        scaled / divisor
    };
    i64::try_from(quantity).map_err(|_| {
        AllocationError::Arithmetic(ArithmeticError::Overflow {
            operation: "allocation quantity",
        })
    })
}

fn validate(values: &[i64], weights: &[i64]) -> Result<(), AllocationError> {
    if values.is_empty() || values.len() != weights.len() {
        return Err(AllocationError::Shape);
    }
    if values.iter().any(|value| *value < 0) || weights.iter().any(|weight| *weight <= 0) {
        return Err(AllocationError::InvalidWeight);
    }
    Ok(())
}

fn ratio_cmp(left_value: i64, left_weight: i64, right_value: i64, right_weight: i64) -> Ordering {
    (i128::from(left_value) * i128::from(right_weight))
        .cmp(&(i128::from(right_value) * i128::from(left_weight)))
}

fn settle_residual(taken: &mut [i64], caps: &[i64], wanted: i64) -> Result<(), AllocationError> {
    let total = taken.iter().try_fold(0_i64, |sum, value| {
        sum.checked_add(*value).ok_or(ArithmeticError::Overflow {
            operation: "allocation rounded total",
        })
    })?;
    let residual = wanted.checked_sub(total).ok_or(ArithmeticError::Overflow {
        operation: "allocation residual",
    })?;
    if residual == 0 {
        return Ok(());
    }
    let mut target = 0;
    let mut most_headroom = if residual >= 0 {
        caps[0] - taken[0]
    } else {
        taken[0]
    };
    for index in 1..taken.len() {
        let headroom = if residual >= 0 {
            caps[index] - taken[index]
        } else {
            taken[index]
        };
        if headroom > most_headroom {
            target = index;
            most_headroom = headroom;
        }
    }
    taken[target] = taken[target]
        .checked_add(residual)
        .ok_or(ArithmeticError::Overflow {
            operation: "allocation residual adjustment",
        })?
        .clamp(0, caps[target]);
    Ok(())
}

fn round_half_up_nonnegative(
    numerator: i128,
    denominator: i128,
    operation: &'static str,
) -> Result<i64, AllocationError> {
    let rounded = numerator
        .checked_mul(2)
        .and_then(|value| value.checked_add(denominator))
        .ok_or(ArithmeticError::Overflow { operation })?
        / denominator
        / 2;
    i64::try_from(rounded)
        .map_err(|_| AllocationError::Arithmetic(ArithmeticError::Overflow { operation }))
}

#[cfg(test)]
mod tests {
    use super::{deposit_by_sleeve, quantity_for_value, withdrawal_by_sleeve};

    #[test]
    fn withdrawal_drains_the_overweight_sleeve_first() {
        assert_eq!(
            withdrawal_by_sleeve(&[90_000, 10_000], &[1, 1], 35_000).unwrap(),
            [35_000, 0]
        );
        assert_eq!(
            withdrawal_by_sleeve(&[90_000, 10_000], &[1, 1], 90_000).unwrap(),
            [85_000, 5_000]
        );
        assert_eq!(
            withdrawal_by_sleeve(&[900, 100], &[1, 1], 950).unwrap(),
            [875, 75]
        );
        assert_eq!(
            withdrawal_by_sleeve(&[5_000, 5_000], &[3, 1], 2_000).unwrap(),
            [0, 2_000]
        );
    }

    #[test]
    fn withdrawal_residuals_are_exact_and_bounded() {
        for wanted in [1, 7, 333, 99_991] {
            let values = [1_000_003, 700_001, 3];
            let taken = withdrawal_by_sleeve(&values, &[5, 3, 1], wanted).unwrap();
            assert_eq!(taken.iter().sum::<i64>(), wanted);
            assert!(
                taken
                    .iter()
                    .zip(values)
                    .all(|(amount, value)| *amount >= 0 && *amount <= value)
            );
        }
        assert_eq!(
            withdrawal_by_sleeve(&[300, 200], &[1, 1], 10_000).unwrap(),
            [300, 200]
        );
    }

    #[test]
    fn deposit_fills_the_underweight_sleeve_first() {
        assert_eq!(
            deposit_by_sleeve(&[90_000, 10_000], &[1, 1], 90_000).unwrap(),
            [5_000, 85_000]
        );
    }

    #[test]
    fn quantity_rounding_differs_for_raises_and_purchases() {
        assert_eq!(quantity_for_value(101, 100, 10, true).unwrap(), 11);
        assert_eq!(quantity_for_value(101, 100, 10, false).unwrap(), 10);
        assert_eq!(quantity_for_value(1_000, 0, 1, true).unwrap(), 0);
        for scale in [1, 100, 100_000_000] {
            for price in [1, 7, 333, 5_000_000] {
                let quantity = quantity_for_value(123_456_789, price, scale, true).unwrap();
                assert!(
                    i128::from(quantity) * i128::from(price)
                        >= i128::from(123_456_789) * i128::from(scale)
                );
            }
        }
    }
}
