//! Agent-facing read-only debundler workbench.
//!
//! This binary is for agents maintaining a debundle spec. It exposes
//! stable JSON operations over the owner graph and spec tree instead
//! of human-oriented "views".

use std::cmp::Reverse;
use std::collections::{BTreeMap, BTreeSet};
use std::env;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::ExitCode;

use anyhow::{Context, Result, bail};
use clap::{Args as ClapArgs, Parser, Subcommand};
use peel_factorize::{FactorizeDiagnosticReport, FactorizeProposal, PeelFactorizeOptions};
use peel_factorize::{PeelFactorizeReport, analyze_peel_factorize};
use peel_horizon::{PeelHorizonOptions, PeelHorizonReport, analyze_peel_horizon};
use peel_inventory::{PeelInventoryOptions, PeelInventoryRecord, build_inventory};
use serde::Serialize;

use analysis::{
    BindingReport, EvaluatedPeelCandidateReport, OwnerGraphEdgeReport, OwnerGraphNodeReport,
    OwnerGraphPeelSetReport, OwnerGraphReport, QuotientEdgeReport, ResidualOwnerPeelHorizonReport,
    SourceLocation,
};
use spec_modules::{
    collect_module_files, default_binding_patches_path, load_binding_patch_members,
    module_path_from_file, read_module_file,
};

#[derive(Debug, Parser)]
#[command(
    name = "debundle-agent",
    about = "Agent-facing read-only operations over a debundle owner_graph.json and spec modules tree."
)]
pub struct AgentArgs {
    #[command(subcommand)]
    command: AgentCommand,
}

#[derive(Debug, Subcommand)]
enum AgentCommand {
    /// Emit certified module-assignment proposals and diagnostics.
    #[command(name = "plan-work")]
    PlanWork(PlanWorkArgs),
    /// List peelable binding candidates from the current graph/spec.
    #[command(name = "list-candidates")]
    ListCandidates(ListCandidatesArgs),
    /// Report binding-patch coverage against current peelability.
    #[command(name = "patch-status")]
    PatchStatus(PatchStatusArgs),
    /// Explain one owner, binding, or proposal with graph/spec context.
    Explain(ExplainArgs),
    /// Print source text for one owner, binding, or proposal.
    #[command(name = "source-slice")]
    SourceSlice(SourceSliceArgs),
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
}

#[derive(Debug, Clone, ClapArgs)]
struct ListCandidatesArgs {
    #[command(flatten)]
    common: CommonArgs,

    /// Maximum number of candidates to emit. Zero means unlimited.
    #[arg(long, default_value_t = 0)]
    limit: usize,

    /// Filter to candidates with at least one renamed export.
    #[arg(long = "readable-only")]
    readable_only: bool,

    /// Also group emitted candidates by `proposed_dir`.
    #[arg(long = "by-destination")]
    by_destination: bool,
}

#[derive(Debug, Clone, ClapArgs)]
struct PatchStatusArgs {
    #[command(flatten)]
    common: CommonArgs,

    /// Near-missing companion threshold.
    #[arg(long = "near-missing", default_value_t = 2)]
    near_missing: usize,

    /// Max companion bindings to include per near-miss row.
    #[arg(long = "max-companions", default_value_t = 16)]
    max_companions: usize,

    /// Maximum number of rows to keep in each report section. Zero means unlimited.
    #[arg(long, default_value_t = 0)]
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
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
struct QueryReport {
    kind: &'static str,
    value: String,
}

#[derive(Debug, Clone)]
enum SelectionKind {
    Owner(String),
    Binding(String),
    Proposal(String),
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
struct ListCandidatesReport {
    candidates: Vec<PeelInventoryRecord>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    groups: Vec<CandidateGroup>,
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
struct CandidateGroup {
    proposed_dir: String,
    candidates: Vec<PeelInventoryRecord>,
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
    quotient_edges: Vec<QuotientEdgeReport>,
    peel_sets: Vec<OwnerGraphPeelSetReport>,
    evaluated_owner_sets: Vec<EvaluatedPeelCandidateReport>,
    residual_horizon: Vec<ResidualOwnerPeelHorizonReport>,
    factorize_proposals: Vec<FactorizeProposal>,
    factorize_diagnostics: Vec<FactorizeDiagnosticReport>,
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq, PartialOrd, Ord)]
struct BindingHomeReport {
    binding: String,
    name: String,
    source_kind: &'static str,
    path: String,
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

/// Run the agent CLI from argv. Returns the appropriate exit code.
pub fn run_agent() -> ExitCode {
    match real_agent(AgentArgs::parse()) {
        Ok(()) => ExitCode::SUCCESS,
        Err(error) => {
            eprintln!("{error:#}");
            ExitCode::from(1)
        }
    }
}

fn real_agent(args: AgentArgs) -> Result<()> {
    match args.command {
        AgentCommand::PlanWork(args) => {
            print_json(&run_plan_work_report(&args)?).context("writing plan-work JSON")
        }
        AgentCommand::ListCandidates(args) => {
            print_json(&run_list_candidates_report(&args)?).context("writing list-candidates JSON")
        }
        AgentCommand::PatchStatus(args) => {
            print_json(&run_patch_status_report(&args)?).context("writing patch-status JSON")
        }
        AgentCommand::Explain(args) => {
            print_json(&run_explain_report(&args)?).context("writing explain JSON")
        }
        AgentCommand::SourceSlice(args) => {
            print_json(&run_source_slice_report(&args)?).context("writing source-slice JSON")
        }
    }
}

fn print_json<T: Serialize>(value: &T) -> Result<()> {
    println!("{}", serde_json::to_string_pretty(value)?);
    Ok(())
}

fn run_plan_work_report(args: &PlanWorkArgs) -> Result<PeelFactorizeReport> {
    analyze_peel_factorize(&PeelFactorizeOptions {
        owner_graph_path: args.common.owner_graph_path.clone(),
        modules_root: args.common.modules_root.clone(),
        size_cap_lines: args.size_cap_lines,
    })
}

fn run_list_candidates_report(args: &ListCandidatesArgs) -> Result<ListCandidatesReport> {
    let mut candidates = build_inventory(&PeelInventoryOptions {
        owner_graph_path: args.common.owner_graph_path.clone(),
        modules_root: args.common.modules_root.clone(),
    })?;
    if args.readable_only {
        candidates.retain(|record| record.has_readable);
    }
    sort_candidates(&mut candidates);
    apply_limit(&mut candidates, args.limit);
    let groups = if args.by_destination {
        group_candidates_by_destination(&candidates)
    } else {
        Vec::new()
    };
    Ok(ListCandidatesReport { candidates, groups })
}

fn run_patch_status_report(args: &PatchStatusArgs) -> Result<PeelHorizonReport> {
    let mut report = analyze_peel_horizon(&PeelHorizonOptions {
        owner_graph_path: args.common.owner_graph_path.clone(),
        modules_root: args.common.modules_root.clone(),
        near_missing: args.near_missing,
        max_companions: args.max_companions,
    })?;
    apply_limit(&mut report.full, args.limit);
    apply_limit(&mut report.with_companions, args.limit);
    apply_limit(&mut report.near, args.limit);
    Ok(report)
}

fn run_explain_report(args: &ExplainArgs) -> Result<ExplainReport> {
    let graph = load_graph(&args.common.owner_graph_path)?;
    let selection = args.selection.selection_kind()?;
    let query = query_report(&selection);
    let owner_ids = resolve_owner_ids(&selection, &graph, &args.common, args.size_cap_lines)?;
    let owner_set: BTreeSet<String> = owner_ids.iter().cloned().collect();
    let owners = owners_for_ids(&graph, &owner_set);

    let mut neighbor_ids = BTreeSet::new();
    let incoming_edges: Vec<OwnerGraphEdgeReport> = graph
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
    let outgoing_edges: Vec<OwnerGraphEdgeReport> = graph
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
    let neighbor_owners = owners_for_ids(&graph, &neighbor_ids);

    let mut bindings: Vec<BindingReport> = owners
        .iter()
        .flat_map(|owner| owner.declared_bindings.iter().cloned())
        .collect();
    bindings.sort();
    bindings.dedup();
    let binding_ids: BTreeSet<String> = bindings
        .iter()
        .map(|binding| binding.binding.clone())
        .collect();
    let binding_homes = binding_homes(&args.common.modules_root, &binding_ids)?;

    let selected_destinations: BTreeSet<String> = owners
        .iter()
        .map(|owner| owner.destination.id.clone())
        .collect();
    let quotient_edges = graph
        .quotient
        .edges
        .iter()
        .filter(|edge| {
            selected_destinations.contains(&edge.source)
                || selected_destinations.contains(&edge.target)
        })
        .cloned()
        .collect();

    let peel_sets = graph
        .peelability
        .minimal_peel_sets
        .iter()
        .filter(|set| overlaps(&set.owner_ids, &owner_set))
        .cloned()
        .collect();
    let evaluated_owner_sets = graph
        .peelability
        .evaluated_owner_sets
        .iter()
        .filter(|set| overlaps(&set.owner_ids, &owner_set))
        .cloned()
        .collect();
    let residual_horizon = graph
        .peelability
        .residual_owner_horizon
        .iter()
        .filter(|owner| owner_set.contains(&owner.owner_id))
        .cloned()
        .collect();

    let factorize = analyze_peel_factorize(&PeelFactorizeOptions {
        owner_graph_path: args.common.owner_graph_path.clone(),
        modules_root: args.common.modules_root.clone(),
        size_cap_lines: args.size_cap_lines,
    })?;
    let factorize_proposals = factorize
        .proposals
        .into_iter()
        .filter(|proposal| overlaps(&proposal.owner_ids, &owner_set))
        .collect();
    let factorize_diagnostics = factorize
        .diagnostics
        .into_iter()
        .filter(|diagnostic| overlaps(&diagnostic.owner_ids, &owner_set))
        .collect();

    Ok(ExplainReport {
        query,
        owner_ids,
        owners,
        neighbor_owners,
        bindings,
        binding_homes,
        incoming_edges,
        outgoing_edges,
        quotient_edges,
        peel_sets,
        evaluated_owner_sets,
        residual_horizon,
        factorize_proposals,
        factorize_diagnostics,
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

fn sort_candidates(candidates: &mut [PeelInventoryRecord]) {
    candidates.sort_by_key(|record| {
        (
            record.owner_count,
            Reverse(record.has_readable),
            record.proposed_dir.clone(),
            record.candidate_id.clone(),
        )
    });
}

fn apply_limit<T>(records: &mut Vec<T>, limit: usize) {
    if limit > 0 {
        records.truncate(limit);
    }
}

fn group_candidates_by_destination(candidates: &[PeelInventoryRecord]) -> Vec<CandidateGroup> {
    let mut groups: BTreeMap<String, Vec<PeelInventoryRecord>> = BTreeMap::new();
    for candidate in candidates {
        groups
            .entry(candidate.proposed_dir.clone())
            .or_default()
            .push(candidate.clone());
    }
    groups
        .into_iter()
        .map(|(proposed_dir, candidates)| CandidateGroup {
            proposed_dir,
            candidates,
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

fn overlaps(owner_ids: &[String], selected: &BTreeSet<String>) -> bool {
    owner_ids.iter().any(|owner_id| selected.contains(owner_id))
}

impl SelectionArgs {
    fn selection_kind(&self) -> Result<SelectionKind> {
        let selected = [
            self.owner_id.as_ref(),
            self.binding_id.as_ref(),
            self.proposal_id.as_ref(),
        ]
        .into_iter()
        .filter(|value| value.is_some())
        .count();
        if selected != 1 {
            bail!(
                "select exactly one of --owner-id, --binding-id, or --proposal-id (got {selected})"
            );
        }
        if let Some(owner_id) = &self.owner_id {
            Ok(SelectionKind::Owner(owner_id.clone()))
        } else if let Some(binding_id) = &self.binding_id {
            Ok(SelectionKind::Binding(binding_id.clone()))
        } else if let Some(proposal_id) = &self.proposal_id {
            Ok(SelectionKind::Proposal(proposal_id.clone()))
        } else {
            unreachable!("selected count already validated")
        }
    }
}

fn query_report(selection: &SelectionKind) -> QueryReport {
    match selection {
        SelectionKind::Owner(value) => QueryReport {
            kind: "owner_id",
            value: value.clone(),
        },
        SelectionKind::Binding(value) => QueryReport {
            kind: "binding_id",
            value: value.clone(),
        },
        SelectionKind::Proposal(value) => QueryReport {
            kind: "proposal_id",
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
                    source_kind: "module",
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
                source_kind: "binding_patch",
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
        DepKind, FactorizeCell, FactorizeReport, ModuleReportRef, OwnerGraphEdgeReport,
        OwnerGraphNodeReport, OwnerGraphPeelSetReport, OwnerGraphPeelabilityReport,
        OwnerGraphQuotientReport, OwnerGraphReport, PeelCandidateStatus, Purity, QuotientSccReport,
        SourceLocation, StatementKind, StatementOrdinal,
    };
    use tempfile::TempDir;

    use super::*;

    fn write(path: &Path, body: &str) {
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent).unwrap();
        }
        fs::write(path, body).unwrap();
    }

    fn member(binding: &str, export_name: &str) -> BindingReport {
        BindingReport {
            binding: binding.to_string(),
            export_name: export_name.to_string(),
        }
    }

    fn module_ref(label: &str, residual: bool) -> ModuleReportRef {
        ModuleReportRef {
            id: label.to_string(),
            label: label.to_string(),
            residual,
            index: None,
            target_file: None,
        }
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
            declared_bindings: vec![member(binding, export_name)],
            statement_kind: StatementKind::VarDecl,
            purity: Purity::Pure,
            destination: module_ref("residual", true),
        }
    }

    fn graph_fixture() -> OwnerGraphReport {
        OwnerGraphReport {
            chunk_id: "static/index".to_string(),
            nodes: vec![
                owner("owner:0", 1, "ZZ", "PaymentError"),
                owner("owner:1", 2, "aa", "aa"),
            ],
            edges: vec![OwnerGraphEdgeReport {
                id: "edge:0".to_string(),
                source: "owner:1".to_string(),
                target: "owner:0".to_string(),
                edge_kind: DepKind::EagerUse,
                binding: Some("ZZ".to_string()),
                statement_ordinal: StatementOrdinal(2),
                constrains_init_order: true,
            }],
            quotient: OwnerGraphQuotientReport {
                nodes: Vec::new(),
                edges: Vec::new(),
                sccs: Vec::<QuotientSccReport>::new(),
            },
            peelability: OwnerGraphPeelabilityReport {
                residual_destinations: Vec::new(),
                minimal_peel_sets: vec![OwnerGraphPeelSetReport {
                    candidate_id: "peel_candidate:owner:0".to_string(),
                    owner_ids: vec!["owner:0".to_string()],
                    members: vec![member("ZZ", "PaymentError")],
                    emit_blocked_residual_bindings: Vec::new(),
                }],
                residual_owner_horizon: Vec::new(),
                evaluated_owner_sets: Vec::new(),
            },
            pre_existing_entry_exports: Vec::new(),
            factorize: FactorizeReport {
                size_cap_lines: 10_000,
                residual_owner_count: 2,
                cells: vec![FactorizeCell {
                    proposed_module_id: "factor_0000".to_string(),
                    owner_ids: vec!["owner:0".to_string()],
                    binding_ids: vec!["ZZ".to_string()],
                    anonymous_statement_owner_ids: Vec::new(),
                    size_lines_estimate: 1,
                    size_members: 1,
                    source_line_range: Some([2, 2]),
                    ordinal_span: 1,
                    status: PeelCandidateStatus::PeelableNow,
                    landable_today: true,
                    emit_blocked_residual_bindings: Vec::new(),
                    cycle_blocker_owner_ids: Vec::new(),
                    active_modules_referenced: Vec::new(),
                    extends_module_id: None,
                    extension_owner_ids: Vec::new(),
                }],
                diagnostics: Vec::new(),
            },
        }
    }

    fn fixture() -> (TempDir, CommonArgs) {
        let temp = tempfile::tempdir().unwrap();
        let graph_path = temp.path().join("owner_graph.json");
        let modules_root = temp.path().join("spec/modules");
        write(
            &graph_path,
            &serde_json::to_string_pretty(&graph_fixture()).unwrap(),
        );
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

    #[test]
    fn list_candidates_emits_candidates_and_groups() {
        let (_temp, common) = fixture();
        let report = run_list_candidates_report(&ListCandidatesArgs {
            common,
            limit: 0,
            readable_only: true,
            by_destination: true,
        })
        .unwrap();
        assert_eq!(report.candidates.len(), 1);
        assert_eq!(report.candidates[0].members[0].0, "ZZ");
        assert_eq!(report.groups.len(), 1);
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
            },
            size_cap_lines: 10_000,
        })
        .unwrap();
        assert_eq!(report.owner_ids, vec!["owner:0"]);
        assert_eq!(report.incoming_edges.len(), 1);
        assert_eq!(report.neighbor_owners[0].id, "owner:1");
        assert_eq!(report.binding_homes[0].source_kind, "binding_patch");
        assert_eq!(
            report.factorize_proposals[0].proposed_module_id,
            "auto_partition_0000"
        );
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
