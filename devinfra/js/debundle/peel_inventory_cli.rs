use std::process::ExitCode;

use clap::Parser;
use peel_inventory::{InventoryView, PeelInventoryOptions, build_inventory, render_inventory};

#[derive(Debug, Parser)]
#[command(
    name = "peel_inventory",
    about = "Emit a parseable inventory of peelable bindings from a debundle owner_graph.json."
)]
struct Args {
    /// Path to `owner_graph.json` (debundler analysis output).
    #[arg(long = "graph")]
    owner_graph_path: std::path::PathBuf,
    /// Root of `*.yaml` / `*.yaml.deferred` spec files.
    #[arg(long = "modules")]
    modules_root: std::path::PathBuf,
    /// Filter to candidates with at least one renamed (readable) export.
    #[arg(long = "readable-only")]
    readable_only: bool,
    #[arg(long, default_value_t = 200)]
    limit: usize,
    /// Group output by `proposed_dir` (descending by candidate count).
    #[arg(long = "by-destination")]
    by_destination: bool,
    /// Emit JSON instead of human-readable output.
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
    let options = PeelInventoryOptions {
        owner_graph_path: args.owner_graph_path,
        modules_root: args.modules_root,
    };
    let mut inventory = build_inventory(&options)?;
    if args.readable_only {
        inventory.retain(|record| record.has_readable);
    }

    let view = if args.json {
        InventoryView::Json
    } else if args.by_destination {
        InventoryView::ByDestination { limit: args.limit }
    } else {
        InventoryView::Flat { limit: args.limit }
    };

    print!("{}", render_inventory(&inventory, view));
    if args.json {
        println!();
    }
    Ok(())
}
