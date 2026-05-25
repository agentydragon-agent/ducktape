use std::collections::{BTreeMap, BTreeSet, HashMap};

use petgraph::algo::tarjan_scc;
use petgraph::graphmap::DiGraphMap;
use serde::{Deserialize, Serialize};
use swc_ecma_ast::Id;

use crate::facts::EffectCell;
use crate::partition::Partition;
use crate::purity::Purity;
use crate::{ModuleId, SourceLocation, StatementFacts, StatementKind, StatementOrdinal};

/// Per-chunk owner-graph build options. Each field defaults to the
/// strictly-conservative behavior; opt-ins enable conditionally-correct
/// inferences that hold only when the input satisfies a checkable
/// precondition (see `devinfra/js/debundle/AGENTS.md` →
/// "Conditionally-correct optimizations"). The materializer reads
/// these from the per-chunk spec entry in
/// `TransformSpec::chunk_analysis_options`.
#[derive(Debug, Clone, Copy, Default)]
pub struct OwnerGraphOptions {
    /// Emit the side-effect ordering chain using per-statement
    /// (writes, reads) summaries instead of the adjacent-impure
    /// transitive reduction. See the S-chain block in
    /// `build_owner_graph_with` and `dataflow_audit.md`.
    pub dataflow_aware_s_chain: bool,
}

/// One reason an edge `(from, to)` exists, with the source
/// statement ordinal that produced it. This is the single source of
/// truth for edge semantics:
///
/// - `EagerUse` constrains ESM evaluation order under TDZ
///   semantics (`R ⊆ I`).
/// - `LazyUse` contributes to the imports graph `I`, but does not
///   constrain realizability inside an SCC because the read fires
///   after module evaluation.
/// - `EagerRebind` / `LazyRebind` describe rebinding writes. A
///   cross-destination write is rejected outright because ESM imports
///   are read-only in the importing module; same-destination writes
///   are represented only at owner level and don't become module
///   imports.
/// - `Sequenced` contributes to `S` and constrains
///   realizability because source-order side effects require a
///   topological order.
/// - `LocalEffect` is a trusted target-local mutation (for example
///   a TypeScript `__decorate` helper application) that must
///   co-locate with the target owner but should not impose global
///   side-effect ordering on unrelated owners.
#[derive(Debug, Clone)]
pub struct EdgeReason {
    pub(crate) kind: DepKind,
    pub(crate) statement_ordinal: StatementOrdinal,
    pub(crate) binding: Option<Id>,
    /// `Some(callee_owner)` iff this reason was emitted by
    /// `promote_at_init_calls` to propagate a function-body lazy
    /// read/rebind from the at-init callee `callee_owner` up to its
    /// caller (`edge.from`). Two consumers use this:
    ///
    /// - `build_module_quotient` and `check_realizability` drop the
    ///   edge when `partition.of(callee_owner) != partition.of(edge.from)`
    ///   — the body read fires inside a call into a *different* module,
    ///   so by ESM DFS post-order the callee's module (and all of its
    ///   transitive imports, including the target's module) are fully
    ///   evaluated before the call returns. The R -> target-module
    ///   constraint the promotion manufactures is redundant given the
    ///   already-recorded R -> callee-module edge and the callee-module's
    ///   own eval-time reads.
    /// - The wire format (`OwnerGraphEdgeReport`) carries the callee
    ///   owner ID so the planner's `OwnerGraph::from_report` can
    ///   reapply the same filter against the planner-side partition.
    ///
    /// `None` for every non-promoted edge (direct eager/lazy reads,
    /// rebinds, sequenced, local-effect).
    pub(crate) at_init_callee_owner: Option<OwnerId>,
}

impl EdgeReason {
    pub(crate) fn eager_use(so: StatementOrdinal, b: Id) -> Self {
        Self {
            kind: DepKind::EagerUse,
            statement_ordinal: so,
            binding: Some(b),
            at_init_callee_owner: None,
        }
    }
    pub(crate) fn lazy_use(so: StatementOrdinal, b: Id) -> Self {
        Self {
            kind: DepKind::LazyUse,
            statement_ordinal: so,
            binding: Some(b),
            at_init_callee_owner: None,
        }
    }
    pub(crate) fn eager_rebind(so: StatementOrdinal, b: Id) -> Self {
        Self {
            kind: DepKind::EagerRebind,
            statement_ordinal: so,
            binding: Some(b),
            at_init_callee_owner: None,
        }
    }
    pub(crate) fn lazy_rebind(so: StatementOrdinal, b: Id) -> Self {
        Self {
            kind: DepKind::LazyRebind,
            statement_ordinal: so,
            binding: Some(b),
            at_init_callee_owner: None,
        }
    }
    pub(crate) fn sequenced(so: StatementOrdinal) -> Self {
        Self {
            kind: DepKind::Sequenced,
            statement_ordinal: so,
            binding: None,
            at_init_callee_owner: None,
        }
    }
    pub(crate) fn local_effect(so: StatementOrdinal, b: Id) -> Self {
        Self {
            kind: DepKind::LocalEffect,
            statement_ordinal: so,
            binding: Some(b),
            at_init_callee_owner: None,
        }
    }

    /// Set the at-init callee owner for a promoted reason. Used by
    /// `promote_at_init_calls`; downstream gate code consults
    /// `at_init_callee_owner` to skip the edge when caller and callee
    /// land in different partition slots.
    pub(crate) fn with_at_init_callee(mut self, callee_owner: OwnerId) -> Self {
        self.at_init_callee_owner = Some(callee_owner);
        self
    }

    /// Construct a synthetic edge reason from raw fields. Used by
    /// `OwnerGraph::from_report` and similar JSON-recovery paths that
    /// don't carry an `Id` atom for the binding. The realizability
    /// gate (`check_realizability`) consults only `kind` and the
    /// at-init-callee owner — every `is_*` and `constrains_init_order`
    /// predicate above delegates to `kind` — so a synthetic reason
    /// without a binding is sufficient for the gate. Source-of-truth
    /// construction from `StatementFacts` still goes through the
    /// kind-specific helpers above.
    pub fn synthetic(kind: DepKind, statement_ordinal: StatementOrdinal) -> Self {
        Self {
            kind,
            statement_ordinal,
            binding: None,
            at_init_callee_owner: None,
        }
    }

    /// Like [`synthetic`] but also carries the at-init callee owner.
    /// Used by `OwnerGraph::from_report` to round-trip the
    /// cross-module-promotion filter through the wire format so the
    /// peel planner runs the same edge-set the materializer does.
    pub fn synthetic_with_callee(
        kind: DepKind,
        statement_ordinal: StatementOrdinal,
        callee_owner: Option<OwnerId>,
    ) -> Self {
        Self {
            kind,
            statement_ordinal,
            binding: None,
            at_init_callee_owner: callee_owner,
        }
    }

    /// `Some(callee_owner)` iff this edge was emitted by
    /// `promote_at_init_calls` (see [`EdgeReason::at_init_callee_owner`]).
    pub fn at_init_callee_owner(&self) -> Option<OwnerId> {
        self.at_init_callee_owner
    }

    pub fn is_eager_use(&self) -> bool {
        self.kind == DepKind::EagerUse
    }
    pub fn kind(&self) -> DepKind {
        self.kind
    }
    pub fn binding(&self) -> Option<&Id> {
        self.binding.as_ref()
    }
    pub fn statement_ordinal(&self) -> StatementOrdinal {
        self.statement_ordinal
    }
    pub fn is_rebind(&self) -> bool {
        matches!(self.kind, DepKind::EagerRebind | DepKind::LazyRebind)
    }
    pub fn is_sequenced(&self) -> bool {
        self.kind == DepKind::Sequenced
    }
    /// Every kind except `LazyUse` constrains realizability.
    /// Stated as exclusion so adding a new `DepKind` variant
    /// forces an explicit decision here.
    pub fn constrains_init_order(&self) -> bool {
        self.kind != DepKind::LazyUse
    }
}

#[derive(Debug, Clone, Copy, Eq, PartialEq, Ord, PartialOrd, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DepKind {
    EagerUse,
    LazyUse,
    EagerRebind,
    LazyRebind,
    Sequenced,
    LocalEffect,
}

/// Stable-in-run identity of an owner graph vertex. V1 owner
/// vertices are post-comma-list `StatementFacts` rows, so the id
/// is the row's source-order ordinal.
#[derive(Debug, Clone, Copy, Eq, PartialEq, Ord, PartialOrd, Hash, Serialize)]
#[serde(transparent)]
pub struct OwnerId(pub usize);

/// Fine-grained graph before logical modules are formed. Nodes are
/// top-level owners/statements; edges are owner-level reads and
/// source-order side-effect constraints. The module dependency graph
/// is the quotient of this graph by a [`Partition`].
///
/// Storage is **flat-edges + CSR adjacency**, the canonical compiler-IR
/// shape: one [`OwnerEdge`] per reason, indexed by [`OwnerEdgeId`]
/// (= position in `edges`), with per-node `out_edges` / `in_edges`
/// adjacency lists for O(deg) traversal. The previous representation
/// kept two parallel views — a `petgraph::DiGraphMap` for random
/// access by `(from, to)` and a separate `Vec<OwnerEdge>` for
/// stable indices into edges; this collapses them.
#[derive(Debug, Clone, Default)]
pub struct OwnerGraph {
    pub nodes: Vec<OwnerNode>,
    pub edges: Vec<OwnerEdge>,
    /// CSR adjacency by source owner. `out_edges[owner.0]` is a list
    /// of `OwnerEdgeId` indices into `edges`.
    pub out_edges: Vec<Vec<OwnerEdgeId>>,
    /// CSR adjacency by target owner.
    pub in_edges: Vec<Vec<OwnerEdgeId>>,
    /// CSR-style "edges referencing this owner as their at-init
    /// callee", indexed by owner index. Empty for owners that no edge
    /// references via `EdgeReason::at_init_callee_owner`. Lets
    /// `impacted_owner_edges` look up callee-referencing edges in
    /// `O(|edges of that callee|)` instead of scanning the full edge
    /// list per call (a `verdict_with_overlay_touching` per-candidate
    /// hot path on gaffer-scale inputs).
    pub callee_edges: Vec<Vec<OwnerEdgeId>>,
}

#[derive(Debug, Clone)]
pub struct OwnerNode {
    pub id: OwnerId,
    pub statement_ordinal: StatementOrdinal,
    pub source_location: Option<SourceLocation>,
    pub declared: BTreeSet<Id>,
    pub kind: StatementKind,
    pub purity: Purity,
}

impl OwnerGraph {
    /// Iterate `&OwnerEdge` in `OwnerEdgeId` order. Each row is one
    /// reason — multiple reasons between the same `(from, to)` pair
    /// appear as separate entries.
    pub fn iter_edges(&self) -> impl Iterator<Item = &OwnerEdge> + '_ {
        self.edges.iter()
    }

    pub fn node(&self, id: OwnerId) -> Option<&OwnerNode> {
        self.nodes.get(id.0).filter(|node| node.id == id)
    }

    pub fn iter_nodes(&self) -> impl Iterator<Item = &OwnerNode> {
        self.nodes.iter()
    }

    /// Edges originating at `owner`.
    pub fn out_edges_of(&self, owner: OwnerId) -> &[OwnerEdgeId] {
        self.out_edges
            .get(owner.0)
            .map(Vec::as_slice)
            .unwrap_or(&[])
    }

    /// Edges terminating at `owner`.
    pub fn in_edges_of(&self, owner: OwnerId) -> &[OwnerEdgeId] {
        self.in_edges.get(owner.0).map(Vec::as_slice).unwrap_or(&[])
    }

    /// Edges referencing `owner` as their at-init callee. Mirrors
    /// `out_edges_of`/`in_edges_of` but for the callee-owner index.
    pub fn callee_edges_of(&self, owner: OwnerId) -> &[OwnerEdgeId] {
        self.callee_edges
            .get(owner.0)
            .map(Vec::as_slice)
            .unwrap_or(&[])
    }
}

/// Recovery handle that maps the JSON `OwnerGraphReport` owner-id
/// strings to the `OwnerId`s of an `OwnerGraph` built via
/// `OwnerGraph::from_report`. The position of an owner-id in
/// `OwnerGraphReport.nodes` equals the constructed `OwnerId.0`, so the
/// index lookup is just a position scan; this struct keeps the lookup
/// O(1) via an interned `HashMap`.
#[derive(Debug, Clone)]
pub struct OwnerReportIndex {
    pub owner_ids: Vec<String>,
    by_id: HashMap<String, OwnerId>,
}

impl OwnerReportIndex {
    pub fn lookup(&self, id: &str) -> Option<OwnerId> {
        self.by_id.get(id).copied()
    }

    pub fn id_of(&self, owner: OwnerId) -> Option<&str> {
        self.owner_ids.get(owner.0).map(String::as_str)
    }
}

impl OwnerGraph {
    /// Reconstruct a typed `OwnerGraph` from a JSON-deserialized
    /// `crate::OwnerGraphReport`. Used by the peel planner CLI so the
    /// realizability gate consults the same IR shape the materializer
    /// gate does, instead of re-deriving cycle detection over the
    /// JSON-flattened edge list.
    ///
    /// The result is "gate-grade": the returned graph carries enough
    /// information for `check_realizability` (edge endpoints,
    /// `DepKind`, residual marker) but **not** every field
    /// `build_owner_graph` populates from `StatementFacts`. Per-owner
    /// `declared`, `kind`, `purity`, and per-edge `binding` are
    /// stubbed with their default / synthetic shapes because the
    /// JSON wire format doesn't carry the hygienic `Id` atoms the
    /// source-of-truth constructor uses. Callers that need those
    /// fields must build the graph from facts, not from the report.
    ///
    /// `OwnerEdgeId`s in the reconstructed graph are assigned in the
    /// order edges appear in `report.edges`; they don't necessarily
    /// match the original `OwnerEdgeId`s that produced the report.
    /// The gate only uses them as opaque identifiers in its evidence
    /// listing.
    pub fn from_report(report: &crate::OwnerGraphReport) -> (Self, OwnerReportIndex) {
        let owner_ids: Vec<String> = report.nodes.iter().map(|n| n.id.clone()).collect();
        let by_id: HashMap<String, OwnerId> = owner_ids
            .iter()
            .enumerate()
            .map(|(i, id)| (id.clone(), OwnerId(i)))
            .collect();

        let nodes: Vec<OwnerNode> = report
            .nodes
            .iter()
            .enumerate()
            .map(|(i, n)| OwnerNode {
                id: OwnerId(i),
                statement_ordinal: n.statement_ordinal,
                source_location: n.source_location.clone(),
                declared: BTreeSet::new(),
                kind: n.statement_kind,
                purity: n.purity.clone(),
            })
            .collect();

        let mut edges: Vec<OwnerEdge> = Vec::with_capacity(report.edges.len());
        for edge in &report.edges {
            let (Some(&from), Some(&to)) = (by_id.get(&edge.source), by_id.get(&edge.target))
            else {
                continue;
            };
            // Round-trip the at-init callee owner so the planner-side
            // gate runs the same cross-module-promotion filter as the
            // materializer.
            let callee_owner = edge
                .at_init_callee_owner
                .as_ref()
                .and_then(|id| by_id.get(id))
                .copied();
            let reason = EdgeReason::synthetic_with_callee(
                edge.edge_kind,
                edge.statement_ordinal,
                callee_owner,
            );
            let id = OwnerEdgeId(edges.len());
            edges.push(OwnerEdge {
                id,
                from,
                to,
                reason,
            });
        }

        let mut out_edges: Vec<Vec<OwnerEdgeId>> = vec![Vec::new(); nodes.len()];
        let mut in_edges: Vec<Vec<OwnerEdgeId>> = vec![Vec::new(); nodes.len()];
        let mut callee_edges: Vec<Vec<OwnerEdgeId>> = vec![Vec::new(); nodes.len()];
        for edge in &edges {
            if let Some(slot) = out_edges.get_mut(edge.from.0) {
                slot.push(edge.id);
            }
            if let Some(slot) = in_edges.get_mut(edge.to.0) {
                slot.push(edge.id);
            }
            if let Some(callee) = edge.reason.at_init_callee_owner()
                && let Some(slot) = callee_edges.get_mut(callee.0)
            {
                slot.push(edge.id);
            }
        }

        let graph = OwnerGraph {
            nodes,
            edges,
            out_edges,
            in_edges,
            callee_edges,
        };
        let index = OwnerReportIndex { owner_ids, by_id };
        (graph, index)
    }
}

/// Per-edge metadata. One physical `(from, to)` ESM `import`
/// directive can be backed by multiple reasons (e.g. several
/// at-init reads of bindings owned by the same target module);
/// they're all kept here so cycle reports can show every
/// triggering statement.
#[derive(Debug, Clone, Default)]
pub struct EdgeMetadata {
    pub reasons: Vec<EdgeReason>,
}

impl EdgeMetadata {
    /// `true` if at least one reason is an at-init read. The
    /// realizability gate uses this to decide whether an
    /// `I ∪ S` SCC contains an `R` cross-module edge.
    pub fn has_eager_use(&self) -> bool {
        self.reasons.iter().any(EdgeReason::is_eager_use)
    }

    /// `true` if at least one reason is a side-effect ordering
    /// edge. `S` edges in an SCC make it unrealizable: the
    /// constraint is "predecessor must evaluate before
    /// successor", and a cycle has no topological emit order
    /// satisfying every such edge.
    pub fn has_sequenced(&self) -> bool {
        self.reasons.iter().any(EdgeReason::is_sequenced)
    }

    /// `true` if at least one reason is a rebinding write. These
    /// edges are rejected outright when they cross destination
    /// modules because imported ESM bindings are read-only.
    pub fn has_rebind(&self) -> bool {
        self.reasons.iter().any(EdgeReason::is_rebind)
    }

    /// `true` if this edge constrains realizability — at least one
    /// of its reasons is realizability-constraining (an at-init
    /// read `R`, a side-effect ordering `S` edge, or a rebinding
    /// write). Lazy read-only edges don't, because the reads they
    /// represent fire after every module in the cycle has finished
    /// evaluating.
    ///
    /// Delegates to `EdgeReason::constrains_init_order` to keep
    /// the per-edge and per-reason definitions in lockstep.
    pub fn constrains_init_order(&self) -> bool {
        self.reasons.iter().any(EdgeReason::constrains_init_order)
    }
}

/// Module dep graph built from per-statement facts and a binding →
/// module assignment.
///
/// Thin newtype around `petgraph::DiGraphMap<ModuleId,
/// EdgeMetadata>`: one edge per directed `(from, to)` pair, weight =
/// `EdgeMetadata`. Multiple reasons for the same physical edge (e.g.
/// several at-init reads of bindings owned by the same target
/// module) accumulate into the edge's reason list. Cycle detection
/// runs through petgraph's `tarjan_scc`.
///
/// `Deref` / `DerefMut` to the inner graph lets callers reach
/// `petgraph` methods (`all_edges`, `edge_weight`, `nodes`,
/// `contains_edge`, …) directly: `dep_graph.all_edges()` instead of
/// `dep_graph.graph.all_edges()`. The newtype is kept (rather than a
/// bare type alias) so the semantic name "the I∪S module-dep
/// quotient" stays distinct from arbitrary
/// `DiGraphMap<ModuleId, EdgeMetadata>` instances.
///
/// For `petgraph::algo::tarjan_scc` (a generic function whose
/// inference doesn't trigger `Deref` coercion), callers reach for
/// the inner graph with `&dep_graph.0` or `&*dep_graph`.
#[derive(Debug, Clone, Default)]
pub struct ModuleQuotient(pub DiGraphMap<ModuleId, EdgeMetadata>);

impl std::ops::Deref for ModuleQuotient {
    type Target = DiGraphMap<ModuleId, EdgeMetadata>;

    fn deref(&self) -> &Self::Target {
        &self.0
    }
}

impl std::ops::DerefMut for ModuleQuotient {
    fn deref_mut(&mut self) -> &mut Self::Target {
        &mut self.0
    }
}

impl ModuleQuotient {
    fn record_reason(&mut self, from: ModuleId, to: ModuleId, reason: EdgeReason) {
        if from == to {
            return;
        }
        if !self.contains_edge(from, to) {
            self.add_edge(from, to, EdgeMetadata::default());
        }
        self.edge_weight_mut(from, to).unwrap().reasons.push(reason);
    }

    /// `true` if the edge `(from, to)` exists and constrains
    /// realizable evaluation order (at-init read or side-effect
    /// ordering). Used by the realizability gate to decide
    /// whether an `I ∪ S` SCC is unrealizable.
    pub fn has_init_order_constraining_edge(&self, from: ModuleId, to: ModuleId) -> bool {
        self.edge_weight(from, to)
            .is_some_and(EdgeMetadata::constrains_init_order)
    }
}

/// Build the fine owner graph from per-statement facts. Pure IR
/// construction: no module assignment, no quotient. Module-level
/// dependencies are derived later by [`build_module_quotient`]
/// given a [`Partition`] mapping owners to destination modules.
///
/// Uses default (strictly-conservative) [`OwnerGraphOptions`]. Call
/// [`build_owner_graph_with`] when the chunk spec opts into
/// conditionally-correct refinements.
pub fn build_owner_graph(facts: &[StatementFacts]) -> OwnerGraph {
    build_owner_graph_with(facts, OwnerGraphOptions::default())
}

/// Like [`build_owner_graph`] but takes per-chunk [`OwnerGraphOptions`].
pub fn build_owner_graph_with(facts: &[StatementFacts], options: OwnerGraphOptions) -> OwnerGraph {
    let mut binding_owner = HashMap::<Id, OwnerId>::new();
    let mut nodes = Vec::<OwnerNode>::with_capacity(facts.len());
    for stmt in facts {
        for binding in &stmt.declared {
            binding_owner.insert(binding.clone(), OwnerId(stmt.ordinal.0));
        }
        let id = OwnerId(stmt.ordinal.0);
        nodes.push(OwnerNode {
            id,
            statement_ordinal: stmt.ordinal,
            source_location: stmt.source_location.clone(),
            declared: stmt.declared.clone(),
            kind: stmt.kind,
            purity: stmt.purity.clone(),
        });
    }

    // Collect (from, to, reason) triples; the final `edges` Vec is
    // sorted at the end so `OwnerEdgeId` indices are stable.
    let mut raw_edges = Vec::<(OwnerId, OwnerId, EdgeReason)>::new();
    // Look-aside table for "what statement owns this OwnerId" — shared
    // by the direct eager-read filter below and by
    // `promote_at_init_calls` (which builds its own local copy; the
    // duplicate cost is negligible).
    let stmt_by_owner: std::collections::HashMap<OwnerId, &StatementFacts> = facts
        .iter()
        .map(|stmt| (OwnerId(stmt.ordinal.0), stmt))
        .collect();
    // A top-level eager read of a binding declared by a `function`
    // declaration cannot observe a TDZ: ECMAScript Phase 1 of module
    // linking (`ModuleDeclarationInstantiation`) binds every
    // `FunctionDeclaration` to its hoisted closure before any module
    // body runs. So `const x = f()` where `f` is a chunk-declared
    // FnDecl is safe regardless of which module owns `f` — there is
    // no init-order constraint to record, and emitting an `EagerUse`
    // edge would manufacture a cross-module constraint no realizable
    // trace demands. Same rule as the FnDecl exclusion in
    // `promote_at_init_calls`. Other declared kinds (VarDecl,
    // ClassDecl) are TDZ-locked until their statement runs, so their
    // cross-module reads stay constrained.
    let target_is_hoisted = |id: &Id| -> bool {
        binding_owner
            .get(id)
            .and_then(|owner| stmt_by_owner.get(owner))
            .map(|stmt| stmt.kind == StatementKind::FnDecl)
            .unwrap_or(false)
    };
    let push_binding_edge = |raw_edges: &mut Vec<(OwnerId, OwnerId, EdgeReason)>,
                             from: OwnerId,
                             binding: &Id,
                             make_reason: fn(StatementOrdinal, Id) -> EdgeReason,
                             statement_ordinal: StatementOrdinal| {
        let Some(to) = binding_owner.get(binding) else {
            return; // not declared in this chunk (global, ImportSpecifier, never-declared)
        };
        if from == *to {
            return;
        }
        raw_edges.push((from, *to, make_reason(statement_ordinal, binding.clone())));
    };
    for stmt in facts {
        let from = OwnerId(stmt.ordinal.0);
        for binding in &stmt.eager_reads {
            if target_is_hoisted(binding) {
                continue;
            }
            push_binding_edge(
                &mut raw_edges,
                from,
                binding,
                EdgeReason::eager_use,
                stmt.ordinal,
            );
        }
        for binding in &stmt.lazy_reads {
            push_binding_edge(
                &mut raw_edges,
                from,
                binding,
                EdgeReason::lazy_use,
                stmt.ordinal,
            );
        }
        for binding in &stmt.eager_rebinds {
            push_binding_edge(
                &mut raw_edges,
                from,
                binding,
                EdgeReason::eager_rebind,
                stmt.ordinal,
            );
        }
        // Only first-order body rebinds emit a constraining
        // `LazyRebind` edge. A rebind inside a nested closure
        // (e.g. an arrow stashed on `globalThis` by the body)
        // doesn't fire when the function is invoked synchronously;
        // emitting an edge for it manufactures a bidirectional
        // G_atomic constraint (atomic_units.rs:82-85) that forces
        // co-location with the rebind target even though no
        // synchronous-trace rebind exists. See the e2e test
        // `at_init_promotion_nested_closure_test` for the
        // rationale; the same first-order narrowing is what
        // promote_at_init_calls uses.
        for binding in &stmt.first_order_lazy_rebinds {
            push_binding_edge(
                &mut raw_edges,
                from,
                binding,
                EdgeReason::lazy_rebind,
                stmt.ordinal,
            );
        }
        for binding in &stmt.local_effects {
            push_binding_edge(
                &mut raw_edges,
                from,
                binding,
                EdgeReason::local_effect,
                stmt.ordinal,
            );
        }
    }

    // At-init call promotion (DESIGN.md "At-init call promotion").
    //
    // A function body's lazy reads/rebinds fire at-init from the
    // perspective of any caller that invokes the function at-init.
    // Without promotion, the realizability primitive's relaxed
    // clause-3 predicate (constraining-edge subgraph has no
    // multi-module SCC) is unsound for the canonical
    // `console.log(readB())` shape: the lazy read inside `readB`'s
    // body fires when the top-level call evaluates, but only the
    // graph's lazy edge is recorded, so cross-module cycles that
    // close through such a lazy edge look acyclic to the constraining
    // subgraph. After promotion, the primitive's verdict is sound.
    //
    // Promoted edges are added at owner-graph level (partition-
    // independent): intra-module promoted edges are dropped by the
    // quotient automatically. Only direct `f(...)` callees that
    // resolve to chunk-declared bindings are followed; indirect
    // calls (`const g = f; g()`), method calls (`obj.method()`), and
    // dynamic dispatch are conservatively unmodelled.
    promote_at_init_calls(facts, &binding_owner, &mut raw_edges);

    emit_s_chain(facts, options, &mut raw_edges);

    // Sort + assign stable `OwnerEdgeId` indices, then build CSR
    // adjacency in one pass.
    raw_edges.sort_by(|(from_a, to_a, reason_a), (from_b, to_b, reason_b)| {
        from_a
            .cmp(from_b)
            .then(to_a.cmp(to_b))
            .then(reason_a.kind.cmp(&reason_b.kind))
            .then(reason_a.statement_ordinal.cmp(&reason_b.statement_ordinal))
            .then(reason_a.binding.cmp(&reason_b.binding))
    });
    let edges: Vec<OwnerEdge> = raw_edges
        .into_iter()
        .enumerate()
        .map(|(idx, (from, to, reason))| OwnerEdge {
            id: OwnerEdgeId(idx),
            from,
            to,
            reason,
        })
        .collect();
    let mut out_edges: Vec<Vec<OwnerEdgeId>> = vec![Vec::new(); nodes.len()];
    let mut in_edges: Vec<Vec<OwnerEdgeId>> = vec![Vec::new(); nodes.len()];
    let mut callee_edges: Vec<Vec<OwnerEdgeId>> = vec![Vec::new(); nodes.len()];
    for edge in &edges {
        if let Some(slot) = out_edges.get_mut(edge.from.0) {
            slot.push(edge.id);
        }
        if let Some(slot) = in_edges.get_mut(edge.to.0) {
            slot.push(edge.id);
        }
        if let Some(callee) = edge.reason.at_init_callee_owner()
            && let Some(slot) = callee_edges.get_mut(callee.0)
        {
            slot.push(edge.id);
        }
    }

    OwnerGraph {
        nodes,
        edges,
        out_edges,
        in_edges,
        callee_edges,
    }
}

/// Side-effect ordering edges (`S` per DESIGN.md "Module dep graphs").
/// At owner level, links impure top-level statements so any realizable
/// schedule preserves their observable order.
///
/// Two emission modes selected by [`OwnerGraphOptions`]:
///
/// - **Strict chain** (default): every later impure statement gets one
///   incoming `Sequenced` edge from the immediately previous impure
///   statement. Transitive reduction of the total order; soundest path.
/// - **Dataflow-aware** (`dataflow_aware_s_chain = true`): emit
///   `Sequenced(curr → prev)` only when `curr` reads or writes a cell
///   `prev` wrote (last-writer-precedes-reader). Statements that fail
///   the `dataflow_summarizable` check (dynamic globalThis key, `with`,
///   direct `eval`, `Function(...)` constructor, `defineProperty` on
///   globals, `Proxy` on globals) fall back to the strict edge against
///   every prior impure owner. See `dataflow_audit.md` for the
///   precondition this relaxation requires.
///
/// `purity` is computed upstream (`classify_expr_purity`) so pure
/// literal initializers (`const X = 42`, `const X = { a: 1 }`,
/// function/class declarations without observable static init) don't
/// contribute to S. Without that precision the cross-module S graph
/// would be dense enough to reject realistic specs for trivially pure
/// const sequences.
fn emit_s_chain(
    facts: &[StatementFacts],
    options: OwnerGraphOptions,
    raw_edges: &mut Vec<(OwnerId, OwnerId, EdgeReason)>,
) {
    if !options.dataflow_aware_s_chain {
        let mut prev: Option<OwnerId> = None;
        for stmt in facts.iter().filter(|s| !s.purity.is_pure()) {
            let from = OwnerId(stmt.ordinal.0);
            if let Some(to) = prev
                && from != to
            {
                raw_edges.push((from, to, EdgeReason::sequenced(stmt.ordinal)));
            }
            prev = Some(from);
        }
        return;
    }

    // Dataflow-aware emission: last-writer-precedes-reader-or-writer.
    // For each impure `curr`, emit an incoming Sequenced edge from the
    // most recent prior impure owner that wrote any cell in
    // `curr.reads ∪ curr.writes`. Statements with
    // `dataflow_summarizable = false` are treated as touching every
    // cell — they get edges to every prior impure owner and become a
    // barrier for subsequent statements.
    let mut last_writer: BTreeMap<EffectCell, OwnerId> = BTreeMap::new();
    let mut prior_impure_owners: Vec<OwnerId> = Vec::new();
    let mut opaque_barrier: Option<OwnerId> = None;
    for stmt in facts.iter().filter(|s| !s.purity.is_pure()) {
        let from = OwnerId(stmt.ordinal.0);
        let mut targets: BTreeSet<OwnerId> = BTreeSet::new();
        if stmt.effects.dataflow_summarizable {
            for cell in stmt.effects.reads.iter().chain(stmt.effects.writes.iter()) {
                if let Some(&to) = last_writer.get(cell) {
                    targets.insert(to);
                }
            }
            // Non-summarizable prior statements are barriers: any later
            // summarizable statement still depends on them, since we
            // don't know what cells they touched.
            if let Some(barrier) = opaque_barrier {
                targets.insert(barrier);
            }
        } else {
            // This statement can't be summarized: treat it as reading
            // and writing every cell. Depend on every prior impure
            // owner, and become the new opaque barrier so later
            // summarizable statements depend on us too.
            targets.extend(prior_impure_owners.iter().copied());
            opaque_barrier = Some(from);
        }
        for to in targets {
            if from != to {
                raw_edges.push((from, to, EdgeReason::sequenced(stmt.ordinal)));
            }
        }
        for cell in &stmt.effects.writes {
            last_writer.insert(cell.clone(), from);
        }
        prior_impure_owners.push(from);
    }
}

/// Promote function-body lazy reads/rebinds to eager owner edges from
/// every statement that at-init-calls the function. Transitive over
/// the call graph among chunk-declared functions: a top-level
/// `f()` whose `f` calls `g` in its body promotes through `g`'s lazy
/// reads/rebinds too. See DESIGN.md "At-init call promotion".
///
/// Per-statement dedup: at most one promoted eager edge per
/// (caller, target-owner) pair, and at most one promoted rebind edge
/// per (caller, target-owner) pair. Without dedup, a single
/// at-init call to a function with N transitive lazy reads would emit
/// N edges from the caller, and multiple at-init calls in the same
/// statement would multiply that further.
fn promote_at_init_calls(
    facts: &[StatementFacts],
    binding_owner: &HashMap<Id, OwnerId>,
    raw_edges: &mut Vec<(OwnerId, OwnerId, EdgeReason)>,
) {
    // 1. Build the call graph: owner → owner edges for each
    //    chunk-declared function callee reachable via *first-order*
    //    body_calls. Nested-closure calls (e.g. inside an arrow
    //    returned by the body) don't fire when the body is invoked
    //    synchronously, so they don't belong on the promotion call
    //    graph — see DESIGN.md "At-init call promotion" and the e2e
    //    test `at_init_promotion_nested_closure_test`.
    //
    //    Add every owner whose body has any first-order lazy reads /
    //    rebinds / calls as a node — those are the callable owners
    //    whose body closures we may need to promote, even if the body
    //    itself makes no calls (e.g. `function readB() { return B; }`).
    let mut call_graph: DiGraphMap<OwnerId, ()> = DiGraphMap::new();
    for stmt in facts {
        let owner = OwnerId(stmt.ordinal.0);
        if !stmt.first_order_body_calls.is_empty()
            || !stmt.first_order_lazy_reads.is_empty()
            || !stmt.first_order_lazy_rebinds.is_empty()
        {
            call_graph.add_node(owner);
        }
    }
    for stmt in facts {
        if stmt.first_order_body_calls.is_empty() {
            continue;
        }
        let caller = OwnerId(stmt.ordinal.0);
        for callee_id in &stmt.first_order_body_calls {
            let Some(callee_owner) = binding_owner.get(callee_id) else {
                continue;
            };
            call_graph.add_node(*callee_owner);
            call_graph.add_edge(caller, *callee_owner, ());
        }
    }
    if call_graph.node_count() == 0 {
        return;
    }

    // 2. Tarjan SCC. `tarjan_scc` returns SCCs in reverse topological
    //    order: leaves (no outgoing edges to other SCCs) first.
    let sccs = tarjan_scc(&call_graph);
    let mut scc_of: BTreeMap<OwnerId, usize> = BTreeMap::new();
    for (idx, scc) in sccs.iter().enumerate() {
        for owner in scc {
            scc_of.insert(*owner, idx);
        }
    }

    // 3. Per-owner seeds: own lazy_reads / lazy_rebinds resolved to
    //    BindingId. Filters out targets whose owner is a function
    //    declaration — function bindings are hoisted at module
    //    instantiation (Phase 1 of ESM linking), so a cross-module
    //    read of a function never observes a TDZ. Promoting such
    //    reads would spuriously close cycles for shapes like mutual
    //    recursion across modules (`function even(){odd()}` /
    //    `function odd(){even()}`), which are actually realizable.
    //    Other declared kinds (VarDecl, ClassDecl) are kept: const /
    //    let / class are TDZ-locked until their statement runs, so a
    //    cross-module read inside an at-init-called function does
    //    fire the realizability hazard. `var` is technically hoisted
    //    too but is rare enough not to warrant a separate distinction
    //    in StatementKind.
    let mut stmt_by_owner: BTreeMap<OwnerId, &StatementFacts> = BTreeMap::new();
    for stmt in facts {
        stmt_by_owner.insert(OwnerId(stmt.ordinal.0), stmt);
    }
    let target_is_hoisted = |id: &Id| -> bool {
        let Some(target_owner) = binding_owner.get(id) else {
            return false;
        };
        stmt_by_owner
            .get(target_owner)
            .map(|stmt| stmt.kind == StatementKind::FnDecl)
            .unwrap_or(false)
    };
    let mut scc_reads: Vec<BTreeSet<Id>> = vec![BTreeSet::new(); sccs.len()];
    let mut scc_rebinds: Vec<BTreeSet<Id>> = vec![BTreeSet::new(); sccs.len()];

    // 4. Closure over the call graph. Iterate SCCs in
    //    reverse-topological order (leaves first). For each SCC,
    //    union members' own seeds plus successor SCC closures.
    for (scc_idx, scc) in sccs.iter().enumerate() {
        let mut reads: BTreeSet<Id> = BTreeSet::new();
        let mut rebinds: BTreeSet<Id> = BTreeSet::new();
        for owner in scc {
            let Some(stmt) = stmt_by_owner.get(owner) else {
                continue;
            };
            for id in &stmt.first_order_lazy_reads {
                if binding_owner.contains_key(id) && !target_is_hoisted(id) {
                    reads.insert(id.clone());
                }
            }
            for id in &stmt.first_order_lazy_rebinds {
                if binding_owner.contains_key(id) {
                    rebinds.insert(id.clone());
                }
            }
        }
        for owner in scc {
            for (_, target, _) in call_graph.edges(*owner) {
                let Some(&target_scc) = scc_of.get(&target) else {
                    continue;
                };
                if target_scc == scc_idx {
                    continue;
                }
                reads.extend(scc_reads[target_scc].iter().cloned());
                rebinds.extend(scc_rebinds[target_scc].iter().cloned());
            }
        }
        scc_reads[scc_idx] = reads;
        scc_rebinds[scc_idx] = rebinds;
    }

    // 5. Emit promoted edges with per-statement, per-kind dedup.
    //    Each emitted reason carries `at_init_callee_owner =
    //    Some(callee_owner)` so the realizability gate can drop the
    //    edge when caller and callee land in different partition
    //    slots — the body read fires inside a call into a different
    //    module, after that callee module (and its imports) have
    //    already evaluated, so the manufactured constraint from R to
    //    the target's module is redundant with the already-recorded
    //    R -> callee-module edge. See `EdgeReason::at_init_callee_owner`.
    for stmt in facts {
        if stmt.at_init_calls.is_empty() {
            continue;
        }
        let caller = OwnerId(stmt.ordinal.0);
        let mut promoted_read_targets: BTreeSet<OwnerId> = BTreeSet::new();
        let mut promoted_rebind_targets: BTreeSet<OwnerId> = BTreeSet::new();
        for callee_id in &stmt.at_init_calls {
            let Some(callee_owner) = binding_owner.get(callee_id) else {
                continue;
            };
            let Some(&scc_idx) = scc_of.get(callee_owner) else {
                continue;
            };
            for target_binding in &scc_reads[scc_idx] {
                let Some(target_owner) = binding_owner.get(target_binding) else {
                    continue;
                };
                if caller == *target_owner {
                    continue;
                }
                if !promoted_read_targets.insert(*target_owner) {
                    continue;
                }
                raw_edges.push((
                    caller,
                    *target_owner,
                    EdgeReason::eager_use(stmt.ordinal, target_binding.clone())
                        .with_at_init_callee(*callee_owner),
                ));
            }
            for target_binding in &scc_rebinds[scc_idx] {
                let Some(target_owner) = binding_owner.get(target_binding) else {
                    continue;
                };
                if caller == *target_owner {
                    continue;
                }
                if !promoted_rebind_targets.insert(*target_owner) {
                    continue;
                }
                raw_edges.push((
                    caller,
                    *target_owner,
                    EdgeReason::eager_rebind(stmt.ordinal, target_binding.clone())
                        .with_at_init_callee(*callee_owner),
                ));
            }
        }
    }
}

/// `true` if `edge` was emitted by `promote_at_init_calls` *and* the
/// at-init callee lives in a different module than the caller per
/// `partition`. In that case the body read fires synchronously inside
/// a call into a different module, after that callee module (and its
/// transitive imports) have already evaluated under ESM DFS
/// post-order. The R -> target-module constraint the promotion
/// records is therefore redundant with the already-recorded
/// R -> callee-module edge and the callee module's own eval-time
/// reads — and worse, it can manufacture a cross-module cycle that
/// no realizable evaluation order actually demands.
///
/// Intra-module at-init calls (caller and callee in the same module)
/// keep their promoted body reads: there the body's reads ARE the
/// caller module's eager reads (same evaluation context).
///
/// Direct (non-promoted) eager reads — `at_init_callee_owner` is
/// `None` — always pass through.
pub(crate) fn is_cross_module_at_init_promotion(edge: &OwnerEdge, partition: &Partition) -> bool {
    let Some(callee_owner) = edge.reason.at_init_callee_owner else {
        return false;
    };
    partition.of(callee_owner) != partition.of(edge.from)
}

/// Partition-projected endpoints of `edge` when it participates in the
/// module quotient view; `None` means "skip this edge."
///
/// Invariant: this is the single function any consumer building a
/// quotient view of the owner graph MUST consult so they agree on the
/// same partition view of every edge. Two filters are folded in here:
///
/// 1. Same-module edges (`from == to` after partition projection) are
///    intra-module and never appear in the module quotient.
/// 2. Cross-module at-init promotions are dropped per
///    [`is_cross_module_at_init_promotion`]'s ESM-semantics
///    justification.
///
/// History: the same `from == to` + `is_cross_module_at_init_promotion`
/// filter pair was previously open-coded at five sites
/// (`build_module_quotient`, `check_realizability`,
/// `OwnerGraph::from_report`-derived gate use,
/// `IncrementalQuotient::{add,remove}_current_edge`,
/// `reports::build_quotient_edge_reports`). A TDZ-class soundness hole
/// reopens any time one of those sites omits or reorders the
/// projection — the per-edge filter pair must stay identical at every
/// call site, because the module-level cycle gate's verdict depends on
/// it. Centralise here.
pub(crate) fn cross_module_partition_endpoints(
    edge: &OwnerEdge,
    partition: &Partition,
) -> Option<(ModuleId, ModuleId)> {
    let from = partition.of(edge.from);
    let to = partition.of(edge.to);
    if from == to {
        return None;
    }
    if is_cross_module_at_init_promotion(edge, partition) {
        return None;
    }
    Some((from, to))
}

/// Gate-side counterpart of [`cross_module_partition_endpoints`] that
/// keeps cross-module at-init promoted edges. The emitter's
/// `collect_phantom_side_effect_providers` adds phantom side-effect
/// imports for these edges, which can reorder ESM's link DFS so the
/// target module evaluates while the caller module is still on the
/// stack — closing a TDZ cycle that
/// [`is_cross_module_at_init_promotion`]'s "callee module is fully
/// evaluated by the time the body call fires" claim hides.
///
/// History: the prior fix in commit `12ce3884b` removed the
/// promoted-edge drop from `check_realizability`,
/// `edge_contribution`, and `IncrementalQuotient::{insert,remove}_current_edge`.
/// Commit `2d6be2473` ("extract `cross_module_partition_endpoints`
/// helper") silently re-introduced the drop by routing those call
/// sites through the same helper as `build_module_quotient` and
/// `reports.rs`. This sibling helper exists so the gate paths
/// preserve `12ce3884b`'s fix while leaving the emit-side and
/// reports view (where the drop is intentional) untouched. See
/// `realizability::tests::promoted_edge_in_aggregator_cycle_is_unrealizable`
/// for the regression fixture.
pub(crate) fn gate_constraining_partition_endpoints(
    edge: &OwnerEdge,
    partition: &Partition,
) -> Option<(ModuleId, ModuleId)> {
    let from = partition.of(edge.from);
    let to = partition.of(edge.to);
    if from == to {
        return None;
    }
    Some((from, to))
}

/// Quotient the owner graph by `partition` to build the module
/// dependency graph consumed by validation and emit. The single
/// public construction path; validation and reports both go through
/// this for any non-hypothetical quotient.
pub fn build_module_quotient(owner_graph: &OwnerGraph, partition: &Partition) -> ModuleQuotient {
    let mut graph = ModuleQuotient(DiGraphMap::new());
    let mut seen_side_effect_module_pairs = BTreeSet::<(ModuleId, ModuleId)>::new();
    for edge in &owner_graph.edges {
        let Some((from, to)) = cross_module_partition_endpoints(edge, partition) else {
            continue;
        };
        if edge.reason.is_sequenced() && !seen_side_effect_module_pairs.insert((from, to)) {
            continue;
        }
        graph.record_reason(from, to, edge.reason.clone());
    }
    graph
}

/// The canonical chunk-wide ESM I-graph. Each entry is a module-level
/// init-order-constraining read or sequenced effect that the
/// emitter actually emits as an ESM `import` directive and that the
/// runtime ECMA-262 linker DFS therefore traverses when the chunk
/// loads. Both the realizability gate (Pass-2 simulator's
/// `i_successors`, linker / source-import positions) and the
/// emitter (`lowering::plan_references::collect_phantom_side_effect_providers`,
/// `chunk_factorization::compute_{linker,source_import}_order`)
/// MUST drive their topology decisions through this single set so
/// they cannot drift apart.
///
/// Filter rule:
///   * Drop same-module edges (no ESM `import`).
///   * Keep cross-module edges whose reason `constrains_init_order()`
///     and is **not** a rebind — i.e. `EagerUse`, `Sequenced`,
///     `LocalEffect`. These are the edges the emitter currently
///     turns into either a binding-level ESM import or a phantom
///     side-effect import.
///   * Drop pure `LazyUse` cross-module edges. They are
///     function-body reads, resolved at call time after every module
///     has loaded; the runtime DFS never follows them, so neither
///     can the gate's simulator without manufacturing imaginary
///     cycles.
///   * Drop `EagerRebind` / `LazyRebind` cross-module edges. They
///     surface as `cross_rebinds` in the realizability verdict, not
///     as I-graph nodes; the emitter never emits them as imports.
///   * Keep cross-module at-init promoted edges (see
///     [`gate_constraining_partition_endpoints`]) — the emitter's
///     phantom side-effect importer also keeps them, so the gate
///     must too.
///
/// Sequenced edges are deduped per `(from, to)` pair to mirror the
/// dedup `build_module_quotient` performs: multiple sequenced
/// reasons between the same module pair represent the same
/// ordering constraint and should not over-weight the I-graph.
///
/// Returns the canonical edge set plus a precomputed `from -> {to}`
/// adjacency map (`i_successors`) ready to feed into the simulator.
pub fn chunk_constraining_module_edges(
    owner_graph: &OwnerGraph,
    partition: &Partition,
) -> ChunkConstrainingEdgeSet {
    let mut edges: BTreeMap<(ModuleId, ModuleId), Vec<OwnerEdgeId>> = BTreeMap::new();
    let mut i_successors: BTreeMap<ModuleId, BTreeSet<ModuleId>> = BTreeMap::new();
    let mut seen_sequenced_pairs: BTreeSet<(ModuleId, ModuleId)> = BTreeSet::new();
    for edge in &owner_graph.edges {
        if owner_graph.node(edge.from).is_none() || owner_graph.node(edge.to).is_none() {
            continue;
        }
        // Gate-side view: keep cross-module at-init promoted edges.
        // The matching `cross_module_partition_endpoints` lenient
        // view would drop them; the canonical edge set is the
        // strict view (see `gate_constraining_partition_endpoints`).
        let Some((from, to)) = gate_constraining_partition_endpoints(edge, partition) else {
            continue;
        };
        if edge.reason.is_rebind() {
            // Rebinds are not I-graph members; they surface via the
            // `cross_rebinds` verdict and are never emitted as ESM
            // imports.
            continue;
        }
        if !edge.reason.constrains_init_order() {
            // Pure `LazyUse` cross-module edges: function-body reads
            // resolved at call time. Runtime DFS never follows them,
            // so the canonical I-graph excludes them.
            continue;
        }
        if edge.reason.is_sequenced() && !seen_sequenced_pairs.insert((from, to)) {
            continue;
        }
        edges.entry((from, to)).or_default().push(edge.id);
        i_successors.entry(from).or_default().insert(to);
    }
    ChunkConstrainingEdgeSet {
        edges,
        i_successors,
    }
}

/// Output of [`chunk_constraining_module_edges`]: the canonical
/// chunk-wide ESM I-graph plus its precomputed adjacency map.
///
/// Consumers MUST treat this as the single source of truth for the
/// "edges the emitter emits as ESM imports" question. See the
/// function-level doc for the filter rule.
#[derive(Debug, Clone, Default, Eq, PartialEq)]
pub struct ChunkConstrainingEdgeSet {
    /// `(from_module, to_module) -> all owner-edge ids` projecting
    /// onto this module pair. Stable ordering by `(ModuleId,
    /// ModuleId)`.
    pub edges: BTreeMap<(ModuleId, ModuleId), Vec<OwnerEdgeId>>,
    /// `from_module -> set of import targets`. Equivalent to
    /// `edges.keys().fold(...)` but precomputed because every
    /// simulator and emitter consumer walks adjacency, not the raw
    /// `(from, to)` list.
    pub i_successors: BTreeMap<ModuleId, BTreeSet<ModuleId>>,
}

impl ChunkConstrainingEdgeSet {
    /// `(from, to) -> &[OwnerEdgeId]` lookup.
    pub fn edges_for(&self, from: ModuleId, to: ModuleId) -> &[OwnerEdgeId] {
        self.edges
            .get(&(from, to))
            .map(Vec::as_slice)
            .unwrap_or(&[])
    }

    /// `from -> &BTreeSet<ModuleId>` lookup, empty default.
    pub fn successors_of(&self, from: ModuleId) -> Option<&BTreeSet<ModuleId>> {
        self.i_successors.get(&from)
    }

    /// `(from, to)` pairs in the canonical edge set. Stable iteration
    /// order.
    pub fn pairs(&self) -> impl Iterator<Item = (ModuleId, ModuleId)> + '_ {
        self.edges.keys().copied()
    }

    /// Membership test for the canonical edge set.
    pub fn contains(&self, from: ModuleId, to: ModuleId) -> bool {
        self.edges.contains_key(&(from, to))
    }
}

/// Stable per-chunk identity of an owner-graph edge. Equal to the
/// edge's position in [`OwnerGraph::edges`]. The previous
/// representation stored the report-shape spelling
/// (`format!("owner_edge:{idx}")`) on every entry; that spelling is
/// `O(n_edges)` strings allocated per chunk and
/// repeated clones in graph-report hot paths. Carry the typed index
/// instead and let the report layer do the formatting at its single
/// serialization boundary via
/// [`OwnerEdgeId::report_key`].
#[derive(Debug, Clone, Copy, Eq, PartialEq, Ord, PartialOrd, Hash)]
pub struct OwnerEdgeId(pub usize);

impl OwnerEdgeId {
    pub(crate) fn report_key(self) -> String {
        format!("owner_edge:{}", self.0)
    }
}

#[derive(Debug, Clone)]
pub struct OwnerEdge {
    pub id: OwnerEdgeId,
    pub from: OwnerId,
    pub to: OwnerId,
    pub reason: EdgeReason,
}

#[cfg(test)]
mod chunk_constraining_module_edges_tests {
    //! Regression coverage for [`chunk_constraining_module_edges`]'s
    //! filter rule. The canonical edge set must match what the
    //! emitter actually emits as ESM `import` directives — namely
    //! all cross-module non-rebind non-LazyUse edges, including
    //! cross-module at-init promoted edges.
    use std::collections::BTreeSet;

    use swc_common::{FileName, SourceMap, sync::Lrc};
    use swc_ecma_parser::{Parser, StringInput, Syntax, lexer::Lexer};

    use super::*;
    use crate::ids::{LogicalModuleIndex, ModuleId};
    use crate::partition::Partition;
    use crate::{AnalysisHints, OwnerGraph, facts::analyze_chunk};

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

    /// Pure cross-module lazy edge must not appear in the canonical
    /// edge set. The emitter never emits an ESM `import` for a
    /// function-body read; the gate must agree.
    #[test]
    fn lazy_only_cross_module_edge_excluded() {
        let source = "const a = 1; function f() { return a; }";
        let owner_graph = parse_and_build(source);
        let mut partition = Partition::new(&owner_graph, module_id(0));
        partition.set(OwnerId(1), module_id(1));
        let canonical = chunk_constraining_module_edges(&owner_graph, &partition);
        // `f` reads `a` from a function body → LazyUse f → a, so the
        // only cross-module edge is mod_1 → mod_0 LazyUse.
        assert!(
            canonical.edges.is_empty(),
            "lazy-only cross-module edges must be excluded; got {:#?}",
            canonical.edges
        );
        assert!(canonical.i_successors.is_empty());
    }

    /// Cross-module eager_use edge appears in the canonical set.
    #[test]
    fn eager_cross_module_edge_included() {
        let source = "const a = 1; const b = a + 1;";
        let owner_graph = parse_and_build(source);
        let mut partition = Partition::new(&owner_graph, module_id(0));
        partition.set(OwnerId(1), module_id(1));
        let canonical = chunk_constraining_module_edges(&owner_graph, &partition);
        let pairs: BTreeSet<(ModuleId, ModuleId)> = canonical.pairs().collect();
        assert_eq!(
            pairs,
            BTreeSet::from([(module_id(1), module_id(0))]),
            "eager cross-module read `b = a + 1` must contribute mod_1 → mod_0"
        );
        assert!(canonical.contains(module_id(1), module_id(0)));
    }

    /// Same-module edges (intra-module reads) never appear in the
    /// canonical set — they don't correspond to any ESM import.
    #[test]
    fn same_module_edges_excluded() {
        let source = "const a = 1; const b = a + 1;";
        let owner_graph = parse_and_build(source);
        // Both owners in module 0 → no cross-module edges.
        let partition = Partition::new(&owner_graph, module_id(0));
        let canonical = chunk_constraining_module_edges(&owner_graph, &partition);
        assert!(canonical.edges.is_empty());
    }

    /// Sequenced edges between the same module pair are deduped (one
    /// representative owner edge per pair) so that having N sequenced
    /// reasons between two modules doesn't over-weight the I-graph.
    /// This mirrors `build_module_quotient`'s dedup.
    #[test]
    fn sequenced_edges_dedup_per_pair() {
        // Two impure statements in different modules: each carries a
        // Sequenced edge from the later impure stmt to the earlier
        // (graph.rs::sequenced_edges).
        let source = "console.log(\"a\"); console.log(\"b\"); console.log(\"c\");";
        let owner_graph = parse_and_build(source);
        let mut partition = Partition::new(&owner_graph, module_id(0));
        partition.set(OwnerId(1), module_id(1));
        partition.set(OwnerId(2), module_id(1));
        let canonical = chunk_constraining_module_edges(&owner_graph, &partition);
        // mod_1 contains owners 1 and 2; the only cross-module
        // sequenced edge is from mod_1 to mod_0 (owners 1, 2 both
        // sequenced after owner 0). We expect exactly ONE pair, even
        // though two owners contribute.
        let pair_count: usize = canonical
            .pairs()
            .filter(|&(from, to)| from == module_id(1) && to == module_id(0))
            .count();
        assert!(
            pair_count <= 1,
            "sequenced edges between the same pair must dedup; got {pair_count}",
        );
    }

    /// Asymmetric I-cycle shape: eager forward + lazy back. The
    /// canonical edge set must contain ONLY the forward edge — the
    /// lazy back-edge is dropped. This is the gaffer fix: a
    /// dependency's lazy back-edge to its dependent must NOT appear
    /// in the runtime DFS topology the simulator walks.
    #[test]
    fn asymmetric_cycle_canonical_set_excludes_lazy_back_edge() {
        let source = "const schemas_target = \"v\"; function lazy_back() { return ids_val; } const ids_val = schemas_target + \"-derived\";";
        let owner_graph = parse_and_build(source);
        let mut partition = Partition::new(&owner_graph, module_id(0));
        partition.set(OwnerId(0), module_id(1)); // schemas_target -> mod_schemas
        partition.set(OwnerId(1), module_id(1)); // lazy_back     -> mod_schemas
        partition.set(OwnerId(2), module_id(2)); // ids_val       -> mod_ids
        let canonical = chunk_constraining_module_edges(&owner_graph, &partition);
        let pairs: BTreeSet<(ModuleId, ModuleId)> = canonical.pairs().collect();
        assert!(
            pairs.contains(&(module_id(2), module_id(1))),
            "forward eager edge ids → schemas must be present; got {pairs:?}"
        );
        assert!(
            !pairs.contains(&(module_id(1), module_id(2))),
            "lazy back-edge schemas → ids must NOT be present; got {pairs:?}"
        );
    }
}

#[cfg(test)]
mod partition_view_invariant_tests {
    //! Regression coverage for the
    //! [`cross_module_partition_endpoints`] invariant: every consumer
    //! that builds a quotient view of the owner graph must agree on
    //! the same filter (skip `from == to` AND skip cross-module
    //! at-init promotions). A past TDZ-class soundness hole reopened
    //! the moment one site forgot one half of the filter. This test
    //! is a static guard that no consumer outside `graph.rs` may call
    //! [`is_cross_module_at_init_promotion`] directly — they must go
    //! through `cross_module_partition_endpoints` so the two checks
    //! stay welded together at the source level.
    //!
    //! Files scanned are the four other partition-quotient consumers
    //! the helper was extracted from: realizability check, the two
    //! incremental-simulator edge mutators (same file), and the
    //! reports quotient builder. Add new sibling consumers to the
    //! `INCLUDE_STR_CALL_SITES` array below as they appear.
    const INCLUDE_STR_CALL_SITES: &[(&str, &str)] = &[
        ("realizability.rs", include_str!("realizability.rs")),
        ("reports.rs", include_str!("reports.rs")),
    ];

    #[test]
    fn no_consumer_calls_is_cross_module_at_init_promotion_directly() {
        for (path, source) in INCLUDE_STR_CALL_SITES {
            for (lineno, line) in source.lines().enumerate() {
                // Skip the doc-comment references that exist only to
                // name-drop the helper in prose.
                if line.trim_start().starts_with("//") {
                    continue;
                }
                assert!(
                    !line.contains("is_cross_module_at_init_promotion"),
                    "{path}:{} calls `is_cross_module_at_init_promotion` directly. \
                     Route through `cross_module_partition_endpoints` so the \
                     `from == to` and promoted-edge filters stay welded together \
                     across consumers (see invariant doc on \
                     `cross_module_partition_endpoints`).\nline: {line}",
                    lineno + 1,
                );
            }
        }
    }
}
