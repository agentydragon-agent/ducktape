use std::collections::{BTreeMap, BTreeSet};

use petgraph::algo::tarjan_scc;
use swc_ecma_ast::Id;

use crate::graph::OwnerEdge;
use crate::{
    AtomicGraphReport, AtomicUnitEdgeReport, AtomicUnitReport, BindingReport, ChunkFactorization,
    DepKind, LogicalModuleIndex, ModuleId, ModuleReportRef, OwnerGraphEdgeReport,
    OwnerGraphNodeReport, OwnerGraphQuotientReport, OwnerGraphReport, OwnerId, QuotientEdgeReport,
    QuotientSccReport,
};

#[derive(Debug, Clone, Default)]
struct QuotientEdgeAccumulator {
    kinds: BTreeSet<DepKind>,
    constrains_init_order: bool,
}

#[derive(Debug, Clone, Default)]
struct AtomicEdgeAccumulator {
    kinds: BTreeSet<DepKind>,
    owner_edge_ids: BTreeSet<String>,
    constrains_init_order: bool,
}

pub(crate) fn build_owner_graph_report(factorization: &ChunkFactorization) -> OwnerGraphReport {
    let owner_edges = &factorization.analysis.owner_graph.edges;
    let quotient_edges = build_quotient_edge_reports(factorization, owner_edges);
    let quotient_nodes = build_quotient_node_reports(factorization);
    let quotient_sccs = build_quotient_scc_reports(factorization, &quotient_edges);
    let nodes = factorization
        .analysis
        .owner_graph
        .iter_nodes()
        .map(|node| OwnerGraphNodeReport {
            id: owner_key(node.id),
            statement_ordinal: node.statement_ordinal,
            source_location: node.source_location.clone(),
            declared_bindings: binding_reports(factorization, node.declared.iter()),
            statement_kind: node.kind,
            purity: node.purity.clone(),
            destination: module_report_ref(factorization, factorization.partition.of(node.id)),
        })
        .collect();
    let edges = owner_edges
        .iter()
        .map(|edge| OwnerGraphEdgeReport {
            id: edge.id.report_key(),
            source: owner_key(edge.from),
            target: owner_key(edge.to),
            edge_kind: edge.reason.kind,
            binding: edge.reason.binding.as_ref().map(|id| id.0.clone()),
            statement_ordinal: edge.reason.statement_ordinal,
            constrains_init_order: edge.reason.constrains_init_order(),
        })
        .collect();
    let atomic_graph = build_atomic_graph_report(factorization, owner_edges);
    OwnerGraphReport {
        chunk_id: factorization.analysis.chunk_id.clone(),
        nodes,
        edges,
        quotient: OwnerGraphQuotientReport {
            nodes: quotient_nodes,
            edges: quotient_edges,
            sccs: quotient_sccs,
        },
        atomic_graph,
    }
}

pub(crate) fn binding_reports<'a, I>(
    factorization: &ChunkFactorization,
    bindings: I,
) -> Vec<BindingReport>
where
    I: IntoIterator<Item = &'a Id>,
{
    bindings
        .into_iter()
        .map(|id| BindingReport {
            binding: id.0.clone(),
            export_name: factorization.analysis.export_name_for(id),
        })
        .collect()
}

fn build_quotient_node_reports(factorization: &ChunkFactorization) -> Vec<ModuleReportRef> {
    let mut modules = BTreeSet::<ModuleId>::new();
    for idx in 0..factorization.analysis.logical_modules.len() {
        modules.insert(ModuleId(LogicalModuleIndex(idx)));
    }
    for (_, module) in factorization.partition.iter() {
        modules.insert(module);
    }
    for (from, to, _) in factorization.dep_graph.all_edges() {
        modules.insert(from);
        modules.insert(to);
    }
    modules
        .into_iter()
        .map(|id| module_report_ref(factorization, id))
        .collect()
}

pub(crate) fn build_quotient_edge_reports(
    factorization: &ChunkFactorization,
    owner_edges: &[OwnerEdge],
) -> Vec<QuotientEdgeReport> {
    let partition = &factorization.partition;
    let mut accum = BTreeMap::<(ModuleId, ModuleId), QuotientEdgeAccumulator>::new();
    let mut seen_side_effect_module_pairs = BTreeSet::<(ModuleId, ModuleId)>::new();
    for edge in owner_edges {
        let from = partition.of(edge.from);
        let to = partition.of(edge.to);
        if from == to {
            continue;
        }
        if edge.reason.is_sequenced() && !seen_side_effect_module_pairs.insert((from, to)) {
            continue;
        }
        let entry = accum.entry((from, to)).or_default();
        entry.kinds.insert(edge.reason.kind);
        entry.constrains_init_order |= edge.reason.constrains_init_order();
    }
    accum
        .into_iter()
        .enumerate()
        .map(|(idx, ((from, to), entry))| QuotientEdgeReport {
            id: format!("module_edge:{idx}"),
            source: module_key(from),
            target: module_key(to),
            edge_kinds: entry.kinds.into_iter().collect(),
            constrains_init_order: entry.constrains_init_order,
        })
        .collect()
}

fn build_atomic_graph_report(
    factorization: &ChunkFactorization,
    owner_edges: &[OwnerEdge],
) -> AtomicGraphReport {
    let mut units = factorization.atomic_units.clone();
    units.sort_by_key(|unit| unit.members.iter().copied().min().map(|owner| owner.0));
    let mut unit_by_owner = BTreeMap::<OwnerId, usize>::new();
    for (unit_idx, unit) in units.iter().enumerate() {
        for owner in &unit.members {
            unit_by_owner.insert(*owner, unit_idx);
        }
    }

    let nodes = units
        .iter()
        .enumerate()
        .map(|(idx, unit)| {
            let mut owner_ids = Vec::new();
            let mut members = Vec::new();
            let mut anonymous_statement_owner_ids = Vec::new();
            let mut destinations_by_id = BTreeMap::<String, ModuleReportRef>::new();
            let mut causes: Vec<DepKind> = unit.causes.iter().copied().collect();
            let mut start_line = usize::MAX;
            let mut end_line = 0usize;
            let mut have_location = false;
            let mut size_lines_estimate = 0usize;
            let mut min_ordinal = usize::MAX;
            let mut max_ordinal = 0usize;
            for owner_id in &unit.members {
                owner_ids.push(owner_key(*owner_id));
                if let Some(node) = factorization.analysis.owner_graph.node(*owner_id) {
                    if node.declared.is_empty() {
                        anonymous_statement_owner_ids.push(owner_key(*owner_id));
                    }
                    members.extend(binding_reports(factorization, node.declared.iter()));
                    if let Some(location) = &node.source_location {
                        have_location = true;
                        start_line = start_line.min(location.start_line);
                        end_line = end_line.max(location.end_line);
                        size_lines_estimate += location.end_line + 1 - location.start_line;
                    }
                    min_ordinal = min_ordinal.min(node.statement_ordinal.0);
                    max_ordinal = max_ordinal.max(node.statement_ordinal.0);
                    let destination =
                        module_report_ref(factorization, factorization.partition.of(*owner_id));
                    destinations_by_id.insert(destination.id.clone(), destination);
                }
            }
            members.sort();
            members.dedup();
            causes.sort();
            anonymous_statement_owner_ids.sort();
            AtomicUnitReport {
                id: atomic_unit_key(idx),
                owner_ids,
                members,
                anonymous_statement_owner_ids,
                destinations: destinations_by_id.into_values().collect(),
                causes,
                size_lines_estimate,
                source_line_range: have_location.then_some([start_line, end_line]),
                ordinal_span: max_ordinal.saturating_sub(min_ordinal),
            }
        })
        .collect();

    let mut accum = BTreeMap::<(usize, usize), AtomicEdgeAccumulator>::new();
    for edge in owner_edges {
        if edge.reason.kind == DepKind::LazyUse {
            continue;
        }
        let (Some(&from_unit), Some(&to_unit)) =
            (unit_by_owner.get(&edge.from), unit_by_owner.get(&edge.to))
        else {
            continue;
        };
        if from_unit == to_unit {
            continue;
        }
        let entry = accum.entry((from_unit, to_unit)).or_default();
        entry.kinds.insert(edge.reason.kind);
        entry.owner_edge_ids.insert(edge.id.report_key());
        entry.constrains_init_order |= edge.reason.constrains_init_order();
    }
    let edges = accum
        .into_iter()
        .enumerate()
        .map(|(idx, ((from, to), entry))| AtomicUnitEdgeReport {
            id: format!("atomic_edge:{idx}"),
            source: atomic_unit_key(from),
            target: atomic_unit_key(to),
            edge_kinds: entry.kinds.into_iter().collect(),
            owner_edge_ids: entry.owner_edge_ids.into_iter().collect(),
            constrains_init_order: entry.constrains_init_order,
        })
        .collect();

    AtomicGraphReport { nodes, edges }
}

fn build_quotient_scc_reports(
    factorization: &ChunkFactorization,
    quotient_edges: &[QuotientEdgeReport],
) -> Vec<QuotientSccReport> {
    let quotient_edges_by_source = quotient_edge_indices_by_source(quotient_edges);
    let mut sccs = Vec::new();
    for scc in tarjan_scc(&factorization.dep_graph.0) {
        let is_cycle = scc.len() > 1
            || (scc.len() == 1 && factorization.dep_graph.contains_edge(scc[0], scc[0]));
        if !is_cycle {
            continue;
        }
        let in_scc: BTreeSet<ModuleId> = scc.iter().copied().collect();
        let mut module_edge_ids = Vec::new();
        let mut constraining_module_edge_ids = Vec::new();
        for &source in &in_scc {
            let Some(out_edges) = quotient_edges_by_source.get(&source) else {
                continue;
            };
            for &(target, edge_idx) in out_edges {
                if !in_scc.contains(&target) {
                    continue;
                }
                let edge = &quotient_edges[edge_idx];
                module_edge_ids.push(edge.id.clone());
                if edge.constrains_init_order {
                    constraining_module_edge_ids.push(edge.id.clone());
                }
            }
        }
        let mut modules: Vec<String> = in_scc.iter().copied().map(module_key).collect();
        modules.sort();
        let mut labels: Vec<String> = modules
            .iter()
            .map(|key| {
                module_id_from_key(key)
                    .map(|id| factorization.analysis.module_name(id))
                    .unwrap_or_else(|| key.clone())
            })
            .collect();
        labels.sort();
        module_edge_ids.sort();
        constraining_module_edge_ids.sort();
        sccs.push(QuotientSccReport {
            id: format!("scc:{}", sccs.len()),
            modules,
            labels,
            is_cycle,
            realizable: constraining_module_edge_ids.is_empty(),
            module_edge_ids,
            constraining_module_edge_ids,
        });
    }
    sccs
}

fn quotient_edge_indices_by_source(
    quotient_edges: &[QuotientEdgeReport],
) -> BTreeMap<ModuleId, Vec<(ModuleId, usize)>> {
    let mut by_source = BTreeMap::<ModuleId, Vec<(ModuleId, usize)>>::new();
    for (idx, edge) in quotient_edges.iter().enumerate() {
        let Some(source) = module_id_from_key(&edge.source) else {
            continue;
        };
        let Some(target) = module_id_from_key(&edge.target) else {
            continue;
        };
        by_source.entry(source).or_default().push((target, idx));
    }
    by_source
}

/// True iff `id` refers to a logical module whose `residual` flag is
/// set — the chunk's catch-all destination synthesized before
/// `ChunkFactorization::build`. Used by the destination
/// projection in reports to gate residual-only predicates without
/// string-matching module ids or labels.
pub(crate) fn is_residual_destination(factorization: &ChunkFactorization, id: ModuleId) -> bool {
    let LogicalModuleIndex(idx) = id.0;
    factorization
        .analysis
        .logical_modules
        .get(idx)
        .is_some_and(|module| module.residual)
}

pub(crate) fn owner_key(id: OwnerId) -> String {
    format!("owner:{}", id.0)
}

pub(crate) fn module_key(id: ModuleId) -> String {
    let LogicalModuleIndex(idx) = id.0;
    format!("logical:{idx}")
}

pub(crate) fn atomic_unit_key(idx: usize) -> String {
    format!("atomic:{idx}")
}

pub(crate) fn module_id_from_key(key: &str) -> Option<ModuleId> {
    key.strip_prefix("logical:")
        .and_then(|idx| idx.parse::<usize>().ok())
        .map(|idx| ModuleId(LogicalModuleIndex(idx)))
}

pub(crate) fn module_report_ref(
    factorization: &ChunkFactorization,
    id: ModuleId,
) -> ModuleReportRef {
    let LogicalModuleIndex(idx) = id.0;
    let logical = factorization.analysis.logical_modules.get(idx);
    ModuleReportRef {
        id: module_key(id),
        label: factorization.analysis.module_name(id),
        residual: is_residual_destination(factorization, id),
        index: logical.map(|_| idx),
        target_file: logical.map(|module| module.target_file.clone()),
    }
}
