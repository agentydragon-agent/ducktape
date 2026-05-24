//! CLI-facing peel proposer over the serialized owner + atomic DAG report.
//!
//! `debundle run` emits stable graph facts only. This crate computes
//! heuristic peel proposals from `OwnerGraphReport.atomic_graph` on demand and
//! annotates them with spec-tree context (active claims) and cell-graph
//! metrics:
//!
//! - `edges_to_active_modules` / `active_modules_referenced`:
//!   outgoing constraining edges from each cell to active-claimed
//!   binding modules (safe references — active modules materialize
//!   before residual_entry).
//! - `internal_edges`, `edges_to_other_residual_cells`,
//!   `other_residual_cells_referenced`: cell-graph relationship
//!   counts derived from the partition the analyzer chose.
//!
//! Diagnostics come through separately. A diagnostic is not a module
//! assignment the author can land as-is.
//!
//! ## Renderer over `QuotientGraph`
//!
//! Commit 1b of `plans/peel_proposer_contraction_model.md` routes
//! proposal emission through the kernel: the cell-discovery pass
//! (`proposal_cells_from_atomic_graph`) materializes today's
//! atomic-DAG-closure cells as a `QuotientGraph` partition (one class
//! per cell, residual catch-alls as singletons), and `emit_proposals`
//! reads class membership through that quotient. Commit 2's greedy
//! plugs into the same kernel by applying additional contractions on
//! top before emission. The output of `factorize` is byte-identical
//! to the pre-kernel binary's output for the same input.

use std::collections::{BTreeMap, BTreeSet, HashMap};
use std::fs;
use std::path::PathBuf;

use anyhow::{Context, Result};
use serde::Serialize;

use analysis::{FactorizeDiagnosticReason, LineRange, OwnerGraphReport, PeelCandidateStatus};
use spec_modules::load_active_claims;

use crate::quotient::{
    ClassId, OwnerIdx, QuotientGraph, SeedContractionRejected, SpecModuleGroup, build_seed_quotient,
};

#[derive(Debug, Clone)]
pub struct PeelFactorizeOptions {
    pub owner_graph_path: PathBuf,
    pub modules_root: PathBuf,
    /// Hard ceiling (in summed source-line counts) per emitted
    /// proposal. Frontiers exceeding the cap appear as diagnostics.
    pub size_cap_lines: usize,
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
pub struct PeelFactorizeReport {
    pub proposals: Vec<FactorizeProposal>,
    pub diagnostics: Vec<FactorizeDiagnosticReport>,
    pub size_cap_lines: usize,
    pub residual_owner_count: usize,
    pub active_claimed_binding_count: usize,
    /// Counts by proposal verdict status.
    /// Keys use the report's stable snake_case status spelling.
    pub status_counts: BTreeMap<String, usize>,
    /// Counts by diagnostic reason. Diagnostics are not module
    /// assignments that can be landed as-is.
    pub diagnostic_counts: BTreeMap<String, usize>,
    /// Proposal size histograms. Each bucket includes total count
    /// plus how many proposals in the bucket are landable today.
    pub size_distributions: FactorizeSizeDistributions,
    /// Per-contraction rejection diagnostics from the seeding
    /// protocol (`peel::quotient::build_seed_quotient`). Empty on
    /// well-formed input; populated when the spec declares an
    /// unrealizable owner grouping. Skipped from JSON output when
    /// empty so existing well-formed fixtures stay byte-identical.
    /// See `plans/peel_proposer_contraction_model.md`.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub seed_rejections: Vec<SeedContractionRejected>,
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
pub struct FactorizeSizeDistributions {
    pub by_members: Vec<FactorizeSizeBucketCount>,
    pub by_lines: Vec<FactorizeSizeBucketCount>,
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
pub struct FactorizeSizeBucketCount {
    pub bucket: String,
    pub count: usize,
    pub landable_count: usize,
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
pub struct FactorizeProposal {
    pub proposed_module_id: String,
    pub owner_ids: Vec<String>,
    /// Bindings declared by the cell's owners. Excludes
    /// anonymous side-effect statements, which appear under
    /// `anonymous_statement_owner_ids` instead.
    pub binding_ids: Vec<String>,
    /// Anonymous side-effect statements (owners with empty
    /// `declared_bindings`) in this cell. Lane workers materialize
    /// these via `anonymous_statements:` entries quoting the
    /// statement's source verbatim — the materializer's cycle
    /// gate counts these statements when determining whether the
    /// cell's promotion would cycle through `residual_entry`.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub anonymous_statement_owner_ids: Vec<String>,
    pub size_lines_estimate: usize,
    /// `[start_line, end_line]` of the lowest-line and highest-line
    /// owner bodies. `None` when none of the cell's owners have
    /// a `source_location`.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub source_line_range: Option<[usize; 2]>,
    pub ordinal_span: usize,
    pub internal_edges: usize,
    /// Edges from this cell to OTHER residual cells. Cycle-risk
    /// edges: promoting this cell to active while the pointed-at
    /// residual cells stay residual would create `<this>` →
    /// `residual_entry` reads, which the cycle gate will reject.
    pub edges_to_other_residual_cells: usize,
    /// Other residual cells (by proposed_module_id) this cell's
    /// outgoing constraining edges target.
    pub other_residual_cells_referenced: Vec<String>,
    /// Edges from this cell to active-claimed bindings. Safe:
    /// active modules materialize before residual_entry, so reads
    /// to them don't cycle. Informational.
    pub edges_to_active_modules: usize,
    /// Active module paths this cell's outgoing constraining edges
    /// target (deduplicated).
    pub active_modules_referenced: Vec<String>,
    /// Should be empty for certified proposals. Kept for defensive
    /// compatibility with older reports.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub cycle_blocker_owner_ids: Vec<String>,
    /// Proposal verdict for this closed atomic-unit owner set.
    pub status: PeelCandidateStatus,
    /// `true` for atomic-DAG-closed proposal cells.
    pub landable_today: bool,
    /// When this proposal extends an existing active module, this carries the
    /// active module id. `None` for fresh-module proposals.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub extends_module_id: Option<String>,
    /// Loose owner ids (residual today) that would be added to
    /// `extends_module_id`. Empty for fresh-module proposals.
    pub extension_owner_ids: Vec<String>,
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
pub struct FactorizeDiagnosticReport {
    pub diagnostic_id: String,
    pub owner_ids: Vec<String>,
    pub binding_ids: Vec<String>,
    pub size_lines_estimate: usize,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub source_line_range: Option<[usize; 2]>,
    pub ordinal_span: usize,
    pub status: PeelCandidateStatus,
    pub reason: FactorizeDiagnosticReason,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub cycle_blocker_owner_ids: Vec<String>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub active_modules_referenced: Vec<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub extends_module_id: Option<String>,
}

pub fn analyze_peel_factorize(options: &PeelFactorizeOptions) -> Result<PeelFactorizeReport> {
    let graph: OwnerGraphReport = serde_json::from_str(
        &fs::read_to_string(&options.owner_graph_path)
            .with_context(|| format!("reading {}", options.owner_graph_path.display()))?,
    )
    .with_context(|| format!("parsing {}", options.owner_graph_path.display()))?;
    let claims = load_active_claims(&options.modules_root)?;
    Ok(factorize(&graph, &claims, options.size_cap_lines))
}

pub fn factorize(
    graph: &OwnerGraphReport,
    active_claims: &BTreeMap<String, String>,
    size_cap_lines: usize,
) -> PeelFactorizeReport {
    let owner_index: HashMap<&str, usize> = graph
        .nodes
        .iter()
        .enumerate()
        .map(|(i, node)| (node.id.as_str(), i))
        .collect();

    let residual: BTreeSet<usize> = graph
        .nodes
        .iter()
        .enumerate()
        .filter(|(_, node)| node.destination.residual)
        .map(|(i, _)| i)
        .collect();

    let owner_to_active_module: HashMap<usize, String> = graph
        .nodes
        .iter()
        .enumerate()
        .filter_map(|(i, node)| {
            if node.destination.residual {
                return None;
            }
            let path = node
                .declared_bindings
                .iter()
                .find_map(|b| active_claims.get(b.binding.as_str()))
                .cloned()
                .or_else(|| node.destination.target_file.clone())
                .unwrap_or_else(|| node.destination.label.clone());
            Some((i, path))
        })
        .collect();

    let (quotient, cell_records, diagnostics) =
        proposal_cells_from_atomic_graph(graph, &owner_index, size_cap_lines);

    // Per-cell edge accounting. We walk every constraining edge
    // once, classifying the source-cell / target-cell pair into:
    // - internal (same cell, residual)            → cell.internal_edges
    // - inter-residual (different residual cells) → cell.edges_to_other_residual_cells
    // - cell → active claim                       → cell.edges_to_active_modules
    let mut residual_constraining_edges: Vec<(usize, usize)> = Vec::new();
    let mut edges_to_active: Vec<(usize, String)> = Vec::new();
    for edge in &graph.edges {
        if !edge.constrains_init_order {
            continue;
        }
        let (Some(&source), Some(&target)) = (
            owner_index.get(edge.source.as_str()),
            owner_index.get(edge.target.as_str()),
        ) else {
            continue;
        };
        if !residual.contains(&source) || source == target {
            continue;
        }
        if residual.contains(&target) {
            residual_constraining_edges.push((source, target));
        } else if let Some(module_path) = owner_to_active_module.get(&target) {
            edges_to_active.push((source, module_path.clone()));
        }
    }

    let proposals = emit_proposals(
        &quotient,
        &cell_records,
        &residual_constraining_edges,
        &edges_to_active,
        graph,
    );
    let status_counts = status_counts(&proposals);
    let diagnostic_counts = diagnostic_counts(&diagnostics);
    let size_distributions = size_distributions(&proposals);
    let seed_rejections = compute_seed_rejections(graph, size_cap_lines);
    PeelFactorizeReport {
        proposals,
        diagnostics,
        size_cap_lines,
        residual_owner_count: residual.len(),
        active_claimed_binding_count: active_claims.len(),
        status_counts,
        diagnostic_counts,
        size_distributions,
        seed_rejections,
    }
}

/// Build the seed quotient under the kernel and surface any rejected
/// forced contractions. The quotient is constructed but not yet used
/// to drive emission — today's `emit_proposals` path remains the
/// renderer. Commit 2 enables greedy merges off this quotient; for
/// commit 1 the kernel runs alongside `emit_proposals` as a
/// pure-side-effect diagnostic.
///
/// Spec-module groups for the kernel come from grouping owners by
/// their active destination (the same view `factorize` uses to label
/// extensions). Owners whose destination is residual stay
/// singletons; the kernel never tries to contract them with each
/// other at this stage.
fn compute_seed_rejections(
    graph: &OwnerGraphReport,
    cap_lines: usize,
) -> Vec<SeedContractionRejected> {
    // Group owners by their declared active destination. Residual
    // owners are skipped — they're singletons in the spec.
    let mut groups: BTreeMap<String, Vec<String>> = BTreeMap::new();
    for node in &graph.nodes {
        if node.destination.residual {
            continue;
        }
        groups
            .entry(node.destination.id.clone())
            .or_default()
            .push(node.id.clone());
    }
    let spec_modules: Vec<SpecModuleGroup> = groups
        .into_iter()
        .map(|(module_id, mut owner_ids)| {
            owner_ids.sort();
            SpecModuleGroup {
                module_id,
                owner_ids,
            }
        })
        .collect();

    let (_q, rejected) =
        build_seed_quotient(graph, &graph.atomic_graph.nodes, &spec_modules, cap_lines);
    rejected
}

/// Build the seed quotient (kernel-state-only entry-point) for
/// callers that want to inspect the equivalence classes without
/// running the full proposal-emission pipeline. Used by future
/// commits (greedy merge step) and by tests.
pub fn build_factorize_seed_quotient(
    graph: &OwnerGraphReport,
    cap_lines: usize,
) -> (QuotientGraph, Vec<SeedContractionRejected>) {
    let mut groups: BTreeMap<String, Vec<String>> = BTreeMap::new();
    for node in &graph.nodes {
        if node.destination.residual {
            continue;
        }
        groups
            .entry(node.destination.id.clone())
            .or_default()
            .push(node.id.clone());
    }
    let spec_modules: Vec<SpecModuleGroup> = groups
        .into_iter()
        .map(|(module_id, mut owner_ids)| {
            owner_ids.sort();
            SpecModuleGroup {
                module_id,
                owner_ids,
            }
        })
        .collect();
    build_seed_quotient(graph, &graph.atomic_graph.nodes, &spec_modules, cap_lines)
}

/// Compute the atomic-DAG-reachability-closure cells that today's
/// proposer renders into proposals, then construct a `QuotientGraph`
/// whose equivalence classes are exactly those cells.
///
/// Returns:
/// - the cells-derived quotient (residual atomic-unit closures
///   contracted into single classes; unaffected owners remain
///   singletons),
/// - a list of `CellClassRecord` (one per emitted cell, in the same
///   order today's pipeline produces) carrying the class id, the
///   `extends_module_id`/`extension_owner_idxs` metadata, and the
///   atomic-DAG-closure verdict,
/// - the diagnostic list for cells that fail the active-module or
///   size-cap gate.
///
/// This is the **Path B** implementation of commit 1b in
/// `plans/peel_proposer_contraction_model.md`: today's cell
/// semantics (transitive closure over atomic-DAG edges to
/// residual-containing units, with overlap coalescing) is preserved
/// verbatim; the kernel hosts the resulting partition as a quotient
/// so the renderer (`emit_proposals`) reads class membership
/// uniformly. Commit 2's greedy will plug in on top of this same
/// quotient.
fn proposal_cells_from_atomic_graph(
    graph: &OwnerGraphReport,
    owner_index: &HashMap<&str, usize>,
    size_cap_lines: usize,
) -> (
    QuotientGraph,
    Vec<CellClassRecord>,
    Vec<FactorizeDiagnosticReport>,
) {
    let unit_index: HashMap<&str, usize> = graph
        .atomic_graph
        .nodes
        .iter()
        .enumerate()
        .map(|(idx, unit)| (unit.id.as_str(), idx))
        .collect();
    let mut owner_to_unit = HashMap::<usize, usize>::new();
    for (unit_idx, unit) in graph.atomic_graph.nodes.iter().enumerate() {
        for owner_id in &unit.owner_ids {
            if let Some(&owner_idx) = owner_index.get(owner_id.as_str()) {
                owner_to_unit.insert(owner_idx, unit_idx);
            }
        }
    }
    let unit_has_residual: Vec<bool> = graph
        .atomic_graph
        .nodes
        .iter()
        .map(|unit| unit.destinations.iter().any(|dest| dest.residual))
        .collect();
    let mut outgoing_residual_units =
        vec![BTreeSet::<usize>::new(); graph.atomic_graph.nodes.len()];
    for edge in &graph.atomic_graph.edges {
        if !edge.constrains_init_order {
            continue;
        }
        let (Some(&source), Some(&target)) = (
            unit_index.get(edge.source.as_str()),
            unit_index.get(edge.target.as_str()),
        ) else {
            continue;
        };
        if source != target && unit_has_residual.get(target).copied().unwrap_or(false) {
            outgoing_residual_units[source].insert(target);
        }
    }

    let mut closed_sets: Vec<BTreeSet<usize>> = (0..graph.atomic_graph.nodes.len())
        .filter(|&start| unit_has_residual[start])
        .map(|start| close_residual_units(start, &outgoing_residual_units))
        .collect();
    coalesce_overlapping_sets(&mut closed_sets);

    // First pass: classify each cell into "diagnostic" or
    // "renderable" (= one cell-class in the quotient). Build the
    // owner-index partition (`render_groups`) for the kernel.
    let mut diagnostics = Vec::<FactorizeDiagnosticReport>::new();
    let mut render_groups: Vec<Vec<OwnerIdx>> = Vec::new();
    let mut render_metadata: Vec<RenderCellMetadata> = Vec::new();
    let mut seen = BTreeSet::<(Option<String>, Vec<usize>)>::new();
    for closed_units in closed_sets {
        let cell = cell_from_units(graph, owner_index, &closed_units);
        if cell.owners.is_empty() {
            continue;
        }
        let active_destinations = active_destinations_for_cell(graph, &cell.owners);
        if active_destinations.len() > 1 {
            diagnostics.push(diagnostic_from_cell(
                diagnostics.len(),
                &cell,
                graph,
                PeelCandidateStatus::BlockedCycle,
                FactorizeDiagnosticReason::ActiveModuleConflict,
                active_destinations.into_iter().collect(),
            ));
            continue;
        }
        let mut cell = cell;
        cell.extends_module_id = active_destinations.first().cloned();
        if cell.extends_module_id.is_some() {
            cell.extension_owner_idxs = cell
                .owners
                .iter()
                .copied()
                .filter(|idx| graph.nodes[*idx].destination.residual)
                .collect();
        }
        let key_owners: Vec<usize> = cell.owners.iter().copied().collect();
        if !seen.insert((cell.extends_module_id.clone(), key_owners)) {
            continue;
        }
        if cell.lines > size_cap_lines {
            diagnostics.push(diagnostic_from_cell(
                diagnostics.len(),
                &cell,
                graph,
                PeelCandidateStatus::BlockedResidualDependency,
                FactorizeDiagnosticReason::ExceedsSizeCap,
                Vec::new(),
            ));
            continue;
        }
        let group: Vec<OwnerIdx> = cell.owners.iter().map(|&idx| OwnerIdx(idx)).collect();
        render_groups.push(group);
        render_metadata.push(RenderCellMetadata {
            extends_module_id: cell.extends_module_id,
            extension_owner_idxs: cell.extension_owner_idxs,
            verdict: Verdict {
                status: PeelCandidateStatus::PeelableNow,
                landable_today: true,
                cycle_blocker_owner_ids: Vec::new(),
            },
        });
    }

    // Materialize the partition into a quotient. The kernel hosts the
    // equivalence relation; the renderer reads class members through
    // `quotient.class_members`.
    let (quotient, group_class_ids) =
        QuotientGraph::from_report_with_partition(graph, size_cap_lines, &render_groups);
    let cell_records: Vec<CellClassRecord> = render_metadata
        .into_iter()
        .zip(group_class_ids)
        .map(|(meta, class_id)| CellClassRecord {
            class_id,
            extends_module_id: meta.extends_module_id,
            extension_owner_idxs: meta.extension_owner_idxs,
            verdict: meta.verdict,
        })
        .collect();
    (quotient, cell_records, diagnostics)
}

/// Cell-class record passed to `emit_proposals`. The class id refers
/// into the cells-derived quotient. Extension metadata is derived
/// from owner destinations at cell-discovery time and survives the
/// refactor unchanged.
#[derive(Debug, Clone)]
struct CellClassRecord {
    class_id: ClassId,
    extends_module_id: Option<String>,
    extension_owner_idxs: BTreeSet<usize>,
    verdict: Verdict,
}

struct RenderCellMetadata {
    extends_module_id: Option<String>,
    extension_owner_idxs: BTreeSet<usize>,
    verdict: Verdict,
}

fn close_residual_units(
    start: usize,
    outgoing_residual_units: &[BTreeSet<usize>],
) -> BTreeSet<usize> {
    let mut closed = BTreeSet::from([start]);
    let mut stack = vec![start];
    while let Some(unit) = stack.pop() {
        for &target in &outgoing_residual_units[unit] {
            if closed.insert(target) {
                stack.push(target);
            }
        }
    }
    closed
}

fn coalesce_overlapping_sets(sets: &mut Vec<BTreeSet<usize>>) {
    let mut changed = true;
    while changed {
        changed = false;
        'outer: for left in 0..sets.len() {
            for right in (left + 1)..sets.len() {
                if sets[left].is_disjoint(&sets[right]) {
                    continue;
                }
                let merged = sets.remove(right);
                sets[left].extend(merged);
                changed = true;
                break 'outer;
            }
        }
    }
    sets.sort();
}

fn cell_from_units(
    graph: &OwnerGraphReport,
    owner_index: &HashMap<&str, usize>,
    unit_indices: &BTreeSet<usize>,
) -> Cell {
    let mut owners = BTreeSet::<usize>::new();
    for &unit_idx in unit_indices {
        let Some(unit) = graph.atomic_graph.nodes.get(unit_idx) else {
            continue;
        };
        for owner_id in &unit.owner_ids {
            if let Some(&owner_idx) = owner_index.get(owner_id.as_str()) {
                owners.insert(owner_idx);
            }
        }
    }
    let lines = owners
        .iter()
        .map(|&idx| owner_line_count(&graph.nodes[idx]))
        .sum();
    Cell {
        owners,
        lines,
        extends_module_id: None,
        extension_owner_idxs: BTreeSet::new(),
    }
}

fn active_destinations_for_cell(
    graph: &OwnerGraphReport,
    owners: &BTreeSet<usize>,
) -> BTreeSet<String> {
    owners
        .iter()
        .filter_map(|&idx| {
            let dest = &graph.nodes[idx].destination;
            (!dest.residual).then(|| dest.id.clone())
        })
        .collect()
}

fn diagnostic_from_cell(
    idx: usize,
    cell: &Cell,
    graph: &OwnerGraphReport,
    status: PeelCandidateStatus,
    reason: FactorizeDiagnosticReason,
    active_modules_referenced: Vec<String>,
) -> FactorizeDiagnosticReport {
    // Diagnostics never reach the renderer-over-quotient path; they
    // close before a class is allocated. Compute the same surface
    // fields directly from the cell's owners.
    let mut owner_ids: Vec<String> = Vec::with_capacity(cell.owners.len());
    let mut binding_ids: BTreeSet<String> = BTreeSet::new();
    let mut line_range = LineRange::new();
    let mut max_ordinal = 0usize;
    let mut min_ordinal = usize::MAX;
    for &owner_idx in &cell.owners {
        let node = &graph.nodes[owner_idx];
        owner_ids.push(node.id.clone());
        for binding in &node.declared_bindings {
            binding_ids.insert(binding.binding.to_string());
        }
        if let Some(loc) = &node.source_location {
            line_range.expand(loc);
        }
        min_ordinal = min_ordinal.min(node.statement_ordinal.0);
        max_ordinal = max_ordinal.max(node.statement_ordinal.0);
    }
    owner_ids.sort();
    FactorizeDiagnosticReport {
        diagnostic_id: format!("diagnostic:{}_{idx:04}", diagnostic_reason_key(reason)),
        owner_ids,
        binding_ids: binding_ids.into_iter().collect(),
        size_lines_estimate: cell.lines,
        source_line_range: line_range.into_array(),
        ordinal_span: max_ordinal.saturating_sub(min_ordinal),
        status,
        reason,
        cycle_blocker_owner_ids: Vec::new(),
        active_modules_referenced,
        extends_module_id: cell.extends_module_id.clone(),
    }
}

/// Intermediate representation of one atomic-DAG-reachability
/// closure produced by `proposal_cells_from_atomic_graph`. Used to
/// classify the closure into "diagnostic-bound" (active-module
/// conflict, exceeds size cap) vs "renderable" and to materialize
/// the resulting partition into a `QuotientGraph`. The renderer
/// (`emit_proposals`) does not see `Cell`; it reads class membership
/// directly from the quotient.
#[derive(Debug, Clone)]
struct Cell {
    owners: BTreeSet<usize>,
    lines: usize,
    extends_module_id: Option<String>,
    extension_owner_idxs: BTreeSet<usize>,
}

/// Per-cell gate result from the atomic-DAG closure. Attached to
/// each `CellClassRecord` so the renderer can stamp the proposal
/// with the cell-discovery pass's verdict.
#[derive(Debug, Clone)]
struct Verdict {
    status: PeelCandidateStatus,
    landable_today: bool,
    cycle_blocker_owner_ids: Vec<String>,
}

fn owner_line_count(node: &analysis::OwnerGraphNodeReport) -> usize {
    node.source_location
        .as_ref()
        .map(|loc| {
            loc.end_line
                .saturating_sub(loc.start_line)
                .saturating_add(1)
        })
        .unwrap_or(0)
}

struct ProposalContext<'a> {
    graph: &'a OwnerGraphReport,
    quotient: &'a QuotientGraph,
    residual_edges: &'a [(usize, usize)],
    active_edges: &'a [(usize, String)],
    /// Map from owner-index to the cell-record index whose class
    /// contains this owner. Owners not in any rendered cell-class
    /// are absent from the map.
    owner_to_cell: HashMap<usize, usize>,
}

fn emit_proposals(
    quotient: &QuotientGraph,
    cell_records: &[CellClassRecord],
    residual_edges: &[(usize, usize)],
    active_edges: &[(usize, String)],
    graph: &OwnerGraphReport,
) -> Vec<FactorizeProposal> {
    // Build owner-to-cell from the quotient's class memberships,
    // keyed by cell-record index (not class id). The renderer's
    // edge-attribution logic treats cells as units; it doesn't need
    // class ids, just per-cell identity.
    let mut owner_to_cell: HashMap<usize, usize> = HashMap::new();
    for (cell_idx, record) in cell_records.iter().enumerate() {
        for owner in quotient.class_members(record.class_id) {
            owner_to_cell.insert(owner.0, cell_idx);
        }
    }

    let ctx = ProposalContext {
        graph,
        quotient,
        residual_edges,
        active_edges,
        owner_to_cell,
    };

    let mut proposals: Vec<FactorizeProposal> = cell_records
        .iter()
        .enumerate()
        .map(|(cell_idx, record)| build_proposal(cell_idx, record, &ctx))
        .collect();

    // Residual-dependency depth sort with source-line tie-break.
    // Certified analyzer output normally has no outgoing residual
    // constraining edges; this still keeps legacy/synthetic reports
    // deterministic.
    let depths = compute_topo_depths(cell_records.len(), residual_edges, &ctx.owner_to_cell);
    let mut indexed: Vec<(usize, FactorizeProposal)> = proposals.drain(..).enumerate().collect();
    indexed.sort_by(|(li, left), (ri, right)| {
        depths[*li].cmp(&depths[*ri]).then_with(|| {
            let lk = left
                .source_line_range
                .map(|range| range[0])
                .unwrap_or(usize::MAX);
            let rk = right
                .source_line_range
                .map(|range| range[0])
                .unwrap_or(usize::MAX);
            lk.cmp(&rk)
        })
    });

    // After topo-sort the cells are renumbered; rebuild the original
    // cell_idx → new_idx map so cross-references inside the
    // `other_residual_cells_referenced` lists point at the right
    // post-sort module IDs.
    let new_id_for: HashMap<usize, usize> = indexed
        .iter()
        .enumerate()
        .map(|(new_idx, (orig_idx, _))| (*orig_idx, new_idx))
        .collect();
    let mut out: Vec<FactorizeProposal> = indexed.into_iter().map(|(_, p)| p).collect();
    for proposal in out.iter_mut() {
        promote_anonymous_only_cell_to_extension(proposal);
    }
    let mut fresh_counter = 0usize;
    for proposal in out.iter_mut() {
        if proposal.extends_module_id.is_none() {
            proposal.proposed_module_id = format!("auto_partition_{fresh_counter:04}");
            fresh_counter += 1;
        }
        proposal.other_residual_cells_referenced = proposal
            .other_residual_cells_referenced
            .iter()
            .filter_map(|old_id| {
                let old_idx: usize = old_id.strip_prefix("auto_partition_")?.parse().ok()?;
                new_id_for
                    .get(&old_idx)
                    .map(|i| format!("auto_partition_{i:04}"))
            })
            .collect();
    }
    out
}

/// Promote an anonymous-only fresh-module cell into an extension of
/// the single active module its constraining edges target.
///
/// Motivation: top-level side-effect statements (`__decorate(...)`,
/// `register(...)`, target-mutating `Foo.x = ...` installs, IIFE
/// preludes) declare no binding name, so the spec author has no way
/// to claim them by name. When the named binding they apply to is
/// already in an active module, the natural spec edit is "extend
/// that module with these `anonymous_statements:`". Without this
/// promotion the planner just reports them as fresh
/// `auto_partition_NNNN` proposals and the author has to spot them
/// by hand.
///
/// Preconditions for promotion (all required):
/// - `extends_module_id` is `None` (cell is a fresh-module proposal today).
/// - `binding_ids` is empty (cell has no named bindings — promoting a
///   cell with named bindings would force them into an existing
///   module's `members:` list, which is a different spec edit and
///   needs the author's judgement on naming).
/// - `edges_to_other_residual_cells == 0` (the cell has no
///   leftover residual dependency; promoting wouldn't strand the
///   extension behind another residual cell).
/// - `active_modules_referenced.len() == 1` and
///   `edges_to_active_modules > 0` (every outgoing cross-module
///   constraining edge points at exactly one active module — the
///   unambiguous extension target).
fn promote_anonymous_only_cell_to_extension(proposal: &mut FactorizeProposal) {
    if proposal.extends_module_id.is_some()
        || !proposal.binding_ids.is_empty()
        || proposal.edges_to_other_residual_cells != 0
        || proposal.edges_to_active_modules == 0
        || proposal.active_modules_referenced.len() != 1
    {
        return;
    }
    let target = proposal.active_modules_referenced[0].clone();
    proposal.extends_module_id = Some(target.clone());
    proposal.proposed_module_id = format!("extend:{target}");
    // The cell's owners are anonymous-only by precondition
    // (`binding_ids` empty + every owner with no declared bindings
    // contributed to `anonymous_statement_owner_ids` in
    // `build_proposal`). Surface them in `extension_owner_ids`
    // alongside the named-binding case so a downstream consumer
    // reading the proposal can materialize the spec edit
    // ("add these anonymous_statements to <target>.yaml") off
    // a single field, distinguishing kinds by checking owner shape
    // (named vs anonymous) on each id.
    let mut ids = proposal.owner_ids.clone();
    ids.sort();
    proposal.extension_owner_ids = ids;
}

fn compute_topo_depths(
    cell_count: usize,
    residual_edges: &[(usize, usize)],
    owner_to_cell: &HashMap<usize, usize>,
) -> Vec<usize> {
    let mut adj: Vec<BTreeSet<usize>> = vec![BTreeSet::new(); cell_count];
    for &(s, t) in residual_edges {
        let (Some(&cs), Some(&ct)) = (owner_to_cell.get(&s), owner_to_cell.get(&t)) else {
            continue;
        };
        if cs != ct {
            adj[cs].insert(ct);
        }
    }
    let mut depths = vec![None; cell_count];
    fn dfs(node: usize, adj: &[BTreeSet<usize>], depths: &mut [Option<usize>]) -> usize {
        if let Some(d) = depths[node] {
            return d;
        }
        // Mark as in-progress with depth 0. If a legacy/synthetic
        // report contains an inter-cell cycle, the sort remains
        // deterministic instead of recursing forever.
        depths[node] = Some(0);
        let max_child = adj[node]
            .iter()
            .map(|&child| dfs(child, adj, depths))
            .max()
            .map(|d| d + 1)
            .unwrap_or(0);
        depths[node] = Some(max_child);
        max_child
    }
    for i in 0..cell_count {
        dfs(i, &adj, &mut depths);
    }
    depths.into_iter().map(|d| d.unwrap_or(0)).collect()
}

fn build_proposal(
    cell_idx: usize,
    record: &CellClassRecord,
    ctx: &ProposalContext,
) -> FactorizeProposal {
    // Class members come from the quotient. The renderer treats the
    // class as the unit of emission — exactly what commit 2's greedy
    // will produce after additional contractions.
    let class_id = record.class_id;
    let owner_idxs: Vec<usize> = ctx.quotient.class_members(class_id).map(|o| o.0).collect();
    let class_lines = ctx.quotient.class_lines(class_id);

    let mut owner_ids: Vec<String> = Vec::with_capacity(owner_idxs.len());
    let mut anonymous_owner_ids: Vec<String> = Vec::new();
    let mut binding_ids: BTreeSet<String> = BTreeSet::new();
    let mut line_range = LineRange::new();
    let mut max_ordinal = 0usize;
    let mut min_ordinal = usize::MAX;
    for &owner_idx in &owner_idxs {
        let node = &ctx.graph.nodes[owner_idx];
        owner_ids.push(node.id.clone());
        if node.declared_bindings.is_empty() {
            anonymous_owner_ids.push(node.id.clone());
        }
        for binding in &node.declared_bindings {
            binding_ids.insert(binding.binding.to_string());
        }
        if let Some(loc) = &node.source_location {
            line_range.expand(loc);
        }
        min_ordinal = min_ordinal.min(node.statement_ordinal.0);
        max_ordinal = max_ordinal.max(node.statement_ordinal.0);
    }
    owner_ids.sort();
    anonymous_owner_ids.sort();

    let mut internal = 0usize;
    let mut to_residual = 0usize;
    let mut residual_targets: BTreeSet<usize> = BTreeSet::new();
    for &(s, t) in ctx.residual_edges {
        let (Some(&cs), Some(&ct)) = (ctx.owner_to_cell.get(&s), ctx.owner_to_cell.get(&t)) else {
            continue;
        };
        if cs == cell_idx && ct == cell_idx {
            internal += 1;
        } else if cs == cell_idx {
            to_residual += 1;
            residual_targets.insert(ct);
        }
    }
    let other_residual_cells_referenced: Vec<String> = residual_targets
        .into_iter()
        .map(|idx| format!("auto_partition_{idx:04}"))
        .collect();

    let mut to_active = 0usize;
    let mut active_targets: BTreeSet<String> = BTreeSet::new();
    for (source_owner, module_path) in ctx.active_edges {
        if ctx.owner_to_cell.get(source_owner) == Some(&cell_idx) {
            to_active += 1;
            active_targets.insert(module_path.clone());
        }
    }
    let active_modules_referenced: Vec<String> = active_targets.into_iter().collect();

    // `status`, `landable_today`, and blocker lists come from the atomic-DAG
    // closure pass in this CLI invocation.
    let cycle_blocker_owner_ids = record.verdict.cycle_blocker_owner_ids.clone();
    let extension_owner_ids: Vec<String> = {
        let mut ids: Vec<String> = record
            .extension_owner_idxs
            .iter()
            .map(|&idx| ctx.graph.nodes[idx].id.clone())
            .collect();
        ids.sort();
        ids
    };
    let proposed_module_id = match &record.extends_module_id {
        Some(target) => format!("extend:{target}"),
        None => format!("auto_partition_{cell_idx:04}"),
    };
    FactorizeProposal {
        proposed_module_id,
        owner_ids,
        binding_ids: binding_ids.into_iter().collect(),
        anonymous_statement_owner_ids: anonymous_owner_ids,
        size_lines_estimate: class_lines,
        source_line_range: line_range.into_array(),
        ordinal_span: max_ordinal.saturating_sub(min_ordinal),
        internal_edges: internal,
        edges_to_other_residual_cells: to_residual,
        other_residual_cells_referenced,
        edges_to_active_modules: to_active,
        active_modules_referenced,
        cycle_blocker_owner_ids,
        status: record.verdict.status,
        landable_today: record.verdict.landable_today,
        extends_module_id: record.extends_module_id.clone(),
        extension_owner_ids,
    }
}

fn status_counts(proposals: &[FactorizeProposal]) -> BTreeMap<String, usize> {
    let mut counts = BTreeMap::new();
    for proposal in proposals {
        *counts
            .entry(status_key(proposal.status).to_string())
            .or_insert(0) += 1;
    }
    counts
}

fn diagnostic_counts(diagnostics: &[FactorizeDiagnosticReport]) -> BTreeMap<String, usize> {
    let mut counts = BTreeMap::new();
    for diagnostic in diagnostics {
        *counts
            .entry(diagnostic_reason_key(diagnostic.reason).to_string())
            .or_insert(0) += 1;
    }
    counts
}

fn size_distributions(proposals: &[FactorizeProposal]) -> FactorizeSizeDistributions {
    FactorizeSizeDistributions {
        by_members: bucket_counts(proposals, |proposal| proposal.owner_ids.len(), size_bucket),
        by_lines: bucket_counts(
            proposals,
            |proposal| proposal.size_lines_estimate,
            size_bucket,
        ),
    }
}

fn bucket_counts(
    proposals: &[FactorizeProposal],
    value: fn(&FactorizeProposal) -> usize,
    bucket: fn(usize) -> &'static str,
) -> Vec<FactorizeSizeBucketCount> {
    const SIZE_BUCKETS: &[&str] = &[
        "0", "1", "2", "3-5", "6-10", "11-20", "21-50", "51-100", "101-250", "251-500", "501-1000",
        ">1000",
    ];
    let mut counts: BTreeMap<&'static str, (usize, usize)> = BTreeMap::new();
    for proposal in proposals {
        let entry = counts.entry(bucket(value(proposal))).or_default();
        entry.0 += 1;
        if proposal.landable_today {
            entry.1 += 1;
        }
    }
    SIZE_BUCKETS
        .iter()
        .filter_map(|bucket| {
            counts
                .get(bucket)
                .map(|(count, landable_count)| FactorizeSizeBucketCount {
                    bucket: (*bucket).to_string(),
                    count: *count,
                    landable_count: *landable_count,
                })
        })
        .collect()
}

fn size_bucket(value: usize) -> &'static str {
    match value {
        0 => "0",
        1 => "1",
        2 => "2",
        3..=5 => "3-5",
        6..=10 => "6-10",
        11..=20 => "11-20",
        21..=50 => "21-50",
        51..=100 => "51-100",
        101..=250 => "101-250",
        251..=500 => "251-500",
        501..=1000 => "501-1000",
        _ => ">1000",
    }
}

fn status_key(status: PeelCandidateStatus) -> &'static str {
    match status {
        PeelCandidateStatus::PeelableNow => "peelable_now",
        PeelCandidateStatus::BlockedCycle => "blocked_cycle",
        PeelCandidateStatus::BlockedResidualDependency => "blocked_residual_dependency",
    }
}

fn diagnostic_reason_key(reason: FactorizeDiagnosticReason) -> &'static str {
    match reason {
        FactorizeDiagnosticReason::ExceedsSizeCap => "exceeds_size_cap",
        FactorizeDiagnosticReason::NoExactRepair => "no_exact_repair",
        FactorizeDiagnosticReason::ActiveModuleConflict => "active_module_conflict",
        FactorizeDiagnosticReason::RepeatedFrontier => "repeated_frontier",
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use swc_atoms::Atom;

    use analysis::{
        AtomicGraphReport, AtomicUnitEdgeReport, AtomicUnitReport, DepKind, ModuleReportRef,
        OwnerGraphEdgeReport, OwnerGraphNodeReport, OwnerGraphQuotientReport, OwnerGraphReport,
        Purity, SourceLocation, StatementKind, StatementOrdinal,
    };

    use super::super::test_utils;

    fn owner(
        id: &str,
        ordinal_value: usize,
        bindings: &[&str],
        lines: usize,
    ) -> OwnerGraphNodeReport {
        owner_at(
            id,
            ordinal_value,
            bindings,
            lines,
            test_utils::module_ref("logical:residual", true),
        )
    }

    fn owner_in_active_module(
        id: &str,
        ordinal_value: usize,
        bindings: &[&str],
        lines: usize,
        module_path: &str,
    ) -> OwnerGraphNodeReport {
        owner_at(
            id,
            ordinal_value,
            bindings,
            lines,
            test_utils::module_ref(module_path, false),
        )
    }

    fn owner_at(
        id: &str,
        ordinal_value: usize,
        bindings: &[&str],
        lines: usize,
        destination: ModuleReportRef,
    ) -> OwnerGraphNodeReport {
        OwnerGraphNodeReport {
            id: id.to_string(),
            statement_ordinal: StatementOrdinal(ordinal_value),
            source_location: Some(SourceLocation {
                source_path: "x.js".to_string(),
                start_line: ordinal_value * 100,
                end_line: ordinal_value * 100 + lines.saturating_sub(1),
            }),
            declared_bindings: bindings.iter().map(|b| test_utils::binding(b)).collect(),
            statement_kind: StatementKind::VarDecl,
            purity: Purity::Pure,
            destination,
        }
    }

    fn edge(
        id: &str,
        source: &str,
        target: &str,
        kind: DepKind,
        constrains: bool,
    ) -> OwnerGraphEdgeReport {
        edge_for_binding(id, source, target, kind, constrains, None)
    }

    fn edge_for_binding(
        id: &str,
        source: &str,
        target: &str,
        kind: DepKind,
        constrains: bool,
        binding: Option<&str>,
    ) -> OwnerGraphEdgeReport {
        OwnerGraphEdgeReport {
            id: id.to_string(),
            source: source.to_string(),
            target: target.to_string(),
            edge_kind: kind,
            binding: binding.map(Atom::from),
            statement_ordinal: StatementOrdinal(0),
            constrains_init_order: constrains,
        }
    }

    fn unit(id: &str, owners: &[&OwnerGraphNodeReport]) -> AtomicUnitReport {
        let mut owner_ids = Vec::new();
        let mut members = Vec::new();
        let mut destinations = BTreeMap::<String, ModuleReportRef>::new();
        let mut line_range = LineRange::new();
        let mut min_ordinal = usize::MAX;
        let mut max_ordinal = 0usize;
        for owner in owners {
            owner_ids.push(owner.id.clone());
            members.extend(owner.declared_bindings.clone());
            destinations.insert(owner.destination.id.clone(), owner.destination.clone());
            if let Some(location) = &owner.source_location {
                line_range.expand(location);
            }
            min_ordinal = min_ordinal.min(owner.statement_ordinal.0);
            max_ordinal = max_ordinal.max(owner.statement_ordinal.0);
        }
        AtomicUnitReport {
            id: id.to_string(),
            owner_ids,
            members,
            anonymous_statement_owner_ids: Vec::new(),
            destinations: destinations.into_values().collect(),
            causes: Vec::new(),
            size_lines_estimate: line_range.size_estimate(),
            source_line_range: line_range.into_array(),
            ordinal_span: max_ordinal.saturating_sub(min_ordinal),
        }
    }

    fn atomic_edge(id: &str, source: &str, target: &str) -> AtomicUnitEdgeReport {
        AtomicUnitEdgeReport {
            id: id.to_string(),
            source: source.to_string(),
            target: target.to_string(),
            edge_kinds: vec![DepKind::EagerUse],
            owner_edge_ids: vec![id.replace("atomic", "edge")],
            constrains_init_order: true,
        }
    }

    fn graph_with_atomic_units(
        nodes: Vec<OwnerGraphNodeReport>,
        edges: Vec<OwnerGraphEdgeReport>,
        atomic_units: Vec<AtomicUnitReport>,
        atomic_edges: Vec<AtomicUnitEdgeReport>,
    ) -> OwnerGraphReport {
        OwnerGraphReport {
            chunk_id: "x".to_string(),
            nodes,
            edges,
            quotient: OwnerGraphQuotientReport {
                nodes: vec![],
                edges: vec![],
                sccs: vec![],
            },
            atomic_graph: AtomicGraphReport {
                nodes: atomic_units,
                edges: atomic_edges,
            },
        }
    }

    fn no_claims() -> BTreeMap<String, String> {
        BTreeMap::new()
    }

    #[test]
    fn residual_atomic_units_become_singleton_proposals() {
        let a = owner("a", 1, &["a"], 10);
        let b = owner("b", 2, &["b"], 10);
        let graph = graph_with_atomic_units(
            vec![a.clone(), b.clone()],
            vec![],
            vec![unit("atomic:0", &[&a]), unit("atomic:1", &[&b])],
            vec![],
        );
        let report = factorize(&graph, &no_claims(), 10_000);
        assert_eq!(report.residual_owner_count, 2);
        assert_eq!(report.proposals.len(), 2);
        assert!(report.proposals.iter().all(|p| p.owner_ids.len() == 1));
        assert!(report.proposals.iter().all(|p| p.landable_today));
        assert_eq!(
            report.status_counts,
            BTreeMap::from([("peelable_now".to_string(), 2)]),
        );
        assert_eq!(
            report.size_distributions.by_members,
            vec![FactorizeSizeBucketCount {
                bucket: "1".to_string(),
                count: 2,
                landable_count: 2,
            }],
        );
        assert_eq!(
            report.size_distributions.by_lines,
            vec![FactorizeSizeBucketCount {
                bucket: "6-10".to_string(),
                count: 2,
                landable_count: 2,
            }],
        );
    }

    #[test]
    fn outgoing_residual_atomic_edges_close_proposals() {
        let a = owner("a", 1, &["a"], 10);
        let b = owner("b", 2, &["b"], 10);
        let edges = vec![edge("e1", "a", "b", DepKind::EagerUse, true)];
        let graph = graph_with_atomic_units(
            vec![a.clone(), b.clone()],
            edges,
            vec![unit("atomic:0", &[&a]), unit("atomic:1", &[&b])],
            vec![atomic_edge("atomic_edge:0", "atomic:0", "atomic:1")],
        );
        let report = factorize(&graph, &no_claims(), 10_000);
        assert!(
            report.proposals.iter().any(|p| p.binding_ids
                == vec!["a".to_string(), "b".to_string()]
                && p.landable_today),
            "expected closure proposal containing a and b: {report:#?}",
        );
    }

    #[test]
    fn edges_to_active_modules_count_outgoing_to_active_claims() {
        let a = owner_in_active_module("a", 1, &["a"], 10, "ui/x");
        let b = owner("b", 2, &["b"], 10);
        let edges = vec![edge("e1", "b", "a", DepKind::EagerUse, true)];
        let graph = graph_with_atomic_units(
            vec![a.clone(), b.clone()],
            edges,
            vec![unit("atomic:0", &[&a]), unit("atomic:1", &[&b])],
            vec![atomic_edge("atomic_edge:0", "atomic:1", "atomic:0")],
        );
        let claims = BTreeMap::from([("a".to_string(), "ui/x".to_string())]);
        let report = factorize(&graph, &claims, 10_000);
        let proposal = report
            .proposals
            .iter()
            .find(|p| p.binding_ids == vec!["b".to_string()])
            .expect("b proposal");
        assert_eq!(proposal.edges_to_active_modules, 1);
        assert_eq!(proposal.active_modules_referenced, vec!["ui/x".to_string()],);
    }

    #[test]
    fn size_capped_atomic_closure_becomes_diagnostic() {
        let a = owner("a", 1, &["a"], 10);
        let b = owner("b", 2, &["b"], 10);
        let graph = graph_with_atomic_units(
            vec![a.clone(), b.clone()],
            vec![edge("e1", "a", "b", DepKind::EagerUse, true)],
            vec![unit("atomic:0", &[&a]), unit("atomic:1", &[&b])],
            vec![atomic_edge("atomic_edge:0", "atomic:0", "atomic:1")],
        );
        let report = factorize(&graph, &no_claims(), 5);
        let diagnostic = report
            .diagnostics
            .iter()
            .find(|diagnostic| diagnostic.binding_ids == vec!["a".to_string(), "b".to_string()])
            .expect("closure diagnostic");
        assert_eq!(diagnostic.reason, FactorizeDiagnosticReason::ExceedsSizeCap);
    }
}
