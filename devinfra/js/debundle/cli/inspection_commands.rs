//! Graph/source inspection commands and their ID resolution and rendering.
use std::path::PathBuf;
use anyhow::{Context, Result};
use clap::Args as ClapArgs;
use peel::factorize::DEFAULT_SIZE_CAP_LINES;
use peel::{CommonArgs as PeelCommonArgs, ExplainArgs, GraphSummaryArgs, OutputFormat,
    PatchPlanArgs, SelectionKind, SourceSliceArgs, UnitsArgs, run_explain_report,
    run_graph_summary_report, run_patch_plan_report, run_source_slice_report, run_units_report};
use spec_modules::{collect_module_files, module_path_from_file};
use crate::emit_report;

/// Args for `debundle describe <id>`.
///
/// `<id>` is dispatched on shape: `owner:NNN`, `atomic:NNN`,
/// `diagnostic:...`, `auto_partition_NNNN`/`extend:...`, a module path
/// (resolves to `<modules>/<id>.yaml`), or otherwise a binding
/// (minified or readable name).
#[derive(Debug, ClapArgs)]
pub(super) struct DescribeArgs {
    /// Identifier to describe.
    pub id: String,

    #[command(flatten)]
    pub common: PeelCommonArgs,

    /// Hard line ceiling used when resolving proposal-id references.
    #[arg(long = "size-cap-lines", default_value_t = DEFAULT_SIZE_CAP_LINES)]
    pub size_cap_lines: usize,

    /// Maximum number of rows to emit per report section. Zero means unlimited.
    #[arg(long, default_value_t = 0)]
    pub limit: usize,

    /// Also run the proposal factorizer to annotate matching proposals and
    /// diagnostics. This is intentionally opt-in because it is expensive on
    /// large graphs.
    #[arg(long = "include-proposals")]
    pub include_proposals: bool,

    /// Root used to resolve relative `source_location.source_path` values.
    #[arg(long = "source-root", env = "DEBUNDLE_SOURCE_ROOT")]
    pub source_root: Option<PathBuf>,

    /// Output format. Default `text` on tty, `json` on pipe.
    #[arg(long, value_enum)]
    pub format: Option<OutputFormat>,
}

/// Args for `debundle show-source <id>`.
#[derive(Debug, ClapArgs)]
pub(super) struct ShowSourceArgs {
    /// Identifier to print source text for.
    pub id: String,

    #[command(flatten)]
    pub common: PeelCommonArgs,

    /// Hard line ceiling used when resolving proposal-id references.
    #[arg(long = "size-cap-lines", default_value_t = DEFAULT_SIZE_CAP_LINES)]
    pub size_cap_lines: usize,

    /// Extra source lines around the selected owner span.
    #[arg(long = "context-lines", default_value_t = 20)]
    pub context_lines: usize,

    /// Root used to resolve relative `source_location.source_path` values.
    #[arg(long = "source-root", env = "DEBUNDLE_SOURCE_ROOT")]
    pub source_root: Option<PathBuf>,

    /// Output format. Default `text` on tty, `json` on pipe.
    #[arg(long, value_enum)]
    pub format: Option<OutputFormat>,
}

/// Dispatch an `<id>` argument into the [`SelectionKind`] it names. Module
/// paths and logical module ids resolve through the same owner-graph/spec
/// claim path as other structured IDs, so binding members and anonymous
/// statements stay in sync.
fn dispatch_id_selection(id: &str, modules_root: &std::path::Path) -> Result<SelectionKind> {
    // Prefix-based dispatch covers the structured ID kinds emitted by
    // the analysis crate.
    if id.starts_with("owner:") {
        return Ok(SelectionKind::Owner(id.to_string()));
    }
    if id.starts_with("logical:") {
        return Ok(SelectionKind::Module(id.to_string()));
    }
    if id.starts_with("atomic:") {
        return Ok(SelectionKind::Unit(id.to_string()));
    }
    if id.starts_with("diagnostic:") {
        return Ok(SelectionKind::Diagnostic(id.to_string()));
    }
    // Module-path detection: try resolving `<modules>/<id>.yaml`.
    // Spec authors sometimes have flat module paths (no `/`); the
    // existence check is the only reliable disambiguator vs. binding
    // names that happen to spell a module-like word.
    if let Some(module_path) = resolve_id_as_module_path(id, modules_root)? {
        return Ok(SelectionKind::ModulePath(module_path));
    }
    if id.starts_with("auto_partition_") || id.starts_with("extend:") {
        return Ok(SelectionKind::Proposal(id.to_string()));
    }
    // Fall through: treat as a binding name (minified or readable).
    Ok(SelectionKind::Binding(id.to_string()))
}

fn resolve_id_as_module_path(id: &str, modules_root: &std::path::Path) -> Result<Option<String>> {
    let module_id = id.strip_suffix(".yaml").unwrap_or(id);
    let candidate = modules_root.join(format!("{module_id}.yaml"));
    if candidate.is_file() {
        return Ok(Some(module_id.to_string()));
    }
    if module_id.contains('/') {
        return Ok(None);
    }

    let filename = format!("{module_id}.yaml");
    let mut matches = collect_module_files(modules_root)
        .with_context(|| format!("walking modules tree {}", modules_root.display()))?
        .into_iter()
        .filter(|path| {
            path.file_name()
                .is_some_and(|name| name == filename.as_str())
        })
        .map(|path| module_path_from_file(&path, modules_root));
    let Some(first) = matches.next() else {
        return Ok(None);
    };
    if matches.next().is_some() {
        return Ok(None);
    }
    Ok(Some(first))
}

pub(super) fn run_describe(args: DescribeArgs) -> Result<()> {
    let selection = dispatch_id_selection(&args.id, &args.common.modules_root)?;
    let inner = ExplainArgs {
        common: args.common,
        selection,
        size_cap_lines: args.size_cap_lines,
        source_root: args.source_root,
        limit: args.limit,
        include_proposals: args.include_proposals,
    };
    let report = run_explain_report(&inner)?;
    emit_report(
        args.format,
        &report,
        render_explain_text,
        "writing describe output",
    )
}

pub(super) fn run_show_source(args: ShowSourceArgs) -> Result<()> {
    let selection = dispatch_id_selection(&args.id, &args.common.modules_root)?;
    let inner = SourceSliceArgs {
        common: args.common,
        selection,
        size_cap_lines: args.size_cap_lines,
        context_lines: args.context_lines,
        source_root: args.source_root,
    };
    let report = run_source_slice_report(&inner)?;
    emit_report(
        args.format,
        &report,
        render_source_slice_text,
        "writing show-source output",
    )
}

fn render_units_text(report: &peel::UnitsReport, out: &mut String) {
    out.push_str(&format!("{} atom(s)\n", report.units.len()));
    for unit in &report.units {
        let bindings: Vec<&str> = unit.members.iter().map(|m| m.binding.as_str()).collect();
        out.push_str(&format!(
            "  {}  [{}]  size={}\n",
            unit.id,
            bindings.join(", "),
            unit.size_lines_estimate
        ));
    }
}

fn render_patch_plan_text(report: &peel::PatchPlanReport, out: &mut String) {
    out.push_str(&format!(
        "{} patch set(s): {} complete, {} split, {} unknown bindings\n",
        report.summary.total_patch_sets,
        report.summary.complete_patch_sets,
        report.summary.split_patch_sets,
        report.summary.unknown_binding_count,
    ));
    for row in &report.rows {
        out.push_str(&format!("  {} [{:?}]\n", row.path, row.status));
    }
}

fn render_graph_summary_text(report: &peel::GraphSummaryReport, out: &mut String) {
    let proposal_count = report
        .proposal_count
        .map(|count| count.to_string())
        .unwrap_or_else(|| "skipped".to_string());
    let diagnostic_count = report
        .diagnostic_count
        .map(|count| count.to_string())
        .unwrap_or_else(|| "skipped".to_string());
    out.push_str(&format!(
        "owners={} edges={} atoms={} residual={} proposals={} diagnostics={}\n",
        report.owner_count,
        report.owner_edge_count,
        report.atomic_unit_count,
        report.residual_atomic_unit_count,
        proposal_count,
        diagnostic_count,
    ));
}

fn render_explain_text(report: &peel::ExplainReport, out: &mut String) {
    out.push_str(&format!(
        "{:?} {:?}\n",
        report.query.kind, report.query.value
    ));
    out.push_str(&format!("  owners: {}\n", report.owner_ids.join(", ")));
    out.push_str(&format!(
        "  bindings: {}\n",
        report
            .bindings
            .iter()
            .map(|b| b.binding.as_str())
            .collect::<Vec<_>>()
            .join(", ")
    ));
    // Home module path per binding (CLI_DOGFOOD #6): the JSON carries
    // `binding_homes[].path`, but the text view previously dropped it,
    // leaving no way to see where a binding lives without `--format json`.
    if !report.binding_homes.is_empty() {
        out.push_str("  homes:\n");
        for home in &report.binding_homes {
            out.push_str(&format!("    {} -> {}\n", home.binding, home.path));
        }
    }
    if !report.unknown_binding_ids.is_empty() {
        out.push_str(&format!(
            "  unknown bindings (claimed but absent from owner graph): {}\n",
            report.unknown_binding_ids.join(", ")
        ));
    }
    out.push_str(&format!("  atomic_units: {}\n", report.atomic_units.len()));
    out.push_str(&format!(
        "  incoming_edges: {}, outgoing_edges: {}\n",
        report.incoming_edges.len(),
        report.outgoing_edges.len()
    ));
}

fn render_source_slice_text(report: &peel::SourceSliceReport, out: &mut String) {
    for slice in &report.slices {
        out.push_str(&format!(
            "--- {} (lines {}-{}) ---\n",
            slice.source_path, slice.context_start_line, slice.context_end_line
        ));
        out.push_str(&slice.text);
        if !slice.text.ends_with('\n') {
            out.push('\n');
        }
    }
}

pub(super) fn run_atoms(args: UnitsArgs) -> Result<()> {
            let report = run_units_report(&args)?;
            emit_report(
                args.format,
                &report,
                render_units_text,
                "writing atoms output",
            )
}

pub(super) fn run_coverage(args: PatchPlanArgs) -> Result<()> {
            let report = run_patch_plan_report(&args)?;
            emit_report(
                args.format,
                &report,
                render_patch_plan_text,
                "writing coverage output",
            )
}

pub(super) fn run_graph_summary(args: GraphSummaryArgs) -> Result<()> {
            let report = run_graph_summary_report(&args)?;
            emit_report(
                args.format,
                &report,
                render_graph_summary_text,
                "writing graph-summary output",
            )
}

#[cfg(test)]
mod tests {
    use std::fs;
    use std::path::Path;
    use peel::SelectionKind;
    use tempfile::TempDir;

    fn write(root: &Path, rel: &str, body: &str) {
        let path = root.join(rel);
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent).unwrap();
        }
        fs::write(path, body).unwrap();
    }

    #[test]
    fn render_explain_text_includes_home_module_paths() {
        // CLI_DOGFOOD #6: the text view must surface each binding's home
        // module path (the JSON's `binding_homes[].path`), not only owners
        // / bindings / atom / edge counts.
        use peel::plan::{BindingHomeReport, BindingHomeSourceKind, QueryKind, QueryReport};
        let report = peel::ExplainReport {
            query: QueryReport {
                kind: QueryKind::Binding,
                value: "XOe".to_string(),
            },
            owner_ids: vec!["owner:0".to_string()],
            owners: vec![],
            neighbor_owners: vec![],
            bindings: vec![],
            binding_homes: vec![BindingHomeReport {
                binding: "XOe".to_string(),
                name: "PluginSettingsAccessor".to_string(),
                source_kind: BindingHomeSourceKind::Module,
                path: "runtime/plugins".to_string(),
            }],
            incoming_edges: vec![],
            outgoing_edges: vec![],
            atomic_units: vec![],
            incoming_atomic_edges: vec![],
            outgoing_atomic_edges: vec![],
            quotient_edges: vec![],
            unknown_binding_ids: vec![],
            factorize_proposals: None,
            factorize_diagnostics: None,
            limits: None,
        };
        let mut out = String::new();
        super::render_explain_text(&report, &mut out);
        assert!(out.contains("homes:"), "missing homes section:\n{out}");
        assert!(
            out.contains("XOe -> runtime/plugins"),
            "missing binding->path line:\n{out}",
        );
    }

    #[test]
    fn dispatch_id_selection_resolves_unique_module_basename_before_proposal_id() {
        let dir = TempDir::new().unwrap();
        let modules_root = dir.path().join("modules");
        write(
            &modules_root,
            "auto_partition/auto_partition_0499.yaml",
            "members: []\n",
        );

        let selection = super::dispatch_id_selection("auto_partition_0499", &modules_root).unwrap();

        assert_eq!(
            selection,
            SelectionKind::ModulePath("auto_partition/auto_partition_0499".to_string())
        );
    }

    #[test]
    fn dispatch_id_owner_prefix() {
        let tmp = tempfile::tempdir().unwrap();
        let modules = tmp.path().to_path_buf();
        std::fs::create_dir_all(&modules).unwrap();
        let sel = super::dispatch_id_selection("owner:42", &modules).unwrap();
        assert_eq!(sel, SelectionKind::Owner("owner:42".to_string()));
    }

    #[test]
    fn dispatch_id_logical_prefix() {
        let tmp = tempfile::tempdir().unwrap();
        let sel = super::dispatch_id_selection("logical:7", tmp.path()).unwrap();
        assert_eq!(sel, SelectionKind::Module("logical:7".to_string()));
    }

    #[test]
    fn dispatch_id_atomic_prefix() {
        let tmp = tempfile::tempdir().unwrap();
        let sel = super::dispatch_id_selection("atomic:7", tmp.path()).unwrap();
        assert_eq!(sel, SelectionKind::Unit("atomic:7".to_string()));
    }

    #[test]
    fn dispatch_id_diagnostic_prefix() {
        let tmp = tempfile::tempdir().unwrap();
        let sel = super::dispatch_id_selection("diagnostic:size_cap_0001", tmp.path()).unwrap();
        assert_eq!(
            sel,
            SelectionKind::Diagnostic("diagnostic:size_cap_0001".to_string())
        );
    }

    #[test]
    fn dispatch_id_proposal_prefix() {
        let tmp = tempfile::tempdir().unwrap();
        let sel = super::dispatch_id_selection("auto_partition_0042", tmp.path()).unwrap();
        assert_eq!(
            sel,
            SelectionKind::Proposal("auto_partition_0042".to_string())
        );
    }

    #[test]
    fn dispatch_id_module_path_when_yaml_exists() {
        let tmp = tempfile::tempdir().unwrap();
        let modules = tmp.path();
        std::fs::create_dir_all(modules.join("runtime")).unwrap();
        std::fs::write(modules.join("runtime/plugins.yaml"), "members: []\n").unwrap();
        let sel = super::dispatch_id_selection("runtime/plugins", modules).unwrap();
        assert_eq!(
            sel,
            SelectionKind::ModulePath("runtime/plugins".to_string())
        );
    }

    #[test]
    fn dispatch_id_binding_otherwise() {
        let tmp = tempfile::tempdir().unwrap();
        let sel = super::dispatch_id_selection("XOe", tmp.path()).unwrap();
        assert_eq!(sel, SelectionKind::Binding("XOe".to_string()));
    }}
