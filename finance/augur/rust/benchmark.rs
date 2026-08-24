use std::{env, fs::File, hint::black_box, io::BufReader, time::Instant};

use augur_rust_simulator::{
    Fixture, PopulationOutput, ValidatedFixture, simulate_summaries_validated,
};
use serde::Serialize;

#[derive(Debug, Serialize)]
struct BenchmarkReport {
    rollout_count: u32,
    horizon_months: u32,
    repeats: usize,
    wall_seconds: Vec<f64>,
    median_wall_seconds: f64,
    rollouts_per_second: f64,
    rollout_months_per_second: f64,
    journal_entry_count: u64,
    disposition_count: u64,
    tax_accrual_count: u64,
    failure_count: u64,
    checksum: u64,
}

fn main() {
    if let Err(error) = run() {
        eprintln!("{error:#}");
        std::process::exit(1);
    }
}

fn run() -> Result<(), Box<dyn std::error::Error>> {
    let mut args = env::args_os();
    let program = args.next().unwrap_or_default();
    let input = args.next().ok_or_else(|| {
        format!(
            "usage: {} FIXTURE.json [REPEATS]",
            program.to_string_lossy()
        )
    })?;
    let repeats = args
        .next()
        .map(|value| value.to_string_lossy().parse::<usize>())
        .transpose()?
        .unwrap_or(5);
    if repeats == 0 || args.next().is_some() {
        return Err(format!(
            "usage: {} FIXTURE.json [REPEATS > 0]",
            program.to_string_lossy()
        )
        .into());
    }

    // Parsing and fixture validation are intentionally outside the timed
    // region. This target measures the rollout state machine and compact
    // population output, not JSON transport.
    let fixture: Fixture = serde_json::from_reader(BufReader::new(File::open(input)?))?;
    let rollout_count = fixture.rollout_count;
    let horizon_months = fixture.scenario.horizon_months;
    let fixture = ValidatedFixture::new(&fixture)?;
    black_box(simulate_summaries_validated(fixture)?);

    let mut durations = Vec::with_capacity(repeats);
    let mut last_output = None;
    for _ in 0..repeats {
        let started = Instant::now();
        let output = black_box(simulate_summaries_validated(fixture)?);
        durations.push(started.elapsed().as_secs_f64());
        last_output = Some(output);
    }
    let output = last_output.expect("positive repeat count");
    let mut sorted = durations.clone();
    sorted.sort_by(f64::total_cmp);
    let median = sorted[sorted.len() / 2];
    let rollout_months = f64::from(rollout_count) * f64::from(horizon_months);
    let report = BenchmarkReport {
        rollout_count,
        horizon_months,
        repeats,
        wall_seconds: durations,
        median_wall_seconds: median,
        rollouts_per_second: f64::from(rollout_count) / median,
        rollout_months_per_second: rollout_months / median,
        journal_entry_count: output
            .rollouts
            .iter()
            .map(|rollout| rollout.journal_entry_count)
            .sum(),
        disposition_count: output
            .rollouts
            .iter()
            .map(|rollout| rollout.disposition_count)
            .sum(),
        tax_accrual_count: output
            .rollouts
            .iter()
            .map(|rollout| rollout.tax_accrual_count)
            .sum(),
        failure_count: output
            .rollouts
            .iter()
            .filter(|rollout| rollout.failed_month.is_some())
            .count() as u64,
        checksum: checksum(&output),
    };
    serde_json::to_writer(std::io::stdout().lock(), &report)?;
    println!();
    Ok(())
}

fn checksum(output: &PopulationOutput) -> u64 {
    let mut hash = 0xcbf2_9ce4_8422_2325_u64;
    for rollout in &output.rollouts {
        hash_u64(&mut hash, u64::from(rollout.rollout_id));
        hash_u64(&mut hash, rollout.failed_month.map_or(u64::MAX, u64::from));
        hash_u64(&mut hash, rollout.journal_entry_count);
        hash_u64(&mut hash, rollout.disposition_count);
        hash_u64(&mut hash, rollout.tax_accrual_count);
        for balance in &rollout.ending_balances {
            hash_bytes(&mut hash, balance.account.agent_id.as_bytes());
            hash_bytes(&mut hash, balance.account.account_id.as_bytes());
            hash_u64(&mut hash, balance.balance.0 as u64);
        }
    }
    hash
}

fn hash_u64(hash: &mut u64, value: u64) {
    hash_bytes(hash, &value.to_le_bytes());
}

fn hash_bytes(hash: &mut u64, bytes: &[u8]) {
    for byte in bytes {
        *hash ^= u64::from(*byte);
        *hash = hash.wrapping_mul(0x0000_0100_0000_01b3);
    }
}
