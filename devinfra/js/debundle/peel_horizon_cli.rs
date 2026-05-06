use std::process::ExitCode;

use clap::Parser;
use peel_horizon::{PeelHorizonOptions, analyze_peel_horizon, render_peel_horizon_report};

#[derive(Debug, Parser)]
#[command(
    name = "peel_horizon",
    about = "Rank tree-shaped module YAMLs against a debundle owner_graph.json peelability report."
)]
struct Args {
    #[arg(long = "graph")]
    owner_graph_path: std::path::PathBuf,
    #[arg(long = "modules")]
    modules_root: std::path::PathBuf,
    #[arg(long, default_value_t = 40)]
    limit: usize,
    #[arg(long, default_value_t = 2)]
    near_missing: usize,
    #[arg(long, default_value_t = 16)]
    max_companions: usize,
    #[arg(long)]
    json: bool,
}

fn main() -> ExitCode {
    match real_main() {
        Ok(()) => ExitCode::SUCCESS,
        Err(error) => {
            eprintln!("{error:#}");
            ExitCode::from(1)
        }
    }
}

fn real_main() -> anyhow::Result<()> {
    let args = Args::parse();
    let options = PeelHorizonOptions {
        owner_graph_path: args.owner_graph_path,
        modules_root: args.modules_root,
        near_missing: args.near_missing,
        max_companions: args.max_companions,
    };
    let report = analyze_peel_horizon(&options)?;
    if args.json {
        println!("{}", serde_json::to_string_pretty(&report)?);
    } else {
        print!(
            "{}",
            render_peel_horizon_report(&report, args.limit, args.max_companions, args.near_missing)
        );
    }
    Ok(())
}
