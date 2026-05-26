use anyhow::{Context, Result};
use clap::{Parser, Subcommand};
use module_cli::{ModuleArgs, run_module_cli};
use peel::{PeelArgs, run_peel};
use pipeline::{TransformArgs, run_transform_cli};

#[derive(Debug, Parser)]
#[command(
    name = "debundle",
    version,
    about = "Debundle JavaScript bundles and inspect peelable module work.",
    long_about = "Runs the debundle transform pipeline and exposes JSON peel-planning queries over generated owner graphs and spec modules."
)]
pub struct DebundleArgs {
    #[command(subcommand)]
    command: DebundleCommand,
}

#[derive(Debug, Subcommand)]
enum DebundleCommand {
    /// Run the debundle transform pipeline from a flat or tree-shaped spec.
    Run(TransformArgs),
    /// Inspect peel-planning evidence from an owner graph and spec modules tree.
    Peel(PeelArgs),
    /// Operate on debundle spec module YAML files (merge, etc.).
    Module(ModuleArgs),
}

pub fn run_debundle_cli(args: DebundleArgs) -> Result<()> {
    match args.command {
        DebundleCommand::Run(args) => {
            let cli = args.resolve()?;
            run_transform_cli(&cli)?;
            Ok(())
        }
        DebundleCommand::Peel(args) => run_peel(args).context("running peel query"),
        DebundleCommand::Module(args) => run_module_cli(args).context("running module subcommand"),
    }
}

#[cfg(test)]
mod tests {
    use std::path::PathBuf;

    use clap::Parser;
    use pipeline::{TransformArgs, TransformSpecSource};

    use super::DebundleArgs;

    fn parsed_run_args(argv: &[&str]) -> TransformArgs {
        let parsed = DebundleArgs::try_parse_from(argv).expect("parse cli");
        match parsed.command {
            super::DebundleCommand::Run(args) => args,
            other => panic!("expected run command, got {other:?}"),
        }
    }

    #[test]
    fn parse_run_args_matches_js_surface() {
        js_ast::with_swc_globals(|| {
            let args = parsed_run_args(&[
                "debundle",
                "run",
                "--spec",
                "spec.yaml",
                "--package-root",
                "pkg=/tmp/pkg",
                "--packages-root",
                "/tmp/packages",
            ]);
            let cli = args.resolve().expect("resolve cli");
            assert_eq!(
                cli.spec_source,
                TransformSpecSource::Flat {
                    path: PathBuf::from("spec.yaml")
                }
            );
            assert_eq!(
                cli.package_roots.get("pkg"),
                Some(&PathBuf::from("/tmp/pkg"))
            );
            assert_eq!(cli.packages_root, Some(PathBuf::from("/tmp/packages")));
        });
    }

    #[test]
    fn parse_tree_run_args() {
        js_ast::with_swc_globals(|| {
            let args = parsed_run_args(&[
                "debundle",
                "run",
                "--tree-config",
                "spec_config.yaml",
                "--tree-modules",
                "modules",
                "--tree-vendor-marks",
                "vendor_marks.yaml",
                "--tree-source-root",
                "/workspace",
                "--out-root",
                "out",
            ]);
            let cli = args.resolve().expect("resolve cli");
            assert_eq!(
                cli.spec_source,
                TransformSpecSource::Tree(spec_tree::CompileSpecTreeOptions {
                    config_path: PathBuf::from("spec_config.yaml"),
                    modules_root: PathBuf::from("modules"),
                    vendor_marks_path: PathBuf::from("vendor_marks.yaml"),
                    source_root: Some(PathBuf::from("/workspace")),
                    out_root: PathBuf::from("out"),
                })
            );
        });
    }

    #[test]
    fn parse_peel_units_command() {
        let parsed = DebundleArgs::try_parse_from([
            "debundle",
            "peel",
            "units",
            "--graph",
            "owner_graph.json",
            "--modules",
            "modules",
        ])
        .expect("parse cli");
        assert!(matches!(parsed.command, super::DebundleCommand::Peel(_)));
    }

    #[test]
    fn parse_module_merge_command() {
        let parsed = DebundleArgs::try_parse_from([
            "debundle",
            "module",
            "merge",
            "--modules",
            "modules",
            "--target",
            "ui/target.yaml",
            "ui/src1.yaml",
            "ui/src2.yaml",
        ])
        .expect("parse cli");
        assert!(matches!(parsed.command, super::DebundleCommand::Module(_)));
    }
}
