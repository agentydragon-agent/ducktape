//! Single source of truth for the three-clause validity predicate
//! (DESIGN.md "Valid peels and atomic modules"). The validator and any
//! hypothetical-move planner checks reach the verdict through this module —
//! see "Realizability primitive" in `DESIGN.md`.
//!
//! Scope: clauses 2 (no cross-destination rebinding writes) and 3
//! (no multi-module SCC in the constraining-edge subgraph of the
//! quotient). Clause 1 (importability) is policy that lives in
//! `materialize_logical_modules` per "Emit-side responsibilities":
//! residual-entry bindings are importable by construction via the
//! auto-grown export pass. Callers that need a private-read blocker
//! (the proposer's `BlockedResidualDependency`) layer it on top of the
//! verdict; it is not part of the realizability primitive.
//!
//! Two access shapes:
//!
//! - `check_realizability(owner_graph, partition) -> Verdict`: pure
//!   function, from-scratch. The correctness reference and the cold-
//!   start path. `O(N + M)` per call.
//! - `RealizabilityIndex`: a stateful index that owns a working
//!   `Partition` and supports `push`/`undo` of `PartitionDelta`s.
//!   `verdict()` reads the current state. A non-mutating overlay query is
//!   kept as a tested future optimization path for planner checks that need
//!   hypothetical owner moves.
//!
//! The transactional API is backed by a rollbackable quotient index:
//! owner-graph edges are fixed, so `push`/`undo` only updates quotient
//! edge buckets incident to moved owners. Full verdicts run SCC over
//! the maintained quotient; candidate verdicts use localized
//! reachability around the hypothetical destination.

use std::collections::{BTreeMap, BTreeSet};

use petgraph::algo::tarjan_scc;
use petgraph::graphmap::DiGraphMap;

use crate::OwnerId;
use crate::graph::{OwnerEdge, OwnerEdgeId, OwnerGraph};
use crate::ids::ModuleId;
use crate::partition::Partition;
use crate::rollback_graph::{GraphMark, RollbackDiGraph};

/// Multi-module SCC of the constraining-edge subgraph of the
/// quotient. The presence of any such SCC violates clause 3.
#[derive(Debug, Clone, Eq, PartialEq)]
pub struct UnrealizableScc {
    /// Modules participating in the cycle.
    pub modules: BTreeSet<ModuleId>,
    /// Every constraining owner-edge whose endpoints both fall inside
    /// `modules` and that crosses module boundaries — i.e. the
    /// owner-level evidence the cycle is composed of. Stable order by
    /// `OwnerEdgeId`.
    pub constraining_owner_edges: Vec<OwnerEdgeId>,
}

/// Cross-destination rebinding write. ESM imports are read-only in the
/// importing module, so any such edge violates clause 2. One entry per
/// owner-edge.
#[derive(Debug, Clone, Eq, PartialEq)]
pub struct CrossRebindEdge {
    pub from: ModuleId,
    pub to: ModuleId,
    pub owner_edge: OwnerEdgeId,
}

/// Verdict on a (current or hypothetical) destination assignment.
/// Empty verdict ↔ realizable per clauses 2 and 3.
#[derive(Debug, Clone, Default, Eq, PartialEq)]
pub struct RealizabilityVerdict {
    pub unrealizable_sccs: Vec<UnrealizableScc>,
    pub cross_rebinds: Vec<CrossRebindEdge>,
}

impl RealizabilityVerdict {
    pub fn is_realizable(&self) -> bool {
        self.unrealizable_sccs.is_empty() && self.cross_rebinds.is_empty()
    }

    /// Modules participating in any unrealizable SCC. Convenience for
    /// the proposer, which decodes the verdict against the candidate's
    /// hypothetical destination.
    pub fn modules_in_unrealizable_sccs(&self) -> BTreeSet<ModuleId> {
        let mut out = BTreeSet::new();
        for scc in &self.unrealizable_sccs {
            for &m in &scc.modules {
                out.insert(m);
            }
        }
        out
    }
}

/// Pure-function form. Builds the constraining-edge quotient, runs
/// Tarjan, surfaces multi-module SCCs and cross-rebinds. The
/// correctness reference for the `RealizabilityIndex`'s incremental
/// backing (verified by differential test in the
/// `RealizabilityIndex` step 1b follow-up).
pub fn check_realizability(
    owner_graph: &OwnerGraph,
    partition: &Partition,
) -> RealizabilityVerdict {
    let mut verdict = RealizabilityVerdict::default();

    // Two parallel adjacency tables:
    //   - `constraining_adj`: only `EagerUse` + `Sequenced` (+
    //     `LocalEffect`) edges, deduped sequenced-per-pair. The
    //     evidence carrier — SCCs here are *the* clause-3 violation.
    //   - `i_adj`: every cross-module edge in the I-graph, including
    //     `LazyUse`. SCCs here are candidates for the asymmetric-
    //     cycle TDZ shape `(at-init forward, lazy back)`; the
    //     simulator below decides whether Lemma 2's source-import
    //     reversal actually rescues evaluation.
    //
    // Sequenced edges are deduped per (from, to) — multiple sequenced
    // reasons between the same module pair represent the same
    // ordering constraint and would over-weight evidence if counted
    // separately. (Matches `build_module_quotient`'s sequenced-edge
    // dedup.)
    let mut constraining_adj: BTreeMap<(ModuleId, ModuleId), Vec<OwnerEdgeId>> = BTreeMap::new();
    let mut i_adj: BTreeMap<(ModuleId, ModuleId), Vec<OwnerEdgeId>> = BTreeMap::new();
    let mut seen_sequenced_pairs: BTreeSet<(ModuleId, ModuleId)> = BTreeSet::new();

    for edge in &owner_graph.edges {
        // Skip edges whose endpoints aren't in this owner graph's
        // partition slot (defensive — Partition is dense, but
        // owner_graph.node() returning None should not crash here).
        if owner_graph.node(edge.from).is_none() || owner_graph.node(edge.to).is_none() {
            continue;
        }
        let from = partition.of(edge.from);
        let to = partition.of(edge.to);
        if from == to {
            continue;
        }
        if edge.reason.is_rebind() {
            verdict.cross_rebinds.push(CrossRebindEdge {
                from,
                to,
                owner_edge: edge.id,
            });
            continue;
        }
        // Every non-rebind cross-module edge participates in I.
        i_adj.entry((from, to)).or_default().push(edge.id);
        if !edge.reason.constrains_init_order() {
            continue;
        }
        if edge.reason.is_sequenced() && !seen_sequenced_pairs.insert((from, to)) {
            continue;
        }
        constraining_adj
            .entry((from, to))
            .or_default()
            .push(edge.id);
    }

    if i_adj.is_empty() {
        return verdict;
    }

    // Pass 1: Tarjan over the constraining-edge subgraph — the
    // historical relaxed clause-3 rule. Catches **mutual**
    // constraining cycles (both sides eager-read each other; no
    // source order can satisfy both).
    let mut con_graph: DiGraphMap<ModuleId, ()> = DiGraphMap::new();
    for &(from, to) in constraining_adj.keys() {
        con_graph.add_edge(from, to, ());
    }
    let mut reported: BTreeSet<BTreeSet<ModuleId>> = BTreeSet::new();
    for scc in tarjan_scc(&con_graph) {
        if scc.len() < 2 {
            continue;
        }
        let modules: BTreeSet<ModuleId> = scc.iter().copied().collect();
        let mut owner_edges: Vec<OwnerEdgeId> = Vec::new();
        for ((from, to), edges) in &constraining_adj {
            if modules.contains(from) && modules.contains(to) {
                owner_edges.extend_from_slice(edges);
            }
        }
        owner_edges.sort();
        reported.insert(modules.clone());
        verdict.unrealizable_sccs.push(UnrealizableScc {
            modules,
            constraining_owner_edges: owner_edges,
        });
    }

    // Pass 2: Tarjan over the full I-graph (constraining + lazy).
    // Multi-module I-SCCs containing constraining edges are the
    // asymmetric `(at-init forward, lazy back)` candidates. Lemma 2
    // (`ChunkFactorization::source_import_position`) reverses
    // entry's import order within each I-SCC so DFS lands on the
    // dependent first and unwinds through the dependency; the
    // simulator below checks whether that reversal actually
    // rescues evaluation given the spec's full import topology.
    let mut i_graph: DiGraphMap<ModuleId, ()> = DiGraphMap::new();
    for &(from, to) in i_adj.keys() {
        i_graph.add_edge(from, to, ());
    }

    let i_sccs = tarjan_scc(&i_graph);
    let candidate_sccs: Vec<BTreeSet<ModuleId>> = i_sccs
        .into_iter()
        .filter_map(|scc| {
            if scc.len() < 2 {
                return None;
            }
            let modules: BTreeSet<ModuleId> = scc.into_iter().collect();
            if reported.contains(&modules) {
                return None;
            }
            // Skip SCCs that carry no constraining edge between
            // members — pure-lazy I-cycles never TDZ regardless of
            // entry's import order.
            let has_constraining = constraining_adj
                .keys()
                .any(|(from, to)| modules.contains(from) && modules.contains(to));
            if !has_constraining {
                return None;
            }
            Some(modules)
        })
        .collect();

    if !candidate_sccs.is_empty() {
        let mut i_successors: BTreeMap<ModuleId, BTreeSet<ModuleId>> = BTreeMap::new();
        for &(from, to) in i_adj.keys() {
            i_successors.entry(from).or_default().insert(to);
        }
        let constraining_pairs: BTreeSet<(ModuleId, ModuleId)> =
            constraining_adj.keys().copied().collect();
        let simulation =
            EsmEvaluationSimulator::build(i_successors, &constraining_pairs, partition.residual());
        for modules in candidate_sccs {
            let tdz_pairs: Vec<(ModuleId, ModuleId)> = simulation
                .tdz_pairs(&modules, &constraining_pairs)
                .collect();
            if tdz_pairs.is_empty() {
                continue;
            }
            // Surface only the constraining edges the simulator
            // actually flagged as TDZ at runtime — that's the
            // "surgical set" spec authors can cut to break the
            // cycle, distinct from the full constraining-evidence
            // listing the cycle report emits.
            let mut owner_edges: Vec<OwnerEdgeId> = Vec::new();
            for (from, to) in &tdz_pairs {
                if let Some(edges) = constraining_adj.get(&(*from, *to)) {
                    owner_edges.extend_from_slice(edges);
                }
            }
            owner_edges.sort();
            verdict.unrealizable_sccs.push(UnrealizableScc {
                modules,
                constraining_owner_edges: owner_edges,
            });
        }
    }

    verdict
}

/// Simulator for ECMA-262 Phase-2 module evaluation order, used to
/// decide whether Lemma 2's source-import reversal actually rescues
/// a candidate asymmetric I-SCC at runtime.
///
/// The simulator models the **same** import-ordering decisions
/// the materializer makes:
///   - residual's imports are sorted by `source_import_position`
///     (the Lemma 2 algorithm — reverse-within-SCC of the
///     constraining linker order). See
///     `ChunkFactorization::source_import_position` and
///     `lowering::lower_chunk`.
///   - every other module's imports are sorted by `linker_position`
///     (dependency-first toposort of the constraining-edge
///     subgraph). See `ChunkFactorization::linker_position` and
///     `lowering::imports_cross::cross_module_imports_for_plan`.
///
/// It then walks DFS from residual, records the post-order
/// evaluation index per module, and verifies every cross-module
/// constraining edge `(M, X)` evaluates the target `X` before the
/// source `M`. Equivalent to asking whether the emitted ESM bundle
/// would actually execute without TDZ on the constraining edges in
/// the candidate SCC.
struct EsmEvaluationSimulator {
    /// Post-order index per module after DFS from residual. Lower
    /// index = earlier post-order = body evaluates earlier. Modules
    /// unreachable from residual are absent — ESM doesn't load them,
    /// so the simulator skips constraining-edge checks involving
    /// them.
    post_order: BTreeMap<ModuleId, usize>,
}

impl EsmEvaluationSimulator {
    fn build(
        i_successors: BTreeMap<ModuleId, BTreeSet<ModuleId>>,
        constraining_pairs: &BTreeSet<(ModuleId, ModuleId)>,
        residual: ModuleId,
    ) -> Self {
        let mut nodes: BTreeSet<ModuleId> = BTreeSet::new();
        nodes.insert(residual);
        for (node, succs) in &i_successors {
            nodes.insert(*node);
            nodes.extend(succs.iter().copied());
        }
        for &(from, to) in constraining_pairs {
            nodes.insert(from);
            nodes.insert(to);
        }

        let linker_position = compute_linker_position(constraining_pairs);
        let i_pairs: BTreeSet<(ModuleId, ModuleId)> = i_successors
            .iter()
            .flat_map(|(from, succs)| succs.iter().map(move |to| (*from, *to)))
            .collect();
        let source_import_position =
            compute_source_import_position(&i_pairs, &nodes, &linker_position);
        let post_order = simulate_esm_post_order(
            residual,
            &i_successors,
            &linker_position,
            &source_import_position,
        );

        Self { post_order }
    }

    /// Yields the `(from, to)` constraining pairs inside `modules`
    /// whose simulator-derived post-order has `to` evaluating at or
    /// after `from` — i.e. the at-init read of `to`'s binding from
    /// `from`'s body would TDZ. Returns the surgical TDZ subset
    /// callers use for diagnostics; an empty iterator means Lemma 2
    /// rescues the SCC.
    ///
    /// Endpoints unreachable from residual are skipped — ESM never
    /// loads them, so they can't fire a TDZ at runtime.
    fn tdz_pairs<'a>(
        &'a self,
        modules: &'a BTreeSet<ModuleId>,
        constraining_pairs: &'a BTreeSet<(ModuleId, ModuleId)>,
    ) -> impl Iterator<Item = (ModuleId, ModuleId)> + 'a {
        constraining_pairs
            .iter()
            .copied()
            .filter(move |&(from, to)| {
                if !modules.contains(&from) || !modules.contains(&to) {
                    return false;
                }
                let (Some(from_idx), Some(to_idx)) =
                    (self.post_order.get(&from), self.post_order.get(&to))
                else {
                    return false;
                };
                to_idx >= from_idx
            })
    }
}

/// Toposort of the constraining-edge subgraph, deepest dependency
/// first. Mirrors `chunk_factorization::compute_linker_order` so
/// the simulator's `linker_position` matches the materializer's.
///
/// Modules with no constraining edge are omitted (matches the
/// production helper, which only considers constraining-graph
/// members).
fn compute_linker_position(
    constraining_pairs: &BTreeSet<(ModuleId, ModuleId)>,
) -> BTreeMap<ModuleId, usize> {
    use petgraph::algo::toposort;
    let mut graph: DiGraphMap<ModuleId, ()> = DiGraphMap::new();
    for &(from, to) in constraining_pairs {
        graph.add_node(from);
        graph.add_node(to);
        graph.add_edge(from, to, ());
    }
    match toposort(&graph, None) {
        Ok(order) => order
            .into_iter()
            .rev()
            .enumerate()
            .map(|(idx, id)| (id, idx))
            .collect(),
        Err(_) => BTreeMap::new(),
    }
}

/// `source_import_position` per Lemma 2: sort modules by
/// `(SCC dep rank ASC, intra-SCC linker_position DESC)`. SCCs are
/// over the full I-graph; SCC dep rank = min linker_position of
/// SCC members. Mirrors `chunk_factorization::compute_source_import_order`.
fn compute_source_import_position(
    i_pairs: &BTreeSet<(ModuleId, ModuleId)>,
    nodes: &BTreeSet<ModuleId>,
    linker_position: &BTreeMap<ModuleId, usize>,
) -> BTreeMap<ModuleId, usize> {
    let mut graph: DiGraphMap<ModuleId, ()> = DiGraphMap::new();
    for &node in nodes {
        graph.add_node(node);
    }
    for &(from, to) in i_pairs {
        graph.add_edge(from, to, ());
    }
    let sccs = tarjan_scc(&graph);
    let mut scc_of: BTreeMap<ModuleId, usize> = BTreeMap::new();
    let mut scc_rank: Vec<usize> = Vec::with_capacity(sccs.len());
    for (idx, scc) in sccs.iter().enumerate() {
        let min_pos = scc
            .iter()
            .filter_map(|m| linker_position.get(m).copied())
            .min()
            .unwrap_or(usize::MAX);
        scc_rank.push(min_pos);
        for m in scc {
            scc_of.insert(*m, idx);
        }
    }
    let mut sorted: Vec<ModuleId> = nodes.iter().copied().collect();
    sorted.sort_by(|a, b| {
        let a_rank = scc_of
            .get(a)
            .and_then(|i| scc_rank.get(*i).copied())
            .unwrap_or(usize::MAX);
        let b_rank = scc_of
            .get(b)
            .and_then(|i| scc_rank.get(*i).copied())
            .unwrap_or(usize::MAX);
        let a_pos = linker_position.get(a).copied();
        let b_pos = linker_position.get(b).copied();
        a_rank.cmp(&b_rank).then_with(|| match (a_pos, b_pos) {
            // Within an SCC, DESC by linker_position so the
            // dependent (highest linker_position = evaluates last)
            // comes first in source. None goes after Some, matching
            // `chunk_factorization::compute_source_import_order`.
            (Some(a), Some(b)) => b.cmp(&a),
            (Some(_), None) => std::cmp::Ordering::Less,
            (None, Some(_)) => std::cmp::Ordering::Greater,
            (None, None) => std::cmp::Ordering::Equal,
        })
    });
    sorted
        .into_iter()
        .enumerate()
        .map(|(idx, id)| (id, idx))
        .collect()
}

/// Simulate ECMA-262 Phase-2 DFS from `residual`. Returns a
/// `post_order` map: lower index = earlier post-order = body
/// evaluates earlier. Modules unreachable from `residual` are
/// absent.
///
/// Import ordering per visitor:
///   - At `residual`: `source_import_position` (Lemma 2-aware).
///   - Elsewhere: `linker_position` ascending (dependency-first;
///     mirrors `lowering::imports_cross::cross_module_imports_for_plan`).
/// Modules without a `linker_position` slot fall back to
/// `usize::MAX` — i.e. evaluated last among that module's imports —
/// matching the materializer's `unwrap_or(usize::MAX)`.
fn simulate_esm_post_order(
    residual: ModuleId,
    i_successors: &BTreeMap<ModuleId, BTreeSet<ModuleId>>,
    linker_position: &BTreeMap<ModuleId, usize>,
    source_import_position: &BTreeMap<ModuleId, usize>,
) -> BTreeMap<ModuleId, usize> {
    enum Frame {
        Enter(ModuleId),
        Finish(ModuleId),
    }

    let mut on_stack: BTreeSet<ModuleId> = BTreeSet::new();
    let mut visited: BTreeSet<ModuleId> = BTreeSet::new();
    let mut post_order: BTreeMap<ModuleId, usize> = BTreeMap::new();
    let mut next_post_index: usize = 0;
    let mut work: Vec<Frame> = vec![Frame::Enter(residual)];

    let sorted_successors = |node: ModuleId| -> Vec<ModuleId> {
        let Some(succs) = i_successors.get(&node) else {
            return Vec::new();
        };
        let mut succs: Vec<ModuleId> = succs.iter().copied().collect();
        if node == residual {
            succs.sort_by_key(|m| source_import_position.get(m).copied().unwrap_or(usize::MAX));
        } else {
            succs.sort_by_key(|m| linker_position.get(m).copied().unwrap_or(usize::MAX));
        }
        succs
    };

    while let Some(frame) = work.pop() {
        match frame {
            Frame::Enter(node) => {
                if visited.contains(&node) {
                    continue;
                }
                if on_stack.contains(&node) {
                    // Cycle no-op: ESM doesn't re-enter a module
                    // already on the link-DFS stack.
                    continue;
                }
                on_stack.insert(node);
                work.push(Frame::Finish(node));
                // Push successors in REVERSE source order so the
                // first source-order successor is popped (DFS'd
                // into) first.
                let succs = sorted_successors(node);
                for succ in succs.into_iter().rev() {
                    work.push(Frame::Enter(succ));
                }
            }
            Frame::Finish(node) => {
                on_stack.remove(&node);
                if visited.insert(node) {
                    post_order.insert(node, next_post_index);
                    next_post_index += 1;
                }
            }
        }
    }

    post_order
}

/// A reversible mutation of a `Partition`. Planner checks can construct
/// deltas to describe hypothetical or actual destination assignments; the
/// index applies and reverts them.
#[derive(Debug, Clone)]
pub enum PartitionDelta {
    /// Reassign every owner in `owners` to `to`. Owners not in the
    /// list keep their current assignment. Owners already at `to` are
    /// no-ops but recorded for journal symmetry.
    MoveOwners { owners: Vec<OwnerId>, to: ModuleId },
}

/// Opaque handle returned by `push`. Passing it to `undo` rolls back
/// to the state before the corresponding push. Handles must be undone
/// in LIFO order — the journal is a stack — and `undo` panics in
/// debug builds on misuse so caller bugs surface early instead of
/// silently corrupting the index.
#[derive(Debug, Clone, Copy, Eq, PartialEq)]
pub struct DeltaHandle(usize);

/// Inverse of a `MoveOwners` delta: the prior `(owner, module)` pairs
/// so `undo` can restore them.
#[derive(Debug, Clone)]
struct JournalEntry {
    prior_assignments: Vec<(OwnerId, ModuleId)>,
    impacted_edges: Vec<OwnerEdgeId>,
    i_graph_mark: GraphMark,
    constraining_graph_mark: GraphMark,
}

#[derive(Debug, Clone, Default)]
struct ConstrainingBucket {
    non_sequenced: BTreeSet<OwnerEdgeId>,
    sequenced: BTreeSet<OwnerEdgeId>,
}

impl ConstrainingBucket {
    fn is_empty(&self) -> bool {
        self.non_sequenced.is_empty() && self.sequenced.is_empty()
    }

    fn insert_edge(&mut self, edge_id: OwnerEdgeId, sequenced: bool) {
        if sequenced {
            self.sequenced.insert(edge_id);
        } else {
            self.non_sequenced.insert(edge_id);
        }
    }

    fn remove_edge(&mut self, edge_id: OwnerEdgeId, sequenced: bool) {
        if sequenced {
            self.sequenced.remove(&edge_id);
        } else {
            self.non_sequenced.remove(&edge_id);
        }
    }

    fn extend_from(&mut self, other: &Self) {
        self.non_sequenced
            .extend(other.non_sequenced.iter().copied());
        self.sequenced.extend(other.sequenced.iter().copied());
    }

    fn remove_from(&mut self, other: &Self) {
        for edge_id in &other.non_sequenced {
            self.non_sequenced.remove(edge_id);
        }
        for edge_id in &other.sequenced {
            self.sequenced.remove(edge_id);
        }
    }

    fn evidence_edges(&self) -> Vec<OwnerEdgeId> {
        let mut edges: Vec<OwnerEdgeId> = self.non_sequenced.iter().copied().collect();
        if let Some(first_sequenced) = self.sequenced.first() {
            edges.push(*first_sequenced);
        }
        edges.sort();
        edges
    }
}

#[derive(Debug, Clone, Copy, Eq, PartialEq)]
struct EdgeContribution {
    from: ModuleId,
    to: ModuleId,
    owner_edge: OwnerEdgeId,
    kind: EdgeContributionKind,
}

#[derive(Debug, Clone, Copy, Eq, PartialEq)]
enum EdgeContributionKind {
    Rebind,
    Import { constraining: bool, sequenced: bool },
}

#[derive(Debug, Clone, Default)]
struct QuotientOverlay {
    i_delta: BTreeMap<(ModuleId, ModuleId), isize>,
    constraining_delta: BTreeMap<(ModuleId, ModuleId), isize>,
    constraining_added: BTreeMap<(ModuleId, ModuleId), ConstrainingBucket>,
    constraining_removed: BTreeMap<(ModuleId, ModuleId), ConstrainingBucket>,
    cross_rebind_added: BTreeMap<OwnerEdgeId, CrossRebindEdge>,
    cross_rebind_removed: BTreeSet<OwnerEdgeId>,
}

impl QuotientOverlay {
    fn add_contribution(&mut self, contribution: EdgeContribution) {
        match contribution.kind {
            EdgeContributionKind::Rebind => {
                self.cross_rebind_added.insert(
                    contribution.owner_edge,
                    CrossRebindEdge {
                        from: contribution.from,
                        to: contribution.to,
                        owner_edge: contribution.owner_edge,
                    },
                );
            }
            EdgeContributionKind::Import {
                constraining,
                sequenced,
            } => {
                increment_delta(&mut self.i_delta, contribution.from, contribution.to, 1);
                if constraining {
                    increment_delta(
                        &mut self.constraining_delta,
                        contribution.from,
                        contribution.to,
                        1,
                    );
                    self.constraining_added
                        .entry((contribution.from, contribution.to))
                        .or_default()
                        .insert_edge(contribution.owner_edge, sequenced);
                }
            }
        }
    }

    fn remove_contribution(&mut self, contribution: EdgeContribution) {
        match contribution.kind {
            EdgeContributionKind::Rebind => {
                self.cross_rebind_removed.insert(contribution.owner_edge);
            }
            EdgeContributionKind::Import {
                constraining,
                sequenced,
            } => {
                increment_delta(&mut self.i_delta, contribution.from, contribution.to, -1);
                if constraining {
                    increment_delta(
                        &mut self.constraining_delta,
                        contribution.from,
                        contribution.to,
                        -1,
                    );
                    self.constraining_removed
                        .entry((contribution.from, contribution.to))
                        .or_default()
                        .insert_edge(contribution.owner_edge, sequenced);
                }
            }
        }
    }
}

fn increment_delta(
    deltas: &mut BTreeMap<(ModuleId, ModuleId), isize>,
    from: ModuleId,
    to: ModuleId,
    delta: isize,
) {
    let key = (from, to);
    let next = deltas.get(&key).copied().unwrap_or(0) + delta;
    if next == 0 {
        deltas.remove(&key);
    } else {
        deltas.insert(key, next);
    }
}

fn edge_contribution(edge: &OwnerEdge, from: ModuleId, to: ModuleId) -> Option<EdgeContribution> {
    if from == to {
        return None;
    }

    let kind = if edge.reason.is_rebind() {
        EdgeContributionKind::Rebind
    } else {
        EdgeContributionKind::Import {
            constraining: edge.reason.constrains_init_order(),
            sequenced: edge.reason.is_sequenced(),
        }
    };

    Some(EdgeContribution {
        from,
        to,
        owner_edge: edge.id,
        kind,
    })
}

struct OverlayGraphView<'a> {
    base: &'a RollbackDiGraph<ModuleId>,
    delta: &'a BTreeMap<(ModuleId, ModuleId), isize>,
    added_out: BTreeMap<ModuleId, BTreeSet<ModuleId>>,
    added_in: BTreeMap<ModuleId, BTreeSet<ModuleId>>,
}

impl<'a> OverlayGraphView<'a> {
    fn new(
        base: &'a RollbackDiGraph<ModuleId>,
        delta: &'a BTreeMap<(ModuleId, ModuleId), isize>,
    ) -> Self {
        let mut added_out = BTreeMap::<ModuleId, BTreeSet<ModuleId>>::new();
        let mut added_in = BTreeMap::<ModuleId, BTreeSet<ModuleId>>::new();
        for (&(from, to), &count) in delta {
            if count <= 0 {
                continue;
            }
            added_out.entry(from).or_default().insert(to);
            added_in.entry(to).or_default().insert(from);
        }
        Self {
            base,
            delta,
            added_out,
            added_in,
        }
    }

    fn scc_containing(&self, node: ModuleId) -> BTreeSet<ModuleId> {
        if !self.has_neighbor(node, WalkDirection::Forward)
            || !self.has_neighbor(node, WalkDirection::Reverse)
        {
            return BTreeSet::from([node]);
        }
        let forward = self.reachable_from(node, WalkDirection::Forward);
        let reverse = self.reachable_from(node, WalkDirection::Reverse);
        forward.intersection(&reverse).copied().collect()
    }

    fn reachable_from(&self, start: ModuleId, direction: WalkDirection) -> BTreeSet<ModuleId> {
        let mut seen = BTreeSet::new();
        let mut stack = vec![start];
        while let Some(node) = stack.pop() {
            if !seen.insert(node) {
                continue;
            }
            for neighbor in self.neighbors(node, direction).into_iter().rev() {
                if !seen.contains(&neighbor) {
                    stack.push(neighbor);
                }
            }
        }
        seen
    }

    fn neighbors(&self, node: ModuleId, direction: WalkDirection) -> Vec<ModuleId> {
        let mut neighbors: BTreeSet<ModuleId> = match direction {
            WalkDirection::Forward => self
                .base
                .successors(node)
                .filter(|&to| self.effective_count(node, to) > 0)
                .collect(),
            WalkDirection::Reverse => self
                .base
                .predecessors(node)
                .filter(|&from| self.effective_count(from, node) > 0)
                .collect(),
        };

        let overlay_neighbors = match direction {
            WalkDirection::Forward => self.added_out.get(&node),
            WalkDirection::Reverse => self.added_in.get(&node),
        };
        if let Some(overlay_neighbors) = overlay_neighbors {
            for &neighbor in overlay_neighbors {
                let (from, to) = match direction {
                    WalkDirection::Forward => (node, neighbor),
                    WalkDirection::Reverse => (neighbor, node),
                };
                if self.effective_count(from, to) > 0 {
                    neighbors.insert(neighbor);
                }
            }
        }

        neighbors.into_iter().collect()
    }

    fn has_neighbor(&self, node: ModuleId, direction: WalkDirection) -> bool {
        let base_neighbors = match direction {
            WalkDirection::Forward => self.base.successors(node),
            WalkDirection::Reverse => self.base.predecessors(node),
        };
        for neighbor in base_neighbors {
            let (from, to) = match direction {
                WalkDirection::Forward => (node, neighbor),
                WalkDirection::Reverse => (neighbor, node),
            };
            if self.effective_count(from, to) > 0 {
                return true;
            }
        }

        let overlay_neighbors = match direction {
            WalkDirection::Forward => self.added_out.get(&node),
            WalkDirection::Reverse => self.added_in.get(&node),
        };
        if let Some(overlay_neighbors) = overlay_neighbors {
            for &neighbor in overlay_neighbors {
                let (from, to) = match direction {
                    WalkDirection::Forward => (node, neighbor),
                    WalkDirection::Reverse => (neighbor, node),
                };
                if self.effective_count(from, to) > 0 {
                    return true;
                }
            }
        }

        false
    }

    fn effective_count(&self, from: ModuleId, to: ModuleId) -> isize {
        self.base.edge_count(from, to) as isize + self.delta.get(&(from, to)).copied().unwrap_or(0)
    }
}

#[derive(Debug, Clone, Copy)]
enum WalkDirection {
    Forward,
    Reverse,
}

#[derive(Debug, Clone)]
struct IncrementalQuotient {
    i_graph: RollbackDiGraph<ModuleId>,
    constraining_graph: RollbackDiGraph<ModuleId>,
    constraining_buckets: BTreeMap<(ModuleId, ModuleId), ConstrainingBucket>,
    cross_rebinds: BTreeMap<OwnerEdgeId, CrossRebindEdge>,
    /// Chunk's residual module — the ESM DFS root. The Lemma 2
    /// simulator that decides candidate asymmetric I-SCCs needs to
    /// know which module gets the source_import_position reversal
    /// (residual) vs which use plain linker_position
    /// (every other module).
    residual: ModuleId,
}

impl IncrementalQuotient {
    fn new(owner_graph: &OwnerGraph, partition: &Partition) -> Self {
        let mut quotient = Self {
            i_graph: RollbackDiGraph::new(),
            constraining_graph: RollbackDiGraph::new(),
            constraining_buckets: BTreeMap::new(),
            cross_rebinds: BTreeMap::new(),
            residual: partition.residual(),
        };
        for edge in &owner_graph.edges {
            quotient.add_current_edge(edge, partition, true);
        }
        quotient
    }

    fn marks(&self) -> (GraphMark, GraphMark) {
        (self.i_graph.mark(), self.constraining_graph.mark())
    }

    fn rollback_graphs(&mut self, i_mark: GraphMark, constraining_mark: GraphMark) {
        self.i_graph.rollback_to(i_mark);
        self.constraining_graph.rollback_to(constraining_mark);
    }

    fn add_current_edge(
        &mut self,
        edge: &crate::graph::OwnerEdge,
        partition: &Partition,
        update_graphs: bool,
    ) {
        let from = partition.of(edge.from);
        let to = partition.of(edge.to);
        if from == to {
            return;
        }
        if edge.reason.is_rebind() {
            self.cross_rebinds.insert(
                edge.id,
                CrossRebindEdge {
                    from,
                    to,
                    owner_edge: edge.id,
                },
            );
            return;
        }

        if update_graphs {
            self.i_graph.increment_edge(from, to);
        }
        if !edge.reason.constrains_init_order() {
            return;
        }
        if update_graphs {
            self.constraining_graph.increment_edge(from, to);
        }
        let bucket = self.constraining_buckets.entry((from, to)).or_default();
        bucket.insert_edge(edge.id, edge.reason.is_sequenced());
    }

    fn remove_current_edge(
        &mut self,
        edge: &crate::graph::OwnerEdge,
        partition: &Partition,
        update_graphs: bool,
    ) {
        let from = partition.of(edge.from);
        let to = partition.of(edge.to);
        if from == to {
            return;
        }
        if edge.reason.is_rebind() {
            self.cross_rebinds.remove(&edge.id);
            return;
        }

        if update_graphs {
            self.i_graph.decrement_edge(from, to);
        }
        if !edge.reason.constrains_init_order() {
            return;
        }
        if update_graphs {
            self.constraining_graph.decrement_edge(from, to);
        }
        let pair = (from, to);
        let mut remove_bucket = false;
        if let Some(bucket) = self.constraining_buckets.get_mut(&pair) {
            bucket.remove_edge(edge.id, edge.reason.is_sequenced());
            remove_bucket = bucket.is_empty();
        }
        if remove_bucket {
            self.constraining_buckets.remove(&pair);
        }
    }

    fn verdict(&self) -> RealizabilityVerdict {
        let mut verdict = RealizabilityVerdict {
            unrealizable_sccs: Vec::new(),
            cross_rebinds: self.cross_rebinds.values().cloned().collect(),
        };
        let mut reported = BTreeSet::<BTreeSet<ModuleId>>::new();

        for modules in self.constraining_graph.all_sccs() {
            if modules.len() < 2 {
                continue;
            }
            let constraining_owner_edges = self.constraining_edges_inside(&modules);
            reported.insert(modules.clone());
            verdict.unrealizable_sccs.push(UnrealizableScc {
                modules,
                constraining_owner_edges,
            });
        }

        let mut candidates: Vec<BTreeSet<ModuleId>> = Vec::new();
        for modules in self.i_graph.all_sccs() {
            if modules.len() < 2 || reported.contains(&modules) {
                continue;
            }
            let constraining_owner_edges = self.constraining_edges_inside(&modules);
            if constraining_owner_edges.is_empty() {
                continue;
            }
            candidates.push(modules);
        }
        if !candidates.is_empty() {
            let simulation = self.build_simulator(None);
            let constraining_pairs: BTreeSet<(ModuleId, ModuleId)> =
                self.constraining_buckets.keys().copied().collect();
            for modules in candidates {
                let tdz_pairs: Vec<(ModuleId, ModuleId)> = simulation
                    .tdz_pairs(&modules, &constraining_pairs)
                    .collect();
                if tdz_pairs.is_empty() {
                    continue;
                }
                let constraining_owner_edges = self.tdz_constraining_edges(&tdz_pairs, None);
                verdict.unrealizable_sccs.push(UnrealizableScc {
                    modules,
                    constraining_owner_edges,
                });
            }
        }

        verdict
    }

    fn verdict_touching(&self, module: ModuleId) -> RealizabilityVerdict {
        let mut verdict = RealizabilityVerdict {
            unrealizable_sccs: Vec::new(),
            cross_rebinds: self.cross_rebinds_touching(module),
        };
        let mut reported = BTreeSet::<BTreeSet<ModuleId>>::new();

        let constraining_modules = self.constraining_graph.scc_containing(module);
        if constraining_modules.len() >= 2 {
            let constraining_owner_edges = self.constraining_edges_inside(&constraining_modules);
            reported.insert(constraining_modules.clone());
            verdict.unrealizable_sccs.push(UnrealizableScc {
                modules: constraining_modules,
                constraining_owner_edges,
            });
        }

        let i_modules = self.i_graph.scc_containing(module);
        if i_modules.len() >= 2 && !reported.contains(&i_modules) {
            let any_constraining = self
                .constraining_buckets
                .keys()
                .any(|(from, to)| i_modules.contains(from) && i_modules.contains(to));
            if any_constraining {
                let simulation = self.build_simulator(None);
                let constraining_pairs: BTreeSet<(ModuleId, ModuleId)> =
                    self.constraining_buckets.keys().copied().collect();
                let tdz_pairs: Vec<(ModuleId, ModuleId)> = simulation
                    .tdz_pairs(&i_modules, &constraining_pairs)
                    .collect();
                if !tdz_pairs.is_empty() {
                    let constraining_owner_edges = self.tdz_constraining_edges(&tdz_pairs, None);
                    verdict.unrealizable_sccs.push(UnrealizableScc {
                        modules: i_modules,
                        constraining_owner_edges,
                    });
                }
            }
        }

        verdict
    }

    fn verdict_with_overlay_touching(
        &self,
        module: ModuleId,
        overlay: &QuotientOverlay,
    ) -> RealizabilityVerdict {
        let mut verdict = RealizabilityVerdict {
            unrealizable_sccs: Vec::new(),
            cross_rebinds: self.cross_rebinds_touching_with_overlay(module, overlay),
        };
        let mut reported = BTreeSet::<BTreeSet<ModuleId>>::new();

        let constraining_graph =
            OverlayGraphView::new(&self.constraining_graph, &overlay.constraining_delta);
        let constraining_modules = constraining_graph.scc_containing(module);
        if constraining_modules.len() >= 2 {
            let constraining_owner_edges =
                self.constraining_edges_inside_with_overlay(&constraining_modules, overlay);
            reported.insert(constraining_modules.clone());
            verdict.unrealizable_sccs.push(UnrealizableScc {
                modules: constraining_modules,
                constraining_owner_edges,
            });
        }

        let i_graph_view = OverlayGraphView::new(&self.i_graph, &overlay.i_delta);
        let i_modules = i_graph_view.scc_containing(module);
        if i_modules.len() >= 2 && !reported.contains(&i_modules) {
            let constraining_pairs = self.constraining_pairs_with_overlay(overlay);
            let any_inside_scc = constraining_pairs.iter().any(|(from, to)| {
                i_modules.contains(from)
                    && i_modules.contains(to)
                    && !self
                        .constraining_bucket_with_overlay((*from, *to), overlay)
                        .is_empty()
            });
            if any_inside_scc {
                let simulation = self.build_simulator(Some(overlay));
                let effective_pairs: BTreeSet<(ModuleId, ModuleId)> = constraining_pairs
                    .into_iter()
                    .filter(|pair| {
                        !self
                            .constraining_bucket_with_overlay(*pair, overlay)
                            .is_empty()
                    })
                    .collect();
                let tdz_pairs: Vec<(ModuleId, ModuleId)> =
                    simulation.tdz_pairs(&i_modules, &effective_pairs).collect();
                if !tdz_pairs.is_empty() {
                    let constraining_owner_edges =
                        self.tdz_constraining_edges(&tdz_pairs, Some(overlay));
                    verdict.unrealizable_sccs.push(UnrealizableScc {
                        modules: i_modules,
                        constraining_owner_edges,
                    });
                }
            }
        }

        verdict
    }

    /// Resolve a list of TDZ-violating `(from, to)` pairs to their
    /// owner-edge ids, optionally applying `overlay`'s edits. Used
    /// by `verdict*` to surface only the surgical set of
    /// constraining edges the simulator flagged.
    fn tdz_constraining_edges(
        &self,
        tdz_pairs: &[(ModuleId, ModuleId)],
        overlay: Option<&QuotientOverlay>,
    ) -> Vec<OwnerEdgeId> {
        let mut edges: Vec<OwnerEdgeId> = Vec::new();
        for &pair in tdz_pairs {
            let bucket = match overlay {
                Some(overlay) => self.constraining_bucket_with_overlay(pair, overlay),
                None => self
                    .constraining_buckets
                    .get(&pair)
                    .cloned()
                    .unwrap_or_default(),
            };
            edges.extend(bucket.evidence_edges());
        }
        edges.sort();
        edges
    }

    /// Build an ESM evaluation simulator from the current quotient
    /// state, optionally applying `overlay`'s I-graph and
    /// constraining-pair edits. Used by every `verdict*` to decide
    /// whether Lemma 2 rescues a candidate asymmetric I-SCC.
    fn build_simulator(&self, overlay: Option<&QuotientOverlay>) -> EsmEvaluationSimulator {
        let mut i_successors: BTreeMap<ModuleId, BTreeSet<ModuleId>> = BTreeMap::new();
        let i_view = match overlay {
            Some(overlay) => Some(OverlayGraphView::new(&self.i_graph, &overlay.i_delta)),
            None => None,
        };
        let i_pairs: BTreeSet<(ModuleId, ModuleId)> = if let Some(view) = &i_view {
            // Effective edges = base ∪ added, with effective_count > 0.
            let mut pairs: BTreeSet<(ModuleId, ModuleId)> = BTreeSet::new();
            for (from, to) in self.i_graph.edge_pairs() {
                if view.effective_count(from, to) > 0 {
                    pairs.insert((from, to));
                }
            }
            for (&(from, to), &count) in &overlay.unwrap().i_delta {
                if count > 0 && view.effective_count(from, to) > 0 {
                    pairs.insert((from, to));
                }
            }
            pairs
        } else {
            self.i_graph.edge_pairs().collect()
        };
        for (from, to) in &i_pairs {
            i_successors.entry(*from).or_default().insert(*to);
        }
        let constraining_pairs: BTreeSet<(ModuleId, ModuleId)> = match overlay {
            Some(overlay) => self
                .constraining_pairs_with_overlay(overlay)
                .into_iter()
                .filter(|pair| {
                    // Drop pairs whose bucket emptied under the
                    // overlay's edits — they no longer carry a
                    // constraining edge after the hypothetical move.
                    !self
                        .constraining_bucket_with_overlay(*pair, overlay)
                        .is_empty()
                })
                .collect(),
            None => self.constraining_buckets.keys().copied().collect(),
        };
        EsmEvaluationSimulator::build(i_successors, &constraining_pairs, self.residual)
    }

    fn overlay_for_move(
        &self,
        owner_graph: &OwnerGraph,
        partition: &Partition,
        owners: &[OwnerId],
        to: ModuleId,
    ) -> QuotientOverlay {
        let owners: BTreeSet<OwnerId> = owners.iter().copied().collect();
        let impacted_owners: Vec<OwnerId> = owners.iter().copied().collect();
        let impacted_edges = impacted_owner_edges(owner_graph, &impacted_owners);
        let mut overlay = QuotientOverlay::default();
        for edge_id in impacted_edges {
            let edge = &owner_graph.edges[edge_id.0];
            let current = edge_contribution(edge, partition.of(edge.from), partition.of(edge.to));
            let next_from = if owners.contains(&edge.from) {
                to
            } else {
                partition.of(edge.from)
            };
            let next_to = if owners.contains(&edge.to) {
                to
            } else {
                partition.of(edge.to)
            };
            let next = edge_contribution(edge, next_from, next_to);
            if current == next {
                continue;
            }
            if let Some(contribution) = current {
                overlay.remove_contribution(contribution);
            }
            if let Some(contribution) = next {
                overlay.add_contribution(contribution);
            }
        }
        overlay
    }

    fn cross_rebinds_touching_with_overlay(
        &self,
        module: ModuleId,
        overlay: &QuotientOverlay,
    ) -> Vec<CrossRebindEdge> {
        let mut rebinds: Vec<CrossRebindEdge> = self
            .cross_rebinds
            .iter()
            .filter(|(edge_id, rebind)| {
                !overlay.cross_rebind_removed.contains(edge_id)
                    && (rebind.from == module || rebind.to == module)
            })
            .map(|(_, rebind)| rebind.clone())
            .collect();
        rebinds.extend(
            overlay
                .cross_rebind_added
                .values()
                .filter(|rebind| rebind.from == module || rebind.to == module)
                .cloned(),
        );
        rebinds.sort_by_key(|rebind| rebind.owner_edge);
        rebinds
    }

    fn cross_rebinds_touching(&self, module: ModuleId) -> Vec<CrossRebindEdge> {
        let mut rebinds: Vec<CrossRebindEdge> = self
            .cross_rebinds
            .values()
            .filter(|rebind| rebind.from == module || rebind.to == module)
            .cloned()
            .collect();
        rebinds.sort_by_key(|rebind| rebind.owner_edge);
        rebinds
    }

    fn constraining_edges_inside(&self, modules: &BTreeSet<ModuleId>) -> Vec<OwnerEdgeId> {
        let mut edges = Vec::new();
        for ((from, to), bucket) in &self.constraining_buckets {
            if modules.contains(from) && modules.contains(to) {
                edges.extend(bucket.evidence_edges());
            }
        }
        edges.sort();
        edges
    }

    fn constraining_edges_inside_with_overlay(
        &self,
        modules: &BTreeSet<ModuleId>,
        overlay: &QuotientOverlay,
    ) -> Vec<OwnerEdgeId> {
        let mut edges = Vec::new();
        for pair in self.constraining_pairs_with_overlay(overlay) {
            if modules.contains(&pair.0) && modules.contains(&pair.1) {
                edges.extend(
                    self.constraining_bucket_with_overlay(pair, overlay)
                        .evidence_edges(),
                );
            }
        }
        edges.sort();
        edges
    }

    fn constraining_pairs_with_overlay(
        &self,
        overlay: &QuotientOverlay,
    ) -> BTreeSet<(ModuleId, ModuleId)> {
        let mut pairs: BTreeSet<(ModuleId, ModuleId)> =
            self.constraining_buckets.keys().copied().collect();
        pairs.extend(overlay.constraining_added.keys().copied());
        pairs.extend(overlay.constraining_removed.keys().copied());
        pairs
    }

    fn constraining_bucket_with_overlay(
        &self,
        pair: (ModuleId, ModuleId),
        overlay: &QuotientOverlay,
    ) -> ConstrainingBucket {
        let mut bucket = self
            .constraining_buckets
            .get(&pair)
            .cloned()
            .unwrap_or_default();
        if let Some(removed) = overlay.constraining_removed.get(&pair) {
            bucket.remove_from(removed);
        }
        if let Some(added) = overlay.constraining_added.get(&pair) {
            bucket.extend_from(added);
        }
        bucket
    }
}

/// Mutable index over a working partition. The single shared
/// implementation of the three-clause predicate, exposed in the
/// transactional shape DESIGN.md "Realizability primitive" prescribes.
///
/// Each `push` snapshots the prior assignments of the touched owners,
/// updates only quotient edge buckets incident to those owners, and
/// records enough graph state for LIFO undo. `verdict()` reads the
/// maintained quotient graph instead of rebuilding it from owner edges.
pub struct RealizabilityIndex<'g> {
    owner_graph: &'g OwnerGraph,
    partition: Partition,
    quotient: IncrementalQuotient,
    journal: Vec<JournalEntry>,
}

impl<'g> RealizabilityIndex<'g> {
    pub fn from_partition(owner_graph: &'g OwnerGraph, partition: Partition) -> Self {
        let quotient = IncrementalQuotient::new(owner_graph, &partition);
        Self {
            owner_graph,
            partition,
            quotient,
            journal: Vec::new(),
        }
    }

    /// Borrow the current working partition. Callers should treat this
    /// as read-only — mutation should go through `push`/`undo` so the
    /// journal stays consistent.
    pub fn partition(&self) -> &Partition {
        &self.partition
    }

    /// Apply `delta` and record its inverse on the journal. Returns a
    /// handle that the matching `undo` consumes.
    ///
    /// Prefer [`Self::scoped`] when the delta lifetime is lexical —
    /// the `push`/`undo` pair is then guaranteed to be balanced and
    /// LIFO-ordered without manual bookkeeping. Use raw `push`/`undo`
    /// only when the lifetime crosses control-flow boundaries that
    /// `scoped` can't span.
    pub fn push(&mut self, delta: PartitionDelta) -> DeltaHandle {
        let entry = match delta {
            PartitionDelta::MoveOwners { owners, to } => {
                let owners: Vec<OwnerId> = owners
                    .into_iter()
                    .collect::<BTreeSet<_>>()
                    .into_iter()
                    .collect();
                let impacted_edges = impacted_owner_edges(self.owner_graph, &owners);
                let (i_graph_mark, constraining_graph_mark) = self.quotient.marks();
                for edge_id in &impacted_edges {
                    let edge = &self.owner_graph.edges[edge_id.0];
                    self.quotient
                        .remove_current_edge(edge, &self.partition, true);
                }

                let mut prior = Vec::with_capacity(owners.len());
                for owner in owners {
                    let was = self.partition.of(owner);
                    if was != to {
                        self.partition.set(owner, to);
                    }
                    prior.push((owner, was));
                }
                for edge_id in &impacted_edges {
                    let edge = &self.owner_graph.edges[edge_id.0];
                    self.quotient.add_current_edge(edge, &self.partition, true);
                }
                JournalEntry {
                    prior_assignments: prior,
                    impacted_edges,
                    i_graph_mark,
                    constraining_graph_mark,
                }
            }
        };
        let handle = DeltaHandle(self.journal.len());
        self.journal.push(entry);
        handle
    }

    /// Roll back the delta identified by `handle`. Must be the top of
    /// the journal; debug builds panic otherwise.
    pub fn undo(&mut self, handle: DeltaHandle) {
        debug_assert_eq!(
            handle.0 + 1,
            self.journal.len(),
            "RealizabilityIndex::undo called out of LIFO order \
             (handle {:?}, journal depth {})",
            handle,
            self.journal.len(),
        );
        let entry = self
            .journal
            .pop()
            .expect("journal must be non-empty for undo");
        for edge_id in &entry.impacted_edges {
            let edge = &self.owner_graph.edges[edge_id.0];
            self.quotient
                .remove_current_edge(edge, &self.partition, false);
        }
        for (owner, prior) in entry.prior_assignments {
            self.partition.set(owner, prior);
        }
        for edge_id in &entry.impacted_edges {
            let edge = &self.owner_graph.edges[edge_id.0];
            self.quotient.add_current_edge(edge, &self.partition, false);
        }
        self.quotient
            .rollback_graphs(entry.i_graph_mark, entry.constraining_graph_mark);
    }

    /// Apply `delta`, run `f` against the index in its post-push
    /// state, then undo. The scoped form guarantees the per-call
    /// push/undo pair regardless of `f`'s control flow.
    pub fn scoped<F, R>(&mut self, delta: PartitionDelta, f: F) -> R
    where
        F: FnOnce(&mut Self) -> R,
    {
        let handle = self.push(delta);
        let result = f(self);
        self.undo(handle);
        result
    }

    /// Verdict against the current working partition. Reads the
    /// incrementally maintained quotient graph and evidence buckets.
    pub fn verdict(&self) -> RealizabilityVerdict {
        self.quotient.verdict()
    }

    /// Verdict filtered to SCCs and cross-rebinds touching `module`.
    /// Candidate evaluation uses this for the fresh hypothetical
    /// destination: unrelated pre-existing bad SCCs are intentionally
    /// ignored, matching the previous full-verdict-then-filter logic.
    pub fn verdict_touching(&self, module: ModuleId) -> RealizabilityVerdict {
        self.quotient.verdict_touching(module)
    }

    /// Verdict for a hypothetical owner move, filtered to the target
    /// module, without mutating the working partition. This is the
    /// candidate-evaluation fast path: it builds a small quotient
    /// overlay for the moved owners' incident edges and runs directed
    /// reachability against the effective graph.
    pub fn verdict_after_moving_owners_touching(
        &self,
        owners: &[OwnerId],
        to: ModuleId,
    ) -> RealizabilityVerdict {
        let overlay = self
            .quotient
            .overlay_for_move(self.owner_graph, &self.partition, owners, to);
        self.quotient.verdict_with_overlay_touching(to, &overlay)
    }
}

fn impacted_owner_edges(owner_graph: &OwnerGraph, owners: &[OwnerId]) -> Vec<OwnerEdgeId> {
    let mut impacted = BTreeSet::<OwnerEdgeId>::new();
    for owner in owners {
        impacted.extend(owner_graph.out_edges_of(*owner).iter().copied());
        impacted.extend(owner_graph.in_edges_of(*owner).iter().copied());
    }
    impacted.into_iter().collect()
}

#[cfg(test)]
mod tests {
    use std::collections::BTreeSet;

    use super::*;
    use crate::OwnerId;
    use crate::facts::analyze_chunk;
    use crate::graph::build_owner_graph;
    use crate::ids::{LogicalModuleIndex, ModuleId};
    use crate::partition::Partition;
    use crate::{AnalysisHints, OwnerGraph};
    use swc_common::{FileName, SourceMap, sync::Lrc};
    use swc_ecma_parser::{Parser, StringInput, Syntax, lexer::Lexer};

    fn module_id(index: usize) -> ModuleId {
        ModuleId(LogicalModuleIndex(index))
    }

    fn parse_and_build(source: &str) -> OwnerGraph {
        let cm: Lrc<SourceMap> = Default::default();
        let fm = cm.new_source_file(
            FileName::Custom("test.js".into()).into(),
            source.to_string(),
        );
        let lexer = Lexer::new(
            Syntax::Es(Default::default()),
            Default::default(),
            StringInput::from(&*fm),
            None,
        );
        let module = Parser::new_from(lexer)
            .parse_module()
            .expect("parse module");
        let facts = analyze_chunk(&module, &AnalysisHints::default(), None, |_| None).facts;
        build_owner_graph(&facts)
    }

    /// Two top-level constants in different modules, with one reading
    /// the other at-init across the module boundary acyclically. No
    /// cycle, no rebind — verdict is empty.
    #[test]
    fn acyclic_cross_module_at_init_read_is_realizable() {
        let source = "const a = 1; const b = a + 1;";
        let owner_graph = parse_and_build(source);
        // Owner 0: const a = 1 → module 0.
        // Owner 1: const b = a + 1 → module 1.
        // Edge owner_1 → owner_0 (eager_use of `a`).
        let mut partition = Partition::new(&owner_graph, module_id(0));
        partition.set(OwnerId(1), module_id(1));
        let verdict = check_realizability(&owner_graph, &partition);
        assert!(
            verdict.is_realizable(),
            "verdict should be empty: {verdict:#?}"
        );
    }

    /// Same setup but flipped to create a constraining cycle: both
    /// statements live in different modules and mutually at-init read
    /// the other. Quotient has a 2-cycle of constraining edges →
    /// unrealizable.
    #[test]
    fn constraining_cycle_across_two_modules_is_unrealizable() {
        // Two top-level constants whose initializers eager-read each
        // other. Real JS would TDZ at runtime, but the analyzer just
        // records the structural graph: two `eager_use` edges in
        // opposite directions. Placing them in different modules
        // forms a constraining-edge SCC of the quotient — exactly
        // what clause 3 rejects.
        let source = "const a = b + 1; const b = a + 1;";
        let owner_graph = parse_and_build(source);
        let mut partition = Partition::new(&owner_graph, module_id(0));
        partition.set(OwnerId(1), module_id(1));
        let verdict = check_realizability(&owner_graph, &partition);
        assert!(
            !verdict.is_realizable(),
            "verdict should report an SCC: {verdict:#?}"
        );
        let modules: BTreeSet<ModuleId> = verdict.modules_in_unrealizable_sccs();
        assert!(modules.contains(&module_id(0)));
        assert!(modules.contains(&module_id(1)));
        assert!(
            verdict
                .unrealizable_sccs
                .iter()
                .all(|scc| !scc.constraining_owner_edges.is_empty()),
            "every SCC must carry owner-edge evidence"
        );
    }

    /// A pure lazy-read cycle (mutual references inside function
    /// bodies) is realizable: ESM evaluates the lazy side first, no
    /// TDZ. Verdict must be empty even when the modules form a cycle
    /// in the *full* quotient.
    #[test]
    fn pure_lazy_cycle_is_realizable() {
        let source = "function a() { return b(); } function b() { return a(); }";
        let owner_graph = parse_and_build(source);
        let mut partition = Partition::new(&owner_graph, module_id(0));
        partition.set(OwnerId(1), module_id(1));
        let verdict = check_realizability(&owner_graph, &partition);
        assert!(
            verdict.is_realizable(),
            "lazy-only cycle should be realizable: {verdict:#?}"
        );
    }

    /// Asymmetric I-cycle `{mod_dep, mod_dependent}` with eager
    /// `mod_dependent → mod_dep` and lazy `mod_dep → mod_dependent`.
    /// Residual (`module_id(0)`) at-init-reads both, so residual has
    /// I-edges into the SCC and Lemma 2 rescues — the simulator's
    /// post-order puts mod_dep's body before mod_dependent's body.
    /// Verdict must be empty.
    #[test]
    fn lemma_two_rescues_asymmetric_cycle_when_residual_imports_scc() {
        // owner_0 (residual): const a = 1; (also reads b, lazy_reader at-init via console.log)
        // owner_1 (mod_dep): const dep_value = "alpha"
        // owner_2 (mod_dep): function lazy_reader() { return cross_value; }
        // owner_3 (mod_dependent): const cross_value = dep_value + "-beta"
        // owner_4 (residual): console.log reads dep_value, cross_value, lazy_reader at-init
        let source = "const dep_value = \"alpha\"; const cross_value = dep_value + \"-beta\"; function lazy_reader() { return cross_value; } console.log(dep_value, cross_value, lazy_reader());";
        let owner_graph = parse_and_build(source);
        let mut partition = Partition::new(&owner_graph, module_id(0));
        // dep_value (owner 0) → mod_dep, cross_value (owner 1) →
        // mod_dependent, lazy_reader (owner 2) → mod_dep,
        // console.log (owner 3) stays in residual (= module_id(0)).
        partition.set(OwnerId(0), module_id(1));
        partition.set(OwnerId(1), module_id(2));
        partition.set(OwnerId(2), module_id(1));
        let verdict = check_realizability(&owner_graph, &partition);
        assert!(
            verdict.is_realizable(),
            "Lemma 2 should rescue this shape; verdict: {verdict:#?}",
        );
    }

    /// Same SCC shape but residual has NO direct I-edge into the
    /// SCC — residual only reaches the SCC through `mod_mediator`,
    /// whose imports are sorted by `linker_position` (dependency
    /// first). The simulator's DFS enters `mod_dep` first via
    /// mediator; mod_dep's lazy back-edge to mod_dependent fires;
    /// mod_dependent body evaluates with dep_value uninitialized.
    /// Verdict must report the SCC.
    #[test]
    fn mediator_only_entrant_into_asymmetric_cycle_is_unrealizable() {
        // owner_0: const dep_value = "alpha"
        // owner_1: const cross_value = dep_value + "-beta"
        // owner_2: function lazy_reader() { return cross_value; }
        // owner_3: function mediator_helper() { return dep_value + lazy_reader(); }
        // owner_4: const mediator_init = mediator_helper(); (at-init promotes
        //          to a constraining edge into the dep_value owner —
        //          mediator → mod_dep eager)
        // owner_5: console.log(mediator_init); (residual at-init)
        let source = "const dep_value = \"alpha\"; const cross_value = dep_value + \"-beta\"; function lazy_reader() { return cross_value; } function mediator_helper() { return dep_value + lazy_reader(); } const mediator_init = mediator_helper(); console.log(mediator_init);";
        let owner_graph = parse_and_build(source);
        let mut partition = Partition::new(&owner_graph, module_id(0));
        partition.set(OwnerId(0), module_id(1)); // dep_value → mod_dep
        partition.set(OwnerId(1), module_id(2)); // cross_value → mod_dependent
        partition.set(OwnerId(2), module_id(1)); // lazy_reader → mod_dep
        partition.set(OwnerId(3), module_id(3)); // mediator_helper → mod_mediator
        partition.set(OwnerId(4), module_id(3)); // mediator_init → mod_mediator
        // owner_5 (console.log) stays in residual.
        let verdict = check_realizability(&owner_graph, &partition);
        assert!(
            !verdict.is_realizable(),
            "mediator-only entrant should trigger TDZ; verdict: {verdict:#?}",
        );
        let modules = verdict.modules_in_unrealizable_sccs();
        assert!(modules.contains(&module_id(1)) && modules.contains(&module_id(2)));
    }

    /// Residual is the source of a constraining edge into the SCC,
    /// but the SCC also has a constraining-target-residual edge.
    /// Lemma 2 fails: residual is the DFS root and evaluates last in
    /// post-order; the SCC member reading residual's binding TDZs.
    #[test]
    fn constraining_edge_into_residual_inside_scc_is_unrealizable() {
        // owner_0: class Backend { ... } (residual, TDZ-locked target)
        // owner_1: let currentLogger; (mod_logger)
        // owner_2: function setLogger(impl) { currentLogger = impl; ... } (mod_logger)
        // owner_3: setLogger(new Backend()); (mod_logger, at-init reads Backend)
        // owner_4: console.log(currentLogger.tag); (residual, lazy read of currentLogger from mod_logger via re-export)
        let source = "class Backend { constructor() { this.tag = \"B\"; } } let currentLogger; function setLogger(impl) { currentLogger = impl; globalThis.__tag = impl.tag; } setLogger(new Backend()); console.log(currentLogger);";
        let owner_graph = parse_and_build(source);
        let mut partition = Partition::new(&owner_graph, module_id(0));
        // Backend (owner 0) stays in residual.
        partition.set(OwnerId(1), module_id(1)); // currentLogger → mod_logger
        partition.set(OwnerId(2), module_id(1)); // setLogger → mod_logger
        partition.set(OwnerId(3), module_id(1)); // setLogger(new Backend()) → mod_logger
        // owner 4 (console.log) stays in residual.
        let verdict = check_realizability(&owner_graph, &partition);
        // mod_logger → residual EagerUse (constraining target = residual)
        // residual → mod_logger LazyUse (re-export / console.log)
        // SCC = {residual, mod_logger}. Constraining edge target = residual.
        // Residual is DFS root; mod_logger body runs first, reads Backend → TDZ.
        assert!(
            !verdict.is_realizable(),
            "constraining edge target=residual must TDZ; verdict: {verdict:#?}",
        );
    }

    /// All owners in the same module → no cross-destination edges of
    /// any kind → empty verdict.
    #[test]
    fn single_module_is_always_realizable() {
        let source = "const a = 1; const b = a + 1; const c = a * b;";
        let owner_graph = parse_and_build(source);
        let partition = Partition::new(&owner_graph, module_id(0));
        let verdict = check_realizability(&owner_graph, &partition);
        assert!(verdict.is_realizable());
    }

    /// Pushing a delta on the index and reading the verdict matches
    /// the pure function on the post-push partition. Undo restores the
    /// pre-push verdict exactly.
    #[test]
    fn index_push_undo_roundtrips_verdict() {
        let source = "const a = b + 1; const b = a + 1;";
        let owner_graph = parse_and_build(source);

        let baseline = Partition::new(&owner_graph, module_id(0));
        let baseline_verdict = check_realizability(&owner_graph, &baseline);
        assert!(baseline_verdict.is_realizable());

        let mut index = RealizabilityIndex::from_partition(&owner_graph, baseline.clone());
        let handle = index.push(PartitionDelta::MoveOwners {
            owners: vec![OwnerId(1)],
            to: module_id(1),
        });
        // After push: matches the explicitly-built post-delta partition.
        let mut hypothetical = baseline.clone();
        hypothetical.set(OwnerId(1), module_id(1));
        let hypothetical_verdict = check_realizability(&owner_graph, &hypothetical);
        assert_eq!(
            index.verdict().unrealizable_sccs.len(),
            hypothetical_verdict.unrealizable_sccs.len(),
        );
        assert!(!index.verdict().is_realizable());

        index.undo(handle);
        // After undo: matches the baseline exactly.
        assert!(index.verdict().is_realizable());
        for owner_id in 0..owner_graph.nodes.len() {
            assert_eq!(
                index.partition().of(OwnerId(owner_id)),
                baseline.of(OwnerId(owner_id)),
                "partition slot {owner_id} should be restored by undo",
            );
        }
    }

    #[test]
    fn duplicate_owner_ids_are_journaled_once() {
        let source = "const a = 1; const b = a + 1;";
        let owner_graph = parse_and_build(source);
        let baseline = Partition::new(&owner_graph, module_id(0));
        let mut index = RealizabilityIndex::from_partition(&owner_graph, baseline.clone());

        let handle = index.push(PartitionDelta::MoveOwners {
            owners: vec![OwnerId(1), OwnerId(1)],
            to: module_id(1),
        });
        assert_eq!(index.partition().of(OwnerId(1)), module_id(1));

        index.undo(handle);
        assert_eq!(index.partition().of(OwnerId(1)), baseline.of(OwnerId(1)));
        assert_eq!(
            normalize_verdict(index.verdict()),
            normalize_verdict(check_realizability(&owner_graph, &baseline)),
        );
    }

    #[test]
    fn move_overlay_matches_scoped_verdict_touching() {
        let source = "const a = b + 1; const b = a + 1;";
        let owner_graph = parse_and_build(source);
        let baseline = Partition::new(&owner_graph, module_id(0));
        let mut index = RealizabilityIndex::from_partition(&owner_graph, baseline.clone());
        let before = normalize_verdict(index.verdict());

        let overlay = index.verdict_after_moving_owners_touching(&[OwnerId(1)], module_id(1));
        let scoped = index.scoped(
            PartitionDelta::MoveOwners {
                owners: vec![OwnerId(1)],
                to: module_id(1),
            },
            |idx| idx.verdict_touching(module_id(1)),
        );

        assert_eq!(normalize_verdict(overlay), normalize_verdict(scoped));
        assert_eq!(
            normalize_verdict(index.verdict()),
            before,
            "overlay query must not mutate the working partition",
        );
        assert_eq!(index.partition().of(OwnerId(1)), baseline.of(OwnerId(1)));
    }

    #[test]
    fn move_overlay_reports_cross_rebinds_like_scoped_verdict() {
        let source = "let a = 0; function b() { a = 1; }";
        let owner_graph = parse_and_build(source);
        let baseline = Partition::new(&owner_graph, module_id(0));
        let mut index = RealizabilityIndex::from_partition(&owner_graph, baseline);

        let overlay = index.verdict_after_moving_owners_touching(&[OwnerId(1)], module_id(1));
        let scoped = index.scoped(
            PartitionDelta::MoveOwners {
                owners: vec![OwnerId(1)],
                to: module_id(1),
            },
            |idx| idx.verdict_touching(module_id(1)),
        );

        assert_eq!(
            normalize_verdict(overlay.clone()),
            normalize_verdict(scoped)
        );
        assert!(overlay.unrealizable_sccs.is_empty());
        assert_eq!(overlay.cross_rebinds.len(), 1);
    }

    #[test]
    fn move_overlay_masks_removed_current_edges() {
        let source = "const a = b + 1; const b = c + 1; const c = 1;";
        let owner_graph = parse_and_build(source);
        let mut baseline = Partition::new(&owner_graph, module_id(0));
        baseline.set(OwnerId(0), module_id(1));
        baseline.set(OwnerId(1), module_id(2));
        baseline.set(OwnerId(2), module_id(3));
        let mut explicit = baseline.clone();
        explicit.set(OwnerId(1), module_id(4));
        let mut index = RealizabilityIndex::from_partition(&owner_graph, baseline);

        let overlay = index.verdict_after_moving_owners_touching(&[OwnerId(1)], module_id(4));
        let scoped = index.scoped(
            PartitionDelta::MoveOwners {
                owners: vec![OwnerId(1)],
                to: module_id(4),
            },
            |idx| idx.verdict_touching(module_id(4)),
        );
        let pure =
            filter_verdict_touching(&check_realizability(&owner_graph, &explicit), module_id(4));

        assert_eq!(
            normalize_verdict(overlay.clone()),
            normalize_verdict(scoped)
        );
        assert_eq!(normalize_verdict(overlay), normalize_verdict(pure));
    }

    /// `scoped` runs the closure with the delta applied and undoes on
    /// return — even when the closure returns a value.
    #[test]
    fn index_scoped_isolates_per_call_state() {
        let source = "const a = b + 1; const b = a + 1;";
        let owner_graph = parse_and_build(source);

        let baseline = Partition::new(&owner_graph, module_id(0));
        let mut index = RealizabilityIndex::from_partition(&owner_graph, baseline.clone());

        let inside_verdict_realizable = index.scoped(
            PartitionDelta::MoveOwners {
                owners: vec![OwnerId(1)],
                to: module_id(1),
            },
            |idx| idx.verdict().is_realizable(),
        );
        assert!(
            !inside_verdict_realizable,
            "inside the scope the cycle exists"
        );

        // After scoped: state restored exactly.
        assert!(index.verdict().is_realizable());
        assert_eq!(index.partition().of(OwnerId(1)), module_id(0));
    }

    #[test]
    fn incremental_index_matches_pure_verdict_through_nested_push_undo() {
        let source = "const a = b + 1; const b = a + 1; function c() { return a; }";
        let owner_graph = parse_and_build(source);

        let baseline = Partition::new(&owner_graph, module_id(0));
        let mut explicit = baseline.clone();
        let mut index = RealizabilityIndex::from_partition(&owner_graph, baseline.clone());

        assert_eq!(
            normalize_verdict(index.verdict()),
            normalize_verdict(check_realizability(&owner_graph, &explicit)),
        );

        let first = index.push(PartitionDelta::MoveOwners {
            owners: vec![OwnerId(1)],
            to: module_id(1),
        });
        explicit.set(OwnerId(1), module_id(1));
        assert_eq!(
            normalize_verdict(index.verdict()),
            normalize_verdict(check_realizability(&owner_graph, &explicit)),
        );

        let second = index.push(PartitionDelta::MoveOwners {
            owners: vec![OwnerId(2)],
            to: module_id(2),
        });
        explicit.set(OwnerId(2), module_id(2));
        assert_eq!(
            normalize_verdict(index.verdict()),
            normalize_verdict(check_realizability(&owner_graph, &explicit)),
        );

        index.undo(second);
        explicit.set(OwnerId(2), module_id(0));
        assert_eq!(
            normalize_verdict(index.verdict()),
            normalize_verdict(check_realizability(&owner_graph, &explicit)),
        );

        index.undo(first);
        explicit.set(OwnerId(1), module_id(0));
        assert_eq!(
            normalize_verdict(index.verdict()),
            normalize_verdict(check_realizability(&owner_graph, &explicit)),
        );
        for owner in 0..owner_graph.nodes.len() {
            assert_eq!(
                index.partition().of(OwnerId(owner)),
                baseline.of(OwnerId(owner))
            );
        }
    }

    #[test]
    fn verdict_touching_matches_full_verdict_filtered_to_module() {
        let source = "const a = b + 1; const b = a + 1; const c = 1;";
        let owner_graph = parse_and_build(source);
        let baseline = Partition::new(&owner_graph, module_id(0));
        let mut index = RealizabilityIndex::from_partition(&owner_graph, baseline);
        index.push(PartitionDelta::MoveOwners {
            owners: vec![OwnerId(1)],
            to: module_id(1),
        });
        index.push(PartitionDelta::MoveOwners {
            owners: vec![OwnerId(2)],
            to: module_id(2),
        });

        let full = index.verdict();
        assert_eq!(
            normalize_verdict(index.verdict_touching(module_id(1))),
            normalize_verdict(filter_verdict_touching(&full, module_id(1))),
        );
        assert_eq!(
            normalize_verdict(index.verdict_touching(module_id(2))),
            normalize_verdict(filter_verdict_touching(&full, module_id(2))),
            "unrelated module should not inherit the a/b SCC",
        );
    }

    #[test]
    fn incremental_index_reports_cross_rebinds_without_scc_edges() {
        let source = "let a = 0; function b() { a = 1; }";
        let owner_graph = parse_and_build(source);
        let baseline = Partition::new(&owner_graph, module_id(0));
        let mut explicit = baseline.clone();
        let mut index = RealizabilityIndex::from_partition(&owner_graph, baseline);

        index.push(PartitionDelta::MoveOwners {
            owners: vec![OwnerId(1)],
            to: module_id(1),
        });
        explicit.set(OwnerId(1), module_id(1));

        let verdict = index.verdict();
        assert_eq!(
            normalize_verdict(verdict.clone()),
            normalize_verdict(check_realizability(&owner_graph, &explicit)),
        );
        assert!(
            verdict.unrealizable_sccs.is_empty(),
            "rebinds are direct violations, not SCC edges: {verdict:#?}",
        );
        assert_eq!(verdict.cross_rebinds.len(), 1);
        assert_eq!(
            normalize_verdict(index.verdict_touching(module_id(1))),
            normalize_verdict(verdict),
        );
    }

    type NormalizedVerdict = (
        BTreeSet<(Vec<ModuleId>, Vec<usize>)>,
        BTreeSet<(ModuleId, ModuleId, usize)>,
    );

    fn normalize_verdict(verdict: RealizabilityVerdict) -> NormalizedVerdict {
        let sccs = verdict
            .unrealizable_sccs
            .into_iter()
            .map(|scc| {
                let modules: Vec<ModuleId> = scc.modules.into_iter().collect();
                let edges: Vec<usize> = scc
                    .constraining_owner_edges
                    .into_iter()
                    .map(|edge| edge.0)
                    .collect();
                (modules, edges)
            })
            .collect();
        let rebinds = verdict
            .cross_rebinds
            .into_iter()
            .map(|rebind| (rebind.from, rebind.to, rebind.owner_edge.0))
            .collect();
        (sccs, rebinds)
    }

    fn filter_verdict_touching(
        verdict: &RealizabilityVerdict,
        module: ModuleId,
    ) -> RealizabilityVerdict {
        RealizabilityVerdict {
            unrealizable_sccs: verdict
                .unrealizable_sccs
                .iter()
                .filter(|scc| scc.modules.contains(&module))
                .cloned()
                .collect(),
            cross_rebinds: verdict
                .cross_rebinds
                .iter()
                .filter(|rebind| rebind.from == module || rebind.to == module)
                .cloned()
                .collect(),
        }
    }
}
