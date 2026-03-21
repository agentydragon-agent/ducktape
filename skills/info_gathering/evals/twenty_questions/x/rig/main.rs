//! Twenty Questions game implemented with Rig (Rust agent framework).

mod docker_exec;
mod game;

use clap::Parser;
use std::path::PathBuf;

#[derive(Parser)]
#[command(about = "Twenty Questions eval — Rig (Rust)")]
struct Args {
    #[arg(long)]
    variant: String,

    #[arg(long)]
    model: Option<String>,

    #[arg(long, default_value = "openai")]
    api: String,

    #[arg(long)]
    output_dir: Option<PathBuf>,
}

fn default_model(api: &str) -> String {
    match api {
        "anthropic" => "claude-haiku-4-5-20251001".to_string(),
        _ => "gpt-4o-mini".to_string(),
    }
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    env_logger::init();
    let args = Args::parse();

    let model = args.model.unwrap_or_else(|| default_model(&args.api));
    let variant = game::get_variant(&args.variant)?;
    let output_dir = args
        .output_dir
        .unwrap_or_else(|| PathBuf::from("eval_results"));

    let summary = game::run_game(&model, &args.api, &variant, &output_dir).await?;

    println!("{}", serde_json::to_string_pretty(&summary)?);
    Ok(())
}
