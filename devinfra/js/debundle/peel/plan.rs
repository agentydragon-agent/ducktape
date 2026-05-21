//! Agent-facing read-only peel-planning workbench.
//!
//! These subcommands are for agents maintaining a debundle spec. They expose
//! stable JSON operations over the owner graph and spec tree instead of
//! human-oriented "views".

use std::collections::{BTreeMap, BTreeSet};
use std::env;
use std::fs;
use std::path::{Path, PathBuf};

use super::factorize::{FactorizeDiagnosticReport, FactorizeProposal, PeelFactorizeOptions};
use super::factorize::{PeelFactorizeReport, analyze_peel_factorize};
use anyhow::{Context, Result, bail};
use clap::{Args as ClapArgs, Subcommand};
use serde::Serialize;

use analysis::{
    AtomicUnitEdgeReport, AtomicUnitReport, BindingReport, OwnerGraphEdgeReport,
    OwnerGraphNodeReport, OwnerGraphReport, QuotientEdgeReport, SourceLocation,
};
use spec_modules::{
    collect_module_files, default_binding_patches_path, load_binding_patch_members,
    module_path_from_file, read_module_file,
};

#[derive(Debug, ClapArgs)]
pub struct PeelArgs {
    #[command(subcommand)]
    command: PeelCommand,
}

#[derive(Debug, Subcommand)]
enum PeelCommand {
    /// Emit module-assignment proposals and diagnostics derived from the atomic DAG.
    #[command(name = "plan-work")]
    PlanWork(PlanWorkArgs),
    /// List atomic units from the emitted graph.
    Units(UnitsArgs),
    /// Report binding/module patch coverage against atomic units.
    #[command(name = "patch-plan")]
    PatchPlan(PatchPlanArgs),
    /// Explain one owner, binding, proposal, unit, or diagnostic with graph/spec context.
    Explain(ExplainArgs),
    /// Print source text for one owner, binding, proposal, unit, or diagnostic.
    #[command(name = "source-slice")]
    SourceSlice(SourceSliceArgs),
    /// Summarize current atomic graph and recommendation counts.
    #[command(name = "graph-summary")]
    GraphSummary(GraphSummaryArgs),
}

#[derive(Debug, Clone, ClapArgs)]
struct CommonArgs {
    /// Path to `owner_graph.json` (debundler analysis output).
    #[arg(long = "graph")]
    owner_graph_path: PathBuf,

    /// Root of emitted-module `*.yaml` spec files.
    #[arg(long = "modules")]
    modules_root: PathBuf,
}

#[derive(Debug, Clone, ClapArgs)]
struct PlanWorkArgs {
    #[command(flatten)]
    common: CommonArgs,

    /// Hard line ceiling per emitted proposal.
    #[arg(long = "size-cap-lines", default_value_t = 10_000)]
    size_cap_lines: usize,

    /// Maximum number of proposals and diagnostics to emit. Zero means unlimited.
    #[arg(long, default_value_t = 0)]
    limit: usize,
}

#[derive(Debug, Clone, ClapArgs)]
struct UnitsArgs {
    #[command(flatten)]
    common: CommonArgs,

    /// Maximum number of units to emit. Zero means unlimited.
    #[arg(long, default_value_t = 0)]
    limit: usize,

    /// Filter to units containing at least one residual owner.
    #[arg(long = "residual-only")]
    residual_only: bool,

    /// Filter to units with at least one renamed export.
    #[arg(long = "readable-only")]
    readable_only: bool,

    /// Also group emitted units by current destination.
    #[arg(long = "by-destination")]
    by_destination: bool,
}

#[derive(Debug, Clone, ClapArgs)]
struct PatchPlanArgs {
    #[command(flatten)]
    common: CommonArgs,

    /// Maximum number of rows to keep. Zero means unlimited.
    #[arg(long, default_value_t = 0)]
    limit: usize,
}

#[derive(Debug, Clone, ClapArgs)]
struct GraphSummaryArgs {
    #[command(flatten)]
    common: CommonArgs,

    /// Hard line ceiling per emitted proposal.
    #[arg(long = "size-cap-lines", default_value_t = 10_000)]
    size_cap_lines: usize,

    /// Maximum number of largest residual units to emit. Zero means unlimited.
    #[arg(long, default_value_t = 10)]
    limit: usize,
}

#[derive(Debug, Clone, ClapArgs)]
struct ExplainArgs {
    #[command(flatten)]
    common: CommonArgs,

    #[command(flatten)]
    selection: SelectionArgs,

    /// Hard line ceiling used when resolving `--proposal-id`.
    #[arg(long = "size-cap-lines", default_value_t = 10_000)]
    size_cap_lines: usize,

    /// Maximum number of rows to emit per report section. Zero means unlimited.
    #[arg(long, default_value_t = 0)]
    limit: usize,
}

#[derive(Debug, Clone, ClapArgs)]
struct SourceSliceArgs {
    #[command(flatten)]
    common: CommonArgs,

    #[command(flatten)]
    selection: SelectionArgs,

    /// Hard line ceiling used when resolving `--proposal-id`.
    #[arg(long = "size-cap-lines", default_value_t = 10_000)]
    size_cap_lines: usize,

    /// Extra source lines to include around the selected owner span.
    #[arg(long = "context-lines", default_value_t = 20)]
    context_lines: usize,

    /// Root used to resolve relative `source_location.source_path` values.
    #[arg(long = "source-root")]
    source_root: Option<PathBuf>,
}

#[derive(Debug, Clone, ClapArgs)]
struct SelectionArgs {
    /// Select one owner id from `owner_graph.json`.
    #[arg(long = "owner-id")]
    owner_id: Option<String>,

    /// Select the owner that declares this input binding id.
    #[arg(long = "binding-id")]
    binding_id: Option<String>,

    /// Select a factorizer proposal by `proposed_module_id`.
    #[arg(long = "proposal-id")]
    proposal_id: Option<String>,

    /// Select one atomic unit id from `owner_graph.json`.
    #[arg(long = "unit-id")]
    unit_id: Option<String>,

    /// Select one factorizer diagnostic by `diagnostic_id`.
    #[arg(long = "diagnostic-id")]
    diagnostic_id: Option<String>,
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
struct QueryReport {
    kind: QueryKind,
    value: String,
}

#[derive(Debug, Clone, Copy, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
enum QueryKind {
    Owner,
    Binding,
    Proposal,
    Unit,
    Diagnostic,
}

#[derive(Debug, Clone)]
enum SelectionKind {
    Owner(String),
    Binding(String),
    Proposal(String),
    Unit(String),
    Diagnostic(String),
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
struct UnitsReport {
    units: Vec<AtomicUnitReport>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    groups: Vec<UnitGroup>,
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
struct UnitGroup {
    destination: String,
    unit_ids: Vec<String>,
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
struct PlanWorkReport {
    #[serde(flatten)]
    report: PeelFactorizeReport,
    #[serde(skip_serializing_if = "Option::is_none")]
    limits: Option<LimitReport>,
}

#[derive(Debug, Clone, Serialize)]
struct ExplainReport {
    query: QueryReport,
    owner_ids: Vec<String>,
    owners: Vec<OwnerGraphNodeReport>,
    neighbor_owners: Vec<OwnerGraphNodeReport>,
    bindings: Vec<BindingReport>,
    binding_homes: Vec<BindingHomeReport>,
    incoming_edges: Vec<OwnerGraphEdgeReport>,
    outgoing_edges: Vec<OwnerGraphEdgeReport>,
    atomic_units: Vec<AtomicUnitReport>,
    incoming_atomic_edges: Vec<AtomicUnitEdgeReport>,
    outgoing_atomic_edges: Vec<AtomicUnitEdgeReport>,
    quotient_edges: Vec<QuotientEdgeReport>,
    factorize_proposals: Vec<FactorizeProposal>,
    factorize_diagnostics: Vec<FactorizeDiagnosticReport>,
    #[serde(skip_serializing_if = "Option::is_none")]
    limits: Option<LimitReport>,
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
struct PatchPlanReport {
    rows: Vec<PatchPlanRow>,
    summary: PatchPlanSummary,
    #[serde(skip_serializing_if = "Option::is_none")]
    limits: Option<LimitReport>,
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
struct PatchPlanSummary {
    total_patch_sets: usize,
    complete_patch_sets: usize,
    split_patch_sets: usize,
    unknown_binding_count: usize,
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
struct PatchPlanRow {
    path: String,
    file: String,
    status: PatchPlanStatus,
    requested_binding_ids: Vec<String>,
    unknown_binding_ids: Vec<String>,
    unit_ids: Vec<String>,
    complete_unit_ids: Vec<String>,
    split_unit_ids: Vec<String>,
    missing_binding_ids: Vec<String>,
    missing_owner_ids: Vec<String>,
    missing_anonymous_owner_ids: Vec<String>,
    matching_proposal_ids: Vec<String>,
}

#[derive(Debug, Clone, Copy, Serialize, PartialEq, Eq, PartialOrd, Ord)]
#[serde(rename_all = "snake_case")]
enum PatchPlanStatus {
    CompleteUnits,
    SplitUnits,
    UnknownBindings,
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
struct GraphSummaryReport {
    owner_count: usize,
    owner_edge_count: usize,
    atomic_unit_count: usize,
    residual_atomic_unit_count: usize,
    atomic_edge_count: usize,
    module_count: usize,
    module_edge_count: usize,
    proposal_count: usize,
    diagnostic_count: usize,
    largest_residual_units: Vec<UnitSummary>,
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
struct UnitSummary {
    unit_id: String,
    size_lines_estimate: usize,
    members: Vec<BindingReport>,
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
struct LimitReport {
    limit: usize,
    sections: BTreeMap<&'static str, LimitSectionReport>,
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
struct LimitSectionReport {
    total: usize,
    emitted: usize,
    truncated: bool,
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq, PartialOrd, Ord)]
struct BindingHomeReport {
    binding: String,
    name: String,
    source_kind: BindingHomeSourceKind,
    path: String,
}

#[derive(Debug, Clone, Copy, Serialize, PartialEq, Eq, PartialOrd, Ord)]
#[serde(rename_all = "snake_case")]
enum BindingHomeSourceKind {
    Module,
    BindingPatch,
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
struct SourceSliceReport {
    query: QueryReport,
    owner_ids: Vec<String>,
    slices: Vec<SourceSlice>,
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
struct SourceSlice {
    source_path: String,
    resolved_path: String,
    start_line: usize,
    end_line: usize,
    context_start_line: usize,
    context_end_line: usize,
    text: String,
}

pub fn run_peel(args: PeelArgs) -> Result<()> {
    match args.command {
        PeelCommand::PlanWork(args) => {
            print_json(&run_plan_work_report(&args)?).context("writing plan-work JSON")
        }
        PeelCommand::Units(args) => {
            print_json(&run_units_report(&args)?).context("writing units JSON")
        }
        PeelCommand::PatchPlan(args) => {
            print_json(&run_patch_plan_report(&args)?).context("writing patch-plan JSON")
        }
        PeelCommand::Explain(args) => {
            print_json(&run_explain_report(&args)?).context("writing explain JSON")
        }
        PeelCommand::SourceSlice(args) => {
            print_json(&run_source_slice_report(&args)?).context("writing source-slice JSON")
        }
        PeelCommand::GraphSummary(args) => {
            print_json(&run_graph_summary_report(&args)?).context("writing graph-summary JSON")
        }
    }
}

fn print_json<T: Serialize>(value: &T) -> Result<()> {
    println!("{}", serde_json::to_string_pretty(value)?);
    Ok(())
}

fn run_plan_work_report(args: &PlanWorkArgs) -> Result<PlanWorkReport> {
    let mut report = analyze_peel_factorize(&PeelFactorizeOptions {
        owner_graph_path: args.common.owner_graph_path.clone(),
        modules_root: args.common.modules_root.clone(),
        size_cap_lines: args.size_cap_lines,
    })?;
    let mut sections = BTreeMap::new();
    if args.limit > 0 {
        sort_factorize_diagnostics(&mut report.diagnostics);
    }
    apply_limit_with_metadata(
        &mut report.proposals,
        args.limit,
        &mut sections,
        "proposals",
    );
    apply_limit_with_metadata(
        &mut report.diagnostics,
        args.limit,
        &mut sections,
        "diagnostics",
    );
    Ok(PlanWorkReport {
        report,
        limits: limit_report(args.limit, sections),
    })
}

fn run_units_report(args: &UnitsArgs) -> Result<UnitsReport> {
    let graph = load_graph(&args.common.owner_graph_path)?;
    let mut units = graph.atomic_graph.nodes.clone();
    if args.residual_only {
        units.retain(|unit| {
            unit.destinations
                .iter()
                .any(|destination| destination.residual)
        });
    }
    if args.readable_only {
        units.retain(|unit| {
            unit.members
                .iter()
                .any(|member| member.binding != member.export_name)
        });
    }
    units.sort_by_key(|unit| {
        (
            unit.source_line_range
                .map(|range| range[0])
                .unwrap_or(usize::MAX),
            unit.id.clone(),
        )
    });
    apply_limit(&mut units, args.limit);
    let groups = if args.by_destination {
        group_units_by_destination(&units)
    } else {
        Vec::new()
    };
    Ok(UnitsReport { units, groups })
}

fn run_patch_plan_report(args: &PatchPlanArgs) -> Result<PatchPlanReport> {
    let graph = load_graph(&args.common.owner_graph_path)?;
    let factorize = analyze_peel_factorize(&PeelFactorizeOptions {
        owner_graph_path: args.common.owner_graph_path.clone(),
        modules_root: args.common.modules_root.clone(),
        size_cap_lines: 10_000,
    })?;
    let mut rows = patch_plan_rows(&graph, &args.common.modules_root, &factorize)?;
    rows.sort_by_key(|row| (row.status, row.path.clone()));
    let summary = PatchPlanSummary {
        total_patch_sets: rows.len(),
        complete_patch_sets: rows
            .iter()
            .filter(|row| row.status == PatchPlanStatus::CompleteUnits)
            .count(),
        split_patch_sets: rows
            .iter()
            .filter(|row| row.status == PatchPlanStatus::SplitUnits)
            .count(),
        unknown_binding_count: rows.iter().map(|row| row.unknown_binding_ids.len()).sum(),
    };
    let mut sections = BTreeMap::new();
    apply_limit_with_metadata(&mut rows, args.limit, &mut sections, "rows");
    Ok(PatchPlanReport {
        rows,
        summary,
        limits: limit_report(args.limit, sections),
    })
}

fn run_graph_summary_report(args: &GraphSummaryArgs) -> Result<GraphSummaryReport> {
    let graph = load_graph(&args.common.owner_graph_path)?;
    let factorize = analyze_peel_factorize(&PeelFactorizeOptions {
        owner_graph_path: args.common.owner_graph_path.clone(),
        modules_root: args.common.modules_root.clone(),
        size_cap_lines: args.size_cap_lines,
    })?;
    let mut largest_residual_units: Vec<UnitSummary> = graph
        .atomic_graph
        .nodes
        .iter()
        .filter(|unit| {
            unit.destinations
                .iter()
                .any(|destination| destination.residual)
        })
        .map(|unit| UnitSummary {
            unit_id: unit.id.clone(),
            size_lines_estimate: unit.size_lines_estimate,
            members: unit.members.clone(),
        })
        .collect();
    largest_residual_units.sort_by_key(|unit| {
        (
            std::cmp::Reverse(unit.size_lines_estimate),
            unit.unit_id.clone(),
        )
    });
    apply_limit(&mut largest_residual_units, args.limit);
    Ok(GraphSummaryReport {
        owner_count: graph.nodes.len(),
        owner_edge_count: graph.edges.len(),
        atomic_unit_count: graph.atomic_graph.nodes.len(),
        residual_atomic_unit_count: graph
            .atomic_graph
            .nodes
            .iter()
            .filter(|unit| {
                unit.destinations
                    .iter()
                    .any(|destination| destination.residual)
            })
            .count(),
        atomic_edge_count: graph.atomic_graph.edges.len(),
        module_count: graph.quotient.nodes.len(),
        module_edge_count: graph.quotient.edges.len(),
        proposal_count: factorize.proposals.len(),
        diagnostic_count: factorize.diagnostics.len(),
        largest_residual_units,
    })
}

fn run_explain_report(args: &ExplainArgs) -> Result<ExplainReport> {
    let graph = load_graph(&args.common.owner_graph_path)?;
    let selection = args.selection.selection_kind()?;
    let query = query_report(&selection);
    let owner_ids = resolve_owner_ids(&selection, &graph, &args.common, args.size_cap_lines)?;
    let owner_set: BTreeSet<String> = owner_ids.iter().cloned().collect();
    let mut owners = owners_for_ids(&graph, &owner_set);

    let mut neighbor_ids = BTreeSet::new();
    let mut incoming_edges: Vec<OwnerGraphEdgeReport> = graph
        .edges
        .iter()
        .filter(|edge| owner_set.contains(&edge.target))
        .inspect(|edge| {
            if !owner_set.contains(&edge.source) {
                neighbor_ids.insert(edge.source.clone());
            }
        })
        .cloned()
        .collect();
    let mut outgoing_edges: Vec<OwnerGraphEdgeReport> = graph
        .edges
        .iter()
        .filter(|edge| owner_set.contains(&edge.source))
        .inspect(|edge| {
            if !owner_set.contains(&edge.target) {
                neighbor_ids.insert(edge.target.clone());
            }
        })
        .cloned()
        .collect();
    let mut neighbor_owners = owners_for_ids(&graph, &neighbor_ids);
    let selected_unit_ids = atomic_unit_ids_for_owner_set(&graph, &owner_set);
    let mut atomic_units = graph
        .atomic_graph
        .nodes
        .iter()
        .filter(|unit| selected_unit_ids.contains(&unit.id))
        .cloned()
        .collect();
    let mut incoming_atomic_edges: Vec<AtomicUnitEdgeReport> = graph
        .atomic_graph
        .edges
        .iter()
        .filter(|edge| selected_unit_ids.contains(&edge.target))
        .cloned()
        .collect();
    let mut outgoing_atomic_edges: Vec<AtomicUnitEdgeReport> = graph
        .atomic_graph
        .edges
        .iter()
        .filter(|edge| selected_unit_ids.contains(&edge.source))
        .cloned()
        .collect();

    let mut bindings: Vec<BindingReport> = owners
        .iter()
        .flat_map(|owner| owner.declared_bindings.iter().cloned())
        .collect();
    bindings.sort();
    bindings.dedup();
    let binding_ids: BTreeSet<String> = bindings
        .iter()
        .map(|binding| binding.binding.to_string())
        .collect();
    let mut binding_homes = binding_homes(&args.common.modules_root, &binding_ids)?;

    let selected_destinations: BTreeSet<String> = owners
        .iter()
        .map(|owner| owner.destination.id.clone())
        .collect();
    let mut quotient_edges = graph
        .quotient
        .edges
        .iter()
        .filter(|edge| {
            selected_destinations.contains(&edge.source)
                || selected_destinations.contains(&edge.target)
        })
        .cloned()
        .collect();

    let factorize = analyze_peel_factorize(&PeelFactorizeOptions {
        owner_graph_path: args.common.owner_graph_path.clone(),
        modules_root: args.common.modules_root.clone(),
        size_cap_lines: args.size_cap_lines,
    })?;
    let mut factorize_proposals = factorize
        .proposals
        .into_iter()
        .filter(|proposal| overlaps(&proposal.owner_ids, &owner_set))
        .collect();
    let mut factorize_diagnostics = factorize
        .diagnostics
        .into_iter()
        .filter(|diagnostic| overlaps(&diagnostic.owner_ids, &owner_set))
        .collect();
    let mut limited_owner_ids = owner_ids;

    let mut sections = BTreeMap::new();
    apply_limit_with_metadata(
        &mut limited_owner_ids,
        args.limit,
        &mut sections,
        "owner_ids",
    );
    apply_limit_with_metadata(&mut owners, args.limit, &mut sections, "owners");
    apply_limit_with_metadata(
        &mut neighbor_owners,
        args.limit,
        &mut sections,
        "neighbor_owners",
    );
    apply_limit_with_metadata(&mut bindings, args.limit, &mut sections, "bindings");
    apply_limit_with_metadata(
        &mut binding_homes,
        args.limit,
        &mut sections,
        "binding_homes",
    );
    apply_limit_with_metadata(
        &mut incoming_edges,
        args.limit,
        &mut sections,
        "incoming_edges",
    );
    apply_limit_with_metadata(
        &mut outgoing_edges,
        args.limit,
        &mut sections,
        "outgoing_edges",
    );
    apply_limit_with_metadata(&mut atomic_units, args.limit, &mut sections, "atomic_units");
    apply_limit_with_metadata(
        &mut incoming_atomic_edges,
        args.limit,
        &mut sections,
        "incoming_atomic_edges",
    );
    apply_limit_with_metadata(
        &mut outgoing_atomic_edges,
        args.limit,
        &mut sections,
        "outgoing_atomic_edges",
    );
    apply_limit_with_metadata(
        &mut quotient_edges,
        args.limit,
        &mut sections,
        "quotient_edges",
    );
    apply_limit_with_metadata(
        &mut factorize_proposals,
        args.limit,
        &mut sections,
        "factorize_proposals",
    );
    apply_limit_with_metadata(
        &mut factorize_diagnostics,
        args.limit,
        &mut sections,
        "factorize_diagnostics",
    );

    Ok(ExplainReport {
        query,
        owner_ids: limited_owner_ids,
        owners,
        neighbor_owners,
        bindings,
        binding_homes,
        incoming_edges,
        outgoing_edges,
        atomic_units,
        incoming_atomic_edges,
        outgoing_atomic_edges,
        quotient_edges,
        factorize_proposals,
        factorize_diagnostics,
        limits: limit_report(args.limit, sections),
    })
}

fn run_source_slice_report(args: &SourceSliceArgs) -> Result<SourceSliceReport> {
    let graph = load_graph(&args.common.owner_graph_path)?;
    let selection = args.selection.selection_kind()?;
    let query = query_report(&selection);
    let owner_ids = resolve_owner_ids(&selection, &graph, &args.common, args.size_cap_lines)?;
    let owner_set: BTreeSet<String> = owner_ids.iter().cloned().collect();
    let owners = owners_for_ids(&graph, &owner_set);
    let spans = source_spans(&owners)?;
    let mut slices = Vec::new();
    for (source_path, location) in spans {
        let resolved = resolve_source_file(
            &source_path,
            args.source_root.as_deref(),
            &args.common.owner_graph_path,
            &args.common.modules_root,
        )?;
        let (context_start_line, context_end_line, text) = read_source_text(
            &resolved,
            location.start_line,
            location.end_line,
            args.context_lines,
        )
        .with_context(|| format!("reading source slice from {}", resolved.display()))?;
        slices.push(SourceSlice {
            source_path,
            resolved_path: resolved.display().to_string(),
            start_line: location.start_line,
            end_line: location.end_line,
            context_start_line,
            context_end_line,
            text,
        });
    }
    Ok(SourceSliceReport {
        query,
        owner_ids,
        slices,
    })
}

fn load_graph(path: &Path) -> Result<OwnerGraphReport> {
    serde_json::from_str(
        &fs::read_to_string(path).with_context(|| format!("reading {}", path.display()))?,
    )
    .with_context(|| format!("parsing {}", path.display()))
}

fn apply_limit<T>(records: &mut Vec<T>, limit: usize) {
    if limit > 0 {
        records.truncate(limit);
    }
}

fn apply_limit_with_metadata<T>(
    records: &mut Vec<T>,
    limit: usize,
    sections: &mut BTreeMap<&'static str, LimitSectionReport>,
    section: &'static str,
) {
    if limit == 0 {
        return;
    }
    let total = records.len();
    apply_limit(records, limit);
    let emitted = records.len();
    sections.insert(
        section,
        LimitSectionReport {
            total,
            emitted,
            truncated: emitted < total,
        },
    );
}

fn limit_report(
    limit: usize,
    sections: BTreeMap<&'static str, LimitSectionReport>,
) -> Option<LimitReport> {
    (limit > 0).then_some(LimitReport { limit, sections })
}

fn sort_factorize_diagnostics(diagnostics: &mut [FactorizeDiagnosticReport]) {
    diagnostics.sort_by_key(|diagnostic| {
        (
            diagnostic.reason,
            diagnostic
                .source_line_range
                .map(|range| range[0])
                .unwrap_or(usize::MAX),
            diagnostic.owner_ids.len(),
            diagnostic.diagnostic_id.clone(),
        )
    });
}

fn group_units_by_destination(units: &[AtomicUnitReport]) -> Vec<UnitGroup> {
    let mut groups: BTreeMap<String, Vec<String>> = BTreeMap::new();
    for unit in units {
        for destination in &unit.destinations {
            groups
                .entry(destination.label.clone())
                .or_default()
                .push(unit.id.clone());
        }
    }
    groups
        .into_iter()
        .map(|(destination, unit_ids)| UnitGroup {
            destination,
            unit_ids,
        })
        .collect()
}

fn owners_for_ids(
    graph: &OwnerGraphReport,
    owner_ids: &BTreeSet<String>,
) -> Vec<OwnerGraphNodeReport> {
    graph
        .nodes
        .iter()
        .filter(|owner| owner_ids.contains(&owner.id))
        .cloned()
        .collect()
}

fn atomic_unit_ids_for_owner_set(
    graph: &OwnerGraphReport,
    owner_ids: &BTreeSet<String>,
) -> BTreeSet<String> {
    graph
        .atomic_graph
        .nodes
        .iter()
        .filter(|unit| unit.owner_ids.iter().any(|owner| owner_ids.contains(owner)))
        .map(|unit| unit.id.clone())
        .collect()
}

fn overlaps(owner_ids: &[String], selected: &BTreeSet<String>) -> bool {
    owner_ids.iter().any(|owner_id| selected.contains(owner_id))
}

fn patch_plan_rows(
    graph: &OwnerGraphReport,
    modules_root: &Path,
    factorize: &PeelFactorizeReport,
) -> Result<Vec<PatchPlanRow>> {
    let binding_to_owner = binding_to_owner(graph);
    let unit_by_owner = unit_by_owner(graph);
    let unit_by_id: BTreeMap<String, &AtomicUnitReport> = graph
        .atomic_graph
        .nodes
        .iter()
        .map(|unit| (unit.id.clone(), unit))
        .collect();
    load_patch_sets(modules_root)?
        .into_iter()
        .map(|patch_set| {
            let mut requested_binding_ids: Vec<String> =
                patch_set.bindings.iter().cloned().collect();
            requested_binding_ids.sort();

            let mut requested_owner_ids = BTreeSet::<String>::new();
            let mut unknown_binding_ids = Vec::<String>::new();
            for binding in &requested_binding_ids {
                if let Some(owner_id) = binding_to_owner.get(binding) {
                    requested_owner_ids.insert(owner_id.clone());
                } else {
                    unknown_binding_ids.push(binding.clone());
                }
            }

            let mut unit_ids: BTreeSet<String> = BTreeSet::new();
            for owner_id in &requested_owner_ids {
                if let Some(unit_id) = unit_by_owner.get(owner_id) {
                    unit_ids.insert(unit_id.clone());
                }
            }

            let mut complete_unit_ids = Vec::<String>::new();
            let mut split_unit_ids = Vec::<String>::new();
            let mut missing_binding_ids = BTreeSet::<String>::new();
            let mut missing_owner_ids = BTreeSet::<String>::new();
            let mut missing_anonymous_owner_ids = BTreeSet::<String>::new();
            for unit_id in &unit_ids {
                let Some(unit) = unit_by_id.get(unit_id) else {
                    continue;
                };
                let unit_bindings: BTreeSet<String> =
                    unit.members.iter().map(|m| m.binding.to_string()).collect();
                let unit_owners: BTreeSet<String> = unit.owner_ids.iter().cloned().collect();
                let bindings_complete = unit_bindings
                    .iter()
                    .all(|binding| patch_set.bindings.contains(binding));
                let owners_complete = unit_owners
                    .iter()
                    .all(|owner_id| requested_owner_ids.contains(owner_id));
                if bindings_complete && owners_complete {
                    complete_unit_ids.push(unit_id.clone());
                } else {
                    split_unit_ids.push(unit_id.clone());
                    missing_binding_ids.extend(
                        unit_bindings
                            .into_iter()
                            .filter(|binding| !patch_set.bindings.contains(binding)),
                    );
                    missing_owner_ids.extend(
                        unit_owners
                            .into_iter()
                            .filter(|owner_id| !requested_owner_ids.contains(owner_id)),
                    );
                    missing_anonymous_owner_ids.extend(
                        unit.anonymous_statement_owner_ids
                            .iter()
                            .filter(|owner_id| !requested_owner_ids.contains(*owner_id))
                            .cloned(),
                    );
                }
            }
            let status = if !split_unit_ids.is_empty() {
                PatchPlanStatus::SplitUnits
            } else if !unknown_binding_ids.is_empty() {
                PatchPlanStatus::UnknownBindings
            } else {
                PatchPlanStatus::CompleteUnits
            };
            let matching_proposal_ids = matching_proposal_ids(factorize, &requested_owner_ids);
            Ok(PatchPlanRow {
                path: patch_set.path,
                file: patch_set.file.display().to_string(),
                status,
                requested_binding_ids,
                unknown_binding_ids,
                unit_ids: unit_ids.into_iter().collect(),
                complete_unit_ids,
                split_unit_ids,
                missing_binding_ids: missing_binding_ids.into_iter().collect(),
                missing_owner_ids: missing_owner_ids.into_iter().collect(),
                missing_anonymous_owner_ids: missing_anonymous_owner_ids.into_iter().collect(),
                matching_proposal_ids,
            })
        })
        .collect()
}

#[derive(Debug, Clone)]
struct PatchSet {
    path: String,
    file: PathBuf,
    bindings: BTreeSet<String>,
}

fn load_patch_sets(modules_root: &Path) -> Result<Vec<PatchSet>> {
    let mut sets = Vec::<PatchSet>::new();
    let binding_patches_path = default_binding_patches_path(modules_root);
    let patch_bindings: BTreeSet<String> = load_binding_patch_members(modules_root)?
        .into_iter()
        .map(|member| member.selector.binding.name)
        .collect();
    if !patch_bindings.is_empty() {
        sets.push(PatchSet {
            path: "binding_patches".to_string(),
            file: binding_patches_path,
            bindings: patch_bindings,
        });
    }
    for file in collect_module_files(modules_root)? {
        let bindings = read_module_file(&file)?
            .members
            .into_iter()
            .map(|member| member.selector.binding.name)
            .collect::<BTreeSet<_>>();
        if bindings.is_empty() {
            continue;
        }
        sets.push(PatchSet {
            path: module_path_from_file(&file, modules_root),
            file,
            bindings,
        });
    }
    Ok(sets)
}

fn binding_to_owner(graph: &OwnerGraphReport) -> BTreeMap<String, String> {
    let mut out = BTreeMap::new();
    for node in &graph.nodes {
        for binding in &node.declared_bindings {
            out.insert(binding.binding.to_string(), node.id.clone());
        }
    }
    out
}

fn unit_by_owner(graph: &OwnerGraphReport) -> BTreeMap<String, String> {
    let mut out = BTreeMap::new();
    for unit in &graph.atomic_graph.nodes {
        for owner_id in &unit.owner_ids {
            out.insert(owner_id.clone(), unit.id.clone());
        }
    }
    out
}

fn matching_proposal_ids(
    factorize: &PeelFactorizeReport,
    requested_owner_ids: &BTreeSet<String>,
) -> Vec<String> {
    if requested_owner_ids.is_empty() {
        return Vec::new();
    }
    factorize
        .proposals
        .iter()
        .filter(|proposal| {
            let proposal_owners: BTreeSet<String> = proposal.owner_ids.iter().cloned().collect();
            requested_owner_ids.is_subset(&proposal_owners)
        })
        .map(|proposal| proposal.proposed_module_id.clone())
        .collect()
}

impl SelectionArgs {
    fn selection_kind(&self) -> Result<SelectionKind> {
        let selected = [
            self.owner_id.as_ref(),
            self.binding_id.as_ref(),
            self.proposal_id.as_ref(),
            self.unit_id.as_ref(),
            self.diagnostic_id.as_ref(),
        ]
        .into_iter()
        .filter(|value| value.is_some())
        .count();
        if selected != 1 {
            bail!(
                "select exactly one of --owner-id, --binding-id, --proposal-id, --unit-id, or --diagnostic-id (got {selected})"
            );
        }
        if let Some(owner_id) = &self.owner_id {
            Ok(SelectionKind::Owner(owner_id.clone()))
        } else if let Some(binding_id) = &self.binding_id {
            Ok(SelectionKind::Binding(binding_id.clone()))
        } else if let Some(proposal_id) = &self.proposal_id {
            Ok(SelectionKind::Proposal(proposal_id.clone()))
        } else if let Some(unit_id) = &self.unit_id {
            Ok(SelectionKind::Unit(unit_id.clone()))
        } else if let Some(diagnostic_id) = &self.diagnostic_id {
            Ok(SelectionKind::Diagnostic(diagnostic_id.clone()))
        } else {
            unreachable!("selected count already validated")
        }
    }
}

fn query_report(selection: &SelectionKind) -> QueryReport {
    match selection {
        SelectionKind::Owner(value) => QueryReport {
            kind: QueryKind::Owner,
            value: value.clone(),
        },
        SelectionKind::Binding(value) => QueryReport {
            kind: QueryKind::Binding,
            value: value.clone(),
        },
        SelectionKind::Proposal(value) => QueryReport {
            kind: QueryKind::Proposal,
            value: value.clone(),
        },
        SelectionKind::Unit(value) => QueryReport {
            kind: QueryKind::Unit,
            value: value.clone(),
        },
        SelectionKind::Diagnostic(value) => QueryReport {
            kind: QueryKind::Diagnostic,
            value: value.clone(),
        },
    }
}

fn resolve_owner_ids(
    selection: &SelectionKind,
    graph: &OwnerGraphReport,
    common: &CommonArgs,
    size_cap_lines: usize,
) -> Result<Vec<String>> {
    let mut owner_ids: Vec<String> = match selection {
        SelectionKind::Owner(owner_id) => {
            if graph.nodes.iter().any(|node| node.id == *owner_id) {
                vec![owner_id.clone()]
            } else {
                bail!("owner id {owner_id:?} not found in owner graph");
            }
        }
        SelectionKind::Binding(binding_id) => graph
            .nodes
            .iter()
            .filter(|node| {
                node.declared_bindings
                    .iter()
                    .any(|binding| binding.binding == *binding_id)
            })
            .map(|node| node.id.clone())
            .collect(),
        SelectionKind::Proposal(proposal_id) => {
            let factorize = analyze_peel_factorize(&PeelFactorizeOptions {
                owner_graph_path: common.owner_graph_path.clone(),
                modules_root: common.modules_root.clone(),
                size_cap_lines,
            })?;
            factorize
                .proposals
                .iter()
                .find(|proposal| proposal.proposed_module_id == *proposal_id)
                .map(|proposal| proposal.owner_ids.clone())
                .unwrap_or_default()
        }
        SelectionKind::Unit(unit_id) => graph
            .atomic_graph
            .nodes
            .iter()
            .find(|unit| unit.id == *unit_id)
            .map(|unit| unit.owner_ids.clone())
            .unwrap_or_default(),
        SelectionKind::Diagnostic(diagnostic_id) => {
            let factorize = analyze_peel_factorize(&PeelFactorizeOptions {
                owner_graph_path: common.owner_graph_path.clone(),
                modules_root: common.modules_root.clone(),
                size_cap_lines,
            })?;
            factorize
                .diagnostics
                .iter()
                .find(|diagnostic| diagnostic.diagnostic_id == *diagnostic_id)
                .map(|diagnostic| diagnostic.owner_ids.clone())
                .unwrap_or_default()
        }
    };
    owner_ids.sort();
    owner_ids.dedup();
    if owner_ids.is_empty() {
        bail!("selection did not resolve to any owner ids");
    }
    Ok(owner_ids)
}

fn binding_homes(
    modules_root: &Path,
    binding_ids: &BTreeSet<String>,
) -> Result<Vec<BindingHomeReport>> {
    let mut homes = BTreeSet::new();
    for path in collect_module_files(modules_root)? {
        let module_path = module_path_from_file(&path, modules_root);
        for member in read_module_file(&path)?.members {
            let binding = member.selector.binding.name;
            if binding_ids.contains(&binding) {
                homes.insert(BindingHomeReport {
                    binding,
                    name: member.name.unwrap_or_default(),
                    source_kind: BindingHomeSourceKind::Module,
                    path: module_path.clone(),
                });
            }
        }
    }
    let patches_path = default_binding_patches_path(modules_root);
    for member in load_binding_patch_members(modules_root)? {
        let binding = member.selector.binding.name;
        if binding_ids.contains(&binding) {
            homes.insert(BindingHomeReport {
                binding,
                name: member.name.unwrap_or_default(),
                source_kind: BindingHomeSourceKind::BindingPatch,
                path: patches_path.display().to_string(),
            });
        }
    }
    Ok(homes.into_iter().collect())
}

fn source_spans(owners: &[OwnerGraphNodeReport]) -> Result<BTreeMap<String, SourceLocation>> {
    let mut spans: BTreeMap<String, SourceLocation> = BTreeMap::new();
    for owner in owners {
        let Some(location) = &owner.source_location else {
            continue;
        };
        spans
            .entry(location.source_path.clone())
            .and_modify(|span| {
                span.start_line = span.start_line.min(location.start_line);
                span.end_line = span.end_line.max(location.end_line);
            })
            .or_insert_with(|| location.clone());
    }
    if spans.is_empty() {
        bail!("selected owners do not have source locations");
    }
    Ok(spans)
}

fn resolve_source_file(
    source_path: &str,
    source_root: Option<&Path>,
    owner_graph_path: &Path,
    modules_root: &Path,
) -> Result<PathBuf> {
    let mut candidates = Vec::new();
    let source = PathBuf::from(source_path);
    if source.is_absolute() {
        candidates.push(source);
    } else {
        if let Some(root) = source_root {
            candidates.push(root.join(source_path));
        }
        if let Ok(cwd) = env::current_dir() {
            candidates.push(cwd.join(source_path));
        }
        push_relative_candidate(&mut candidates, owner_graph_path.parent(), source_path);
        push_relative_candidate(
            &mut candidates,
            owner_graph_path.parent().and_then(Path::parent),
            source_path,
        );
        push_relative_candidate(&mut candidates, modules_root.parent(), source_path);
        push_relative_candidate(
            &mut candidates,
            modules_root.parent().and_then(Path::parent),
            source_path,
        );
    }
    dedup_paths(&mut candidates);
    for candidate in &candidates {
        if candidate.is_file() {
            return Ok(candidate.clone());
        }
    }
    bail!(
        "could not resolve source path {source_path:?}; pass --source-root. Tried: {}",
        candidates
            .iter()
            .map(|path| path.display().to_string())
            .collect::<Vec<_>>()
            .join(", ")
    )
}

fn push_relative_candidate(candidates: &mut Vec<PathBuf>, root: Option<&Path>, source_path: &str) {
    if let Some(root) = root {
        candidates.push(root.join(source_path));
    }
}

fn dedup_paths(paths: &mut Vec<PathBuf>) {
    let mut seen = BTreeSet::new();
    paths.retain(|path| seen.insert(path.display().to_string()));
}

fn read_source_text(
    path: &Path,
    start_line: usize,
    end_line: usize,
    context_lines: usize,
) -> Result<(usize, usize, String)> {
    let body = fs::read_to_string(path)?;
    let lines: Vec<&str> = body.lines().collect();
    if lines.is_empty() {
        return Ok((1, 0, String::new()));
    }
    let context_start_line = start_line.saturating_sub(context_lines).max(1);
    let context_end_line = end_line.saturating_add(context_lines).min(lines.len());
    let start_index = context_start_line.saturating_sub(1).min(lines.len());
    let end_index = context_end_line.min(lines.len());
    let text = if start_index <= end_index {
        lines[start_index..end_index].join("\n")
    } else {
        String::new()
    };
    Ok((context_start_line, context_end_line, text))
}

#[cfg(test)]
mod tests {
    use std::fs;
    use std::path::Path;

    use analysis::{
        AtomicGraphReport, AtomicUnitEdgeReport, AtomicUnitReport, DepKind, ModuleReportRef,
        OwnerGraphEdgeReport, OwnerGraphNodeReport, OwnerGraphQuotientReport, OwnerGraphReport,
        Purity, QuotientSccReport, SourceLocation, StatementKind, StatementOrdinal,
    };
    use tempfile::TempDir;

    use super::*;
    use super::super::test_utils;

    fn write(path: &Path, body: &str) {
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent).unwrap();
        }
        fs::write(path, body).unwrap();
    }

    fn owner(id: &str, ordinal: usize, binding: &str, export_name: &str) -> OwnerGraphNodeReport {
        OwnerGraphNodeReport {
            id: id.to_string(),
            statement_ordinal: StatementOrdinal(ordinal),
            source_location: Some(SourceLocation {
                source_path: "static/index.js".to_string(),
                start_line: ordinal + 1,
                end_line: ordinal + 1,
            }),
            declared_bindings: vec![test_utils::member(binding, export_name)],
            statement_kind: StatementKind::VarDecl,
            purity: Purity::Pure,
            destination: test_utils::module_ref("residual", true),
        }
    }

    fn atomic_unit(id: &str, owners: &[&OwnerGraphNodeReport]) -> AtomicUnitReport {
        let mut owner_ids = Vec::new();
        let mut members = Vec::new();
        let mut destinations = BTreeMap::<String, ModuleReportRef>::new();
        let mut start_line = usize::MAX;
        let mut end_line = 0usize;
        let mut size_lines_estimate = 0usize;
        for owner in owners {
            owner_ids.push(owner.id.clone());
            members.extend(owner.declared_bindings.clone());
            destinations.insert(owner.destination.id.clone(), owner.destination.clone());
            if let Some(location) = &owner.source_location {
                start_line = start_line.min(location.start_line);
                end_line = end_line.max(location.end_line);
                size_lines_estimate += location.end_line + 1 - location.start_line;
            }
        }
        AtomicUnitReport {
            id: id.to_string(),
            owner_ids,
            members,
            anonymous_statement_owner_ids: Vec::new(),
            destinations: destinations.into_values().collect(),
            causes: Vec::new(),
            size_lines_estimate,
            source_line_range: Some([start_line, end_line]),
            ordinal_span: 0,
        }
    }

    fn atomic_edge(
        id: &str,
        source: &str,
        target: &str,
        owner_edge_id: &str,
    ) -> AtomicUnitEdgeReport {
        AtomicUnitEdgeReport {
            id: id.to_string(),
            source: source.to_string(),
            target: target.to_string(),
            edge_kinds: vec![DepKind::EagerUse],
            owner_edge_ids: vec![owner_edge_id.to_string()],
            constrains_init_order: true,
        }
    }

    fn graph_fixture() -> OwnerGraphReport {
        let zz = owner("owner:0", 1, "ZZ", "PaymentError");
        let aa = owner("owner:1", 2, "aa", "aa");
        OwnerGraphReport {
            chunk_id: "static/index".to_string(),
            nodes: vec![zz.clone(), aa.clone()],
            edges: vec![OwnerGraphEdgeReport {
                id: "edge:0".to_string(),
                source: "owner:1".to_string(),
                target: "owner:0".to_string(),
                edge_kind: DepKind::EagerUse,
                binding: Some("ZZ".into()),
                statement_ordinal: StatementOrdinal(2),
                constrains_init_order: true,
            }],
            quotient: OwnerGraphQuotientReport {
                nodes: Vec::new(),
                edges: Vec::new(),
                sccs: Vec::<QuotientSccReport>::new(),
            },
            atomic_graph: AtomicGraphReport {
                nodes: vec![
                    atomic_unit("atomic:0", &[&zz]),
                    atomic_unit("atomic:1", &[&aa]),
                ],
                edges: vec![atomic_edge(
                    "atomic_edge:0",
                    "atomic:1",
                    "atomic:0",
                    "edge:0",
                )],
            },
        }
    }

    fn fixture_with_graph(graph: OwnerGraphReport) -> (TempDir, CommonArgs) {
        let temp = tempfile::tempdir().unwrap();
        let graph_path = temp.path().join("owner_graph.json");
        let modules_root = temp.path().join("spec/modules");
        write(&graph_path, &serde_json::to_string_pretty(&graph).unwrap());
        write(
            &temp.path().join("spec/binding_patches.yaml"),
            "members:\n  - name: PaymentError\n    selector:\n      binding:\n        name: ZZ\n",
        );
        write(&modules_root.join(".keep"), "");
        write(
            &temp.path().join("static/index.js"),
            "const first = 1;\nconst ZZ = class PaymentError {};\nconst aa = ZZ;\n",
        );
        (
            temp,
            CommonArgs {
                owner_graph_path: graph_path,
                modules_root,
            },
        )
    }

    fn fixture() -> (TempDir, CommonArgs) {
        fixture_with_graph(graph_fixture())
    }

    #[test]
    fn plan_work_limit_keeps_sorted_prefix_and_reports_totals() {
        let (_temp, common) = fixture();
        let report = run_plan_work_report(&PlanWorkArgs {
            common,
            size_cap_lines: 10_000,
            limit: 1,
        })
        .unwrap();

        assert_eq!(report.report.proposals.len(), 1);
        assert!(report.report.proposals[0].landable_today);
        let limits = report.limits.unwrap();
        assert_eq!(limits.limit, 1);
        assert_eq!(limits.sections["proposals"].total, 1);
        assert_eq!(limits.sections["proposals"].emitted, 1);
        assert!(!limits.sections["proposals"].truncated);
    }

    #[test]
    fn units_emits_units_and_groups() {
        let (_temp, common) = fixture();
        let report = run_units_report(&UnitsArgs {
            common,
            limit: 0,
            residual_only: true,
            readable_only: true,
            by_destination: true,
        })
        .unwrap();
        assert_eq!(report.units.len(), 1);
        assert_eq!(report.units[0].members[0].binding, "ZZ");
        assert_eq!(report.groups.len(), 1);
    }

    #[test]
    fn patch_plan_reports_split_atomic_units() {
        let (_temp, common) = fixture();
        let report = run_patch_plan_report(&PatchPlanArgs { common, limit: 0 }).unwrap();
        let row = report
            .rows
            .iter()
            .find(|row| row.path == "binding_patches")
            .expect("binding patch row");
        assert_eq!(row.status, PatchPlanStatus::CompleteUnits);
        assert_eq!(row.complete_unit_ids, vec!["atomic:0".to_string()]);
    }

    #[test]
    fn explain_binding_includes_graph_and_spec_context() {
        let (_temp, common) = fixture();
        let report = run_explain_report(&ExplainArgs {
            common,
            selection: SelectionArgs {
                owner_id: None,
                binding_id: Some("ZZ".to_string()),
                proposal_id: None,
                unit_id: None,
                diagnostic_id: None,
            },
            size_cap_lines: 10_000,
            limit: 0,
        })
        .unwrap();
        assert_eq!(report.owner_ids, vec!["owner:0"]);
        assert_eq!(report.incoming_edges.len(), 1);
        assert_eq!(report.neighbor_owners[0].id, "owner:1");
        assert_eq!(
            report.binding_homes[0].source_kind,
            BindingHomeSourceKind::BindingPatch
        );
        assert_eq!(report.atomic_units[0].id, "atomic:0");
        assert_eq!(
            report.factorize_proposals[0].proposed_module_id,
            "auto_partition_0000"
        );
    }

    #[test]
    fn explain_limit_applies_per_section_and_reports_totals() {
        let mut graph = graph_fixture();
        graph.nodes.push(owner("owner:2", 3, "bb", "bb"));
        graph.nodes.push(owner("owner:3", 4, "cc", "cc"));
        graph.edges.push(OwnerGraphEdgeReport {
            id: "edge:1".to_string(),
            source: "owner:2".to_string(),
            target: "owner:0".to_string(),
            edge_kind: DepKind::EagerUse,
            binding: Some("ZZ".into()),
            statement_ordinal: StatementOrdinal(3),
            constrains_init_order: true,
        });
        graph.edges.push(OwnerGraphEdgeReport {
            id: "edge:2".to_string(),
            source: "owner:3".to_string(),
            target: "owner:0".to_string(),
            edge_kind: DepKind::EagerUse,
            binding: Some("ZZ".into()),
            statement_ordinal: StatementOrdinal(4),
            constrains_init_order: true,
        });

        let (_temp, common) = fixture_with_graph(graph);
        let report = run_explain_report(&ExplainArgs {
            common,
            selection: SelectionArgs {
                owner_id: None,
                binding_id: Some("ZZ".to_string()),
                proposal_id: None,
                unit_id: None,
                diagnostic_id: None,
            },
            size_cap_lines: 10_000,
            limit: 1,
        })
        .unwrap();

        assert_eq!(report.incoming_edges.len(), 1);
        assert_eq!(report.neighbor_owners.len(), 1);
        let limits = report.limits.unwrap();
        assert_eq!(limits.sections["incoming_edges"].total, 3);
        assert_eq!(limits.sections["incoming_edges"].emitted, 1);
        assert!(limits.sections["incoming_edges"].truncated);
        assert_eq!(limits.sections["neighbor_owners"].total, 3);
        assert_eq!(limits.sections["neighbor_owners"].emitted, 1);
        assert!(limits.sections["neighbor_owners"].truncated);
        assert_eq!(limits.sections["owner_ids"].total, 1);
        assert!(!limits.sections["owner_ids"].truncated);
    }

    #[test]
    fn source_slice_reads_context_from_resolved_source_root() {
        let (temp, common) = fixture();
        let report = run_source_slice_report(&SourceSliceArgs {
            common,
            selection: SelectionArgs {
                owner_id: Some("owner:0".to_string()),
                binding_id: None,
                proposal_id: None,
                unit_id: None,
                diagnostic_id: None,
            },
            size_cap_lines: 10_000,
            context_lines: 1,
            source_root: Some(temp.path().to_path_buf()),
        })
        .unwrap();
        assert_eq!(report.slices.len(), 1);
        assert_eq!(report.slices[0].context_start_line, 1);
        assert_eq!(report.slices[0].context_end_line, 3);
        assert!(report.slices[0].text.contains("class PaymentError"));
    }
}
