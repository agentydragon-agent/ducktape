use log::info;
use rust_decimal::prelude::*;
use rust_decimal_macros::*;

// TODO: deduplicate
fn decimal_log(x: Decimal) -> Decimal {
    info!("ln({})", x);
    let x = x.to_f64().unwrap();
    Decimal::from_f64(x.ln()).unwrap()
}

pub fn years_until_saved_up_exp(
    total: Decimal,
    yearly_yield: Decimal,
    target_number: Decimal,
    monthly_saving: Decimal,
) -> Decimal {
    // Calculate how much longer do we need to save to get that number.
    let c = -monthly_saving * dec!(12); // monthly savings (minus - because they're plus, not costs)
    let f_0 = total; // initial savings
    let i = yearly_yield; // yearly yield, e.g. 0.04 = 4%
    let i_prime = decimal_log(dec!(1) + i);
    let c = f_0 - (c / i_prime);

    let time_to_reach = |f_x: Decimal| -> Decimal {
        // Derivation:
        // f_x = c*math.Exp(1+i, x) + c/i_prime
        // 0 = c*math.Exp(1+i, x) + c/i_prime - f_x
        // -c*math.Exp(1+i, x) = c/i_prime - f_x
        // math.Exp(1+i, x) = (c/i_prime - f_x) / (-c)
        // x = math.Log((c/i_prime - f_x) / (-c)) / i_prime
        decimal_log((c / i_prime - f_x) / (-c)) / i_prime
    };
    time_to_reach(target_number)
}

// Calculates how long a given amount will last, in years.
pub fn get_investment_durability(
    total: Decimal,
    yearly_yield: Decimal,
    monthly_costs: Decimal,
) -> Decimal {
    let c = monthly_costs * dec!(12); // yearly costs
    let f_0 = total; // initial savings
    let i = yearly_yield; // yearly yield, e.g. 0.04 = 4%
    let i_prime = decimal_log(dec!(1) + i);
    let c = f_0 - (c / i_prime);
    decimal_log(-c / (c * i_prime)) / i_prime
}
