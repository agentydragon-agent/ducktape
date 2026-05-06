use std::env;
use std::path::PathBuf;
use std::process::ExitCode;

use clap::Parser;
use spec_tree::{CompileSpecTreeOptions, compile_spec_tree, write_compiled_spec};

#[derive(Debug, Parser)]
#[command(
    name = "compile_spec_tree",
    about = "Compile tree-shaped debundle YAML sources into one executable transform spec."
)]
struct Args {
    #[arg(long)]
    config: PathBuf,
    #[arg(long)]
    modules: PathBuf,
    #[arg(long = "vendor-marks")]
    vendor_marks: PathBuf,
    #[arg(long = "ancillary-modules")]
    ancillary_modules: Option<PathBuf>,
    #[arg(long)]
    out: PathBuf,
    #[arg(long = "out-root")]
    out_root: PathBuf,
    #[arg(long)]
    force: bool,
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
    let spec = compile_spec_tree(&CompileSpecTreeOptions {
        config_path: args.config,
        modules_root: args.modules,
        vendor_marks_path: args.vendor_marks,
        ancillary_modules_path: args.ancillary_modules,
        out_root: args.out_root,
        force: args.force,
    })?;
    write_compiled_spec(&spec, &resolve_output_path(args.out))
}

fn resolve_output_path(path: PathBuf) -> PathBuf {
    if path.is_absolute() {
        return path;
    }
    if let Ok(bazel_bindir) = env::var("BAZEL_BINDIR") {
        if path.components().next().and_then(|part| match part {
            std::path::Component::Normal(value) => value.to_str(),
            _ => None,
        }) != Some("bazel-out")
        {
            return env::current_dir()
                .unwrap_or_else(|_| PathBuf::from("."))
                .join(bazel_bindir)
                .join(path);
        }
    }
    let workspace_root = env::var("BUILD_WORKSPACE_DIRECTORY")
        .or_else(|_| env::var("BUILD_WORKING_DIRECTORY"))
        .map(PathBuf::from)
        .unwrap_or_else(|_| env::current_dir().unwrap_or_else(|_| PathBuf::from(".")));
    workspace_root.join(path)
}
