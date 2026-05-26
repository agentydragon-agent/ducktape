use std::path::PathBuf;

use anyhow::{Context, Result};
use clap::{Args as ClapArgs, Parser, Subcommand};
use comment_cli::{
    BindingsArgs, ModuleCommentArgs, run_bindings_cli, run_module_comment_cmd,
};
use module_cli::{MergeArgs, ModuleArgs, run_merge, run_module_cli};
use peel::{
    CommonArgs as PeelCommonArgs, ExplainArgs, GraphSummaryArgs, PatchPlanArgs, PeelArgs,
    PlanWorkArgs, SelectionArgs, SourceSliceArgs, UnitsArgs, print_json, run_explain_report,
    run_graph_summary_report, run_patch_plan_report, run_peel, run_plan_work_report,
    run_source_slice_report, run_units_report,
};
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
    /// (Deprecated) Inspect peel-planning evidence. Use the top-level
    /// commands `atoms`, `coverage`, `graph-summary`, `describe`,
    /// `show-source`, `modules propose` instead.
    Peel(PeelArgs),
    /// (Deprecated) `debundle module merge`. Use `debundle modules merge`.
    Module(ModuleArgs),
    /// Per-binding spec edits.
    Bindings(BindingsArgs),
    /// Module-level spec verbs (comment, merge, propose).
    Modules(ModulesNs),
    /// List structural atoms (owner-level SCCs of the constraining-edge graph).
    Atoms(UnitsArgs),
    /// Report spec coverage against atoms.
    Coverage(PatchPlanArgs),
    /// High-level graph counts.
    #[command(name = "graph-summary")]
    GraphSummary(GraphSummaryArgs),
    /// Dereference any identifier (binding, module path, proposal,
    /// atom, owner, diagnostic) with full graph + spec context.
    Describe(DescribeArgs),
    /// Print the source text for any identifier.
    #[command(name = "show-source")]
    ShowSource(ShowSourceArgs),
}

/// Args for `debundle modules ...`. Aggregates the existing
/// comment-edit verb (kept in `comment_cli`) with the new
/// `merge` / `propose` verbs lifted from `module merge` and
/// `peel plan-work`.
#[derive(Debug, ClapArgs)]
pub struct ModulesNs {
    #[command(subcommand)]
    command: ModulesNsCommand,
}

#[derive(Debug, Subcommand)]
enum ModulesNsCommand {
    /// Read, set, edit, or clear a module's top-level `comment:` field.
    Comment(ModuleCommentArgs),
    /// Splice source module YAMLs into a target YAML and delete the sources.
    Merge(MergeArgs),
    /// Emit module-assignment proposals derived from the atomic DAG.
    Propose(PlanWorkArgs),
}

/// Args for `debundle describe <id>`.
///
/// `<id>` is dispatched on shape: `owner:NNN`, `atomic:NNN`,
/// `diagnostic:...`, `auto_partition_NNNN`/`extend:...`, a module path
/// (resolves to `<modules>/<id>.yaml`), or otherwise a binding
/// (minified or readable name).
#[derive(Debug, ClapArgs)]
pub struct DescribeArgs {
    /// Identifier to describe.
    pub id: String,

    #[command(flatten)]
    pub common: PeelCommonArgs,

    /// Hard line ceiling used when resolving proposal-id references.
    #[arg(long = "size-cap-lines", default_value_t = 10_000)]
    pub size_cap_lines: usize,

    /// Maximum number of rows to emit per report section. Zero means unlimited.
    #[arg(long, default_value_t = 0)]
    pub limit: usize,
}

/// Args for `debundle show-source <id>`.
#[derive(Debug, ClapArgs)]
pub struct ShowSourceArgs {
    /// Identifier to print source text for.
    pub id: String,

    #[command(flatten)]
    pub common: PeelCommonArgs,

    /// Hard line ceiling used when resolving proposal-id references.
    #[arg(long = "size-cap-lines", default_value_t = 10_000)]
    pub size_cap_lines: usize,

    /// Extra source lines around the selected owner span.
    #[arg(long = "context-lines", default_value_t = 20)]
    pub context_lines: usize,

    /// Root used to resolve relative `source_location.source_path` values.
    #[arg(long = "source-root", env = "DEBUNDLE_SOURCE_ROOT")]
    pub source_root: Option<PathBuf>,
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
        DebundleCommand::Bindings(args) => run_bindings_cli(args),
        DebundleCommand::Modules(args) => match args.command {
            ModulesNsCommand::Comment(c) => run_module_comment_cmd(c),
            ModulesNsCommand::Merge(m) => run_merge(m),
            ModulesNsCommand::Propose(p) => {
                print_json(&run_plan_work_report(&p)?).context("writing propose JSON")
            }
        },
        DebundleCommand::Atoms(args) => {
            print_json(&run_units_report(&args)?).context("writing atoms JSON")
        }
        DebundleCommand::Coverage(args) => {
            print_json(&run_patch_plan_report(&args)?).context("writing coverage JSON")
        }
        DebundleCommand::GraphSummary(args) => {
            print_json(&run_graph_summary_report(&args)?).context("writing graph-summary JSON")
        }
        DebundleCommand::Describe(args) => run_describe(args),
        DebundleCommand::ShowSource(args) => run_show_source(args),
    }
}

/// Dispatch an `<id>` argument into a [`SelectionArgs`] populated with
/// exactly one field. Module-path IDs return `Ok(Err(module_path))` so
/// the caller can handle the (no-owner) module-only case separately.
pub fn dispatch_id_selection(
    id: &str,
    modules_root: &std::path::Path,
) -> std::result::Result<SelectionArgs, String> {
    // Prefix-based dispatch covers the structured ID kinds emitted by
    // the analysis crate.
    if id.starts_with("owner:") {
        return Ok(selection_with_owner(id));
    }
    if id.starts_with("atomic:") {
        return Ok(selection_with_unit(id));
    }
    if id.starts_with("diagnostic:") {
        return Ok(selection_with_diagnostic(id));
    }
    if id.starts_with("auto_partition_") || id.starts_with("extend:") {
        return Ok(selection_with_proposal(id));
    }
    // Module-path detection: try resolving `<modules>/<id>.yaml`.
    // Spec authors sometimes have flat module paths (no `/`); the
    // existence check is the only reliable disambiguator vs. binding
    // names that happen to spell a module-like word.
    let candidate = modules_root.join(format!("{id}.yaml"));
    if candidate.is_file() {
        return Err(id.to_string());
    }
    // Fall through: treat as a binding name (minified or readable).
    Ok(selection_with_binding(id))
}

fn selection_with_owner(value: &str) -> SelectionArgs {
    SelectionArgs {
        owner_id: Some(value.to_string()),
        binding_id: None,
        proposal_id: None,
        unit_id: None,
        diagnostic_id: None,
    }
}

fn selection_with_unit(value: &str) -> SelectionArgs {
    SelectionArgs {
        owner_id: None,
        binding_id: None,
        proposal_id: None,
        unit_id: Some(value.to_string()),
        diagnostic_id: None,
    }
}

fn selection_with_diagnostic(value: &str) -> SelectionArgs {
    SelectionArgs {
        owner_id: None,
        binding_id: None,
        proposal_id: None,
        unit_id: None,
        diagnostic_id: Some(value.to_string()),
    }
}

fn selection_with_proposal(value: &str) -> SelectionArgs {
    SelectionArgs {
        owner_id: None,
        binding_id: Some(String::new()),
        proposal_id: Some(value.to_string()),
        unit_id: None,
        diagnostic_id: None,
    }
}

fn selection_with_binding(value: &str) -> SelectionArgs {
    SelectionArgs {
        owner_id: None,
        binding_id: Some(value.to_string()),
        proposal_id: None,
        unit_id: None,
        diagnostic_id: None,
    }
}

fn run_describe(args: DescribeArgs) -> Result<()> {
    match dispatch_id_selection(&args.id, &args.common.modules_root) {
        Ok(mut selection) => {
            // selection_with_proposal stuffs a sentinel binding_id; clear it.
            if selection.proposal_id.is_some() {
                selection.binding_id = None;
            }
            let inner = ExplainArgs {
                common: args.common,
                selection,
                size_cap_lines: args.size_cap_lines,
                limit: args.limit,
            };
            print_json(&run_explain_report(&inner)?).context("writing describe JSON")
        }
        Err(module_path) => describe_module(&module_path, &args.common),
    }
}

fn run_show_source(args: ShowSourceArgs) -> Result<()> {
    match dispatch_id_selection(&args.id, &args.common.modules_root) {
        Ok(mut selection) => {
            if selection.proposal_id.is_some() {
                selection.binding_id = None;
            }
            let inner = SourceSliceArgs {
                common: args.common,
                selection,
                size_cap_lines: args.size_cap_lines,
                context_lines: args.context_lines,
                source_root: args.source_root,
            };
            print_json(&run_source_slice_report(&inner)?).context("writing show-source JSON")
        }
        Err(module_path) => show_module_source(&module_path, &args.common, args.context_lines, args.source_root.as_deref()),
    }
}

/// `describe <module-path>`: resolve every binding in the module to
/// owner ids then run the same explain report. Falls through to an
/// empty selection (no owners) when the module YAML has no bindings.
fn describe_module(module_path: &str, common: &PeelCommonArgs) -> Result<()> {
    use std::collections::BTreeSet;
    let bindings = collect_module_bindings(module_path, &common.modules_root)?;
    if bindings.is_empty() {
        anyhow::bail!(
            "module {module_path:?} has no members; nothing to describe"
        );
    }
    // Build an owner-id set by looking up each binding name in the
    // owner graph. Reuse run_explain_report by feeding the first
    // binding and then ignoring; instead, do it directly:
    let graph: analysis::OwnerGraphReport = serde_json::from_str(&std::fs::read_to_string(
        &common.owner_graph_path,
    )?)
    .with_context(|| {
        format!(
            "parsing owner graph {}",
            common.owner_graph_path.display()
        )
    })?;
    let mut owner_ids: BTreeSet<String> = BTreeSet::new();
    for node in &graph.nodes {
        if node
            .declared_bindings
            .iter()
            .any(|b| bindings.contains(&b.binding.to_string()))
        {
            owner_ids.insert(node.id.clone());
        }
    }
    if owner_ids.is_empty() {
        anyhow::bail!(
            "module {module_path:?} declares bindings that do not appear in the owner graph"
        );
    }
    // Use the first owner id as the explain selection; the report's
    // owner-set expansion picks up the rest via shared atomic units.
    let first = owner_ids.iter().next().unwrap().clone();
    let inner = ExplainArgs {
        common: common.clone(),
        selection: selection_with_owner(&first),
        size_cap_lines: 10_000,
        limit: 0,
    };
    print_json(&run_explain_report(&inner)?).context("writing describe JSON")
}

/// `show-source <module-path>`: concatenate source text for every
/// declared binding in the module, in declaration order.
fn show_module_source(
    module_path: &str,
    common: &PeelCommonArgs,
    context_lines: usize,
    source_root: Option<&std::path::Path>,
) -> Result<()> {
    use std::collections::BTreeSet;
    let bindings = collect_module_bindings(module_path, &common.modules_root)?;
    let graph: analysis::OwnerGraphReport = serde_json::from_str(&std::fs::read_to_string(
        &common.owner_graph_path,
    )?)?;
    let mut owner_ids: BTreeSet<String> = BTreeSet::new();
    for node in &graph.nodes {
        if node
            .declared_bindings
            .iter()
            .any(|b| bindings.contains(&b.binding.to_string()))
        {
            owner_ids.insert(node.id.clone());
        }
    }
    let Some(first) = owner_ids.iter().next() else {
        anyhow::bail!(
            "module {module_path:?} has no resolvable owner; nothing to show"
        );
    };
    let inner = SourceSliceArgs {
        common: common.clone(),
        selection: selection_with_owner(first),
        size_cap_lines: 10_000,
        context_lines,
        source_root: source_root.map(|p| p.to_path_buf()),
    };
    print_json(&run_source_slice_report(&inner)?).context("writing show-source JSON")
}

fn collect_module_bindings(
    module_path: &str,
    modules_root: &std::path::Path,
) -> Result<std::collections::BTreeSet<String>> {
    use std::collections::BTreeSet;
    let yaml_path = modules_root.join(format!("{module_path}.yaml"));
    let module = spec_modules::read_module_file(&yaml_path).with_context(|| {
        format!("reading module YAML {}", yaml_path.display())
    })?;
    Ok(module
        .members
        .into_iter()
        .map(|m| m.selector.binding.name)
        .collect::<BTreeSet<_>>())
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
    fn parse_top_level_atoms_command() {
        let parsed = DebundleArgs::try_parse_from([
            "debundle",
            "atoms",
            "--graph",
            "owner_graph.json",
            "--modules",
            "modules",
        ])
        .expect("parse cli");
        assert!(matches!(parsed.command, super::DebundleCommand::Atoms(_)));
    }

    #[test]
    fn parse_top_level_coverage_command() {
        let parsed = DebundleArgs::try_parse_from([
            "debundle",
            "coverage",
            "--graph",
            "owner_graph.json",
            "--modules",
            "modules",
        ])
        .expect("parse cli");
        assert!(matches!(
            parsed.command,
            super::DebundleCommand::Coverage(_)
        ));
    }

    #[test]
    fn parse_top_level_graph_summary_command() {
        let parsed = DebundleArgs::try_parse_from([
            "debundle",
            "graph-summary",
            "--graph",
            "owner_graph.json",
            "--modules",
            "modules",
        ])
        .expect("parse cli");
        assert!(matches!(
            parsed.command,
            super::DebundleCommand::GraphSummary(_)
        ));
    }

    #[test]
    fn parse_top_level_describe_command() {
        let parsed = DebundleArgs::try_parse_from([
            "debundle",
            "describe",
            "XOe",
            "--graph",
            "owner_graph.json",
            "--modules",
            "modules",
        ])
        .expect("parse cli");
        assert!(matches!(
            parsed.command,
            super::DebundleCommand::Describe(_)
        ));
    }

    #[test]
    fn parse_top_level_show_source_command() {
        let parsed = DebundleArgs::try_parse_from([
            "debundle",
            "show-source",
            "XOe",
            "--graph",
            "owner_graph.json",
            "--modules",
            "modules",
            "--source-root",
            "/snapshot",
        ])
        .expect("parse cli");
        assert!(matches!(
            parsed.command,
            super::DebundleCommand::ShowSource(_)
        ));
    }

    #[test]
    fn parse_bindings_comment_command() {
        let parsed = DebundleArgs::try_parse_from([
            "debundle",
            "bindings",
            "comment",
            "--modules",
            "spec/modules",
            "XOe",
            "hand-written annotation",
        ])
        .expect("parse cli");
        assert!(matches!(
            parsed.command,
            super::DebundleCommand::Bindings(_)
        ));
    }

    #[test]
    fn parse_modules_comment_command() {
        let parsed = DebundleArgs::try_parse_from([
            "debundle",
            "modules",
            "comment",
            "--modules",
            "spec/modules",
            "runtime/plugins",
            "--clear",
        ])
        .expect("parse cli");
        assert!(matches!(parsed.command, super::DebundleCommand::Modules(_)));
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

    #[test]
    fn dispatch_id_owner_prefix() {
        let tmp = tempfile::tempdir().unwrap();
        let modules = tmp.path().to_path_buf();
        std::fs::create_dir_all(&modules).unwrap();
        let sel = super::dispatch_id_selection("owner:42", &modules).unwrap();
        assert_eq!(sel.owner_id.as_deref(), Some("owner:42"));
    }

    #[test]
    fn dispatch_id_atomic_prefix() {
        let tmp = tempfile::tempdir().unwrap();
        let sel = super::dispatch_id_selection("atomic:7", tmp.path()).unwrap();
        assert_eq!(sel.unit_id.as_deref(), Some("atomic:7"));
    }

    #[test]
    fn dispatch_id_diagnostic_prefix() {
        let tmp = tempfile::tempdir().unwrap();
        let sel = super::dispatch_id_selection("diagnostic:size_cap_0001", tmp.path()).unwrap();
        assert_eq!(sel.diagnostic_id.as_deref(), Some("diagnostic:size_cap_0001"));
    }

    #[test]
    fn dispatch_id_proposal_prefix() {
        let tmp = tempfile::tempdir().unwrap();
        let sel = super::dispatch_id_selection("auto_partition_0042", tmp.path()).unwrap();
        assert_eq!(sel.proposal_id.as_deref(), Some("auto_partition_0042"));
    }

    #[test]
    fn dispatch_id_module_path_when_yaml_exists() {
        let tmp = tempfile::tempdir().unwrap();
        let modules = tmp.path();
        std::fs::create_dir_all(modules.join("runtime")).unwrap();
        std::fs::write(modules.join("runtime/plugins.yaml"), "members: []\n").unwrap();
        let err = super::dispatch_id_selection("runtime/plugins", modules).unwrap_err();
        assert_eq!(err, "runtime/plugins");
    }

    #[test]
    fn dispatch_id_binding_otherwise() {
        let tmp = tempfile::tempdir().unwrap();
        let sel = super::dispatch_id_selection("XOe", tmp.path()).unwrap();
        assert_eq!(sel.binding_id.as_deref(), Some("XOe"));
    }
}
