//! Quotient-graph kernel for the peel proposer.
//!
//! `QuotientGraph` represents the current equivalence relation `~` over
//! owners, plus the cross-class edge structure derived from the
//! constraining-init-order owner edges. The kernel exposes one mutation
//! (`contract`) and two non-mutating queries
//! (`merge_preserves_invariants`, `would_be_cycles_after_contract`).
//!
//! Splits are forbidden. There is no public API on `QuotientGraph` that
//! refines the equivalence relation. The seeding protocol applies
//! forced contractions one at a time, gating each on
//! `merge_preserves_invariants` and recording a
//! `SeedContractionRejected` diagnostic if the contraction would have
//! created cycles. See
//! `plans/peel_proposer_contraction_model.md` (commit 1) for the
//! mental model.
//!
//! Commit 2 of the plan adds:
//! - `greedy_merge_to_convergence` — the greedy contraction loop
//!   with deterministic `pick_best` tiebreaks.
//! - Incremental cycle-set cache. The cycle set is computed once in
//!   `from_report*` and maintained across `contract` calls without
//!   rebuilding from scratch. Merges only ever shrink the cycle set
//!   (proof in the plan's "Why merges don't create cycles" section),
//!   so the cache update is cheap: walk cycles touching the merged
//!   endpoints, project class labels, drop cycles that collapse to
//!   a single class.
//! - `is_pre_existing_module` per-class metadata. Required by the
//!   commit-2 greedy mergeability restriction ("extension of
//!   existing module by orphaned residual class").
//!
//! ## Why the kernel reimplements the gate over the report
//!
//! `analysis::check_realizability` operates on `OwnerGraph + Partition`
//! (the debundler's IR), but the peel proposer consumes
//! `OwnerGraphReport` (a JSON wire format that drops `Id` atoms and
//! `EdgeReason` payloads). Materializing a synthetic IR from the JSON
//! would either fake `Id` atoms (brittle) or require a large adapter
//! crate (out of scope for commit 1). Instead we recompute the same
//! invariant — multi-class SCC in the constraining-edge quotient — on
//! the JSON-derived adjacency. The semantics are identical for the
//! shapes seed contractions can reach.

use std::collections::{BTreeMap, BTreeSet, HashMap};

use analysis::{DepKind, OwnerGraphReport, RESIDUAL_ENTRY_MODULE_ID};
use petgraph::algo::tarjan_scc;
use petgraph::graphmap::DiGraphMap;
use serde::Serialize;

/// Owner index into the `OwnerGraphReport.nodes` vector. Stable for
/// the lifetime of one quotient graph.
#[derive(Debug, Clone, Copy, Eq, PartialEq, Ord, PartialOrd, Hash, Serialize)]
pub struct OwnerIdx(pub usize);

/// Class identifier in the current quotient. Class IDs are assigned
/// densely starting at 0; the owner with the lowest `OwnerIdx` in a
/// class is canonical (used for tiebreaking and as the class
/// representative in diagnostics).
#[derive(Debug, Clone, Copy, Eq, PartialEq, Ord, PartialOrd, Hash, Serialize)]
pub struct ClassId(pub usize);

/// One unrealizable multi-class SCC in the constraining-edge quotient.
/// Used by both `cycle_set()` and `would_be_cycles_after_contract` as
/// the evidence shape.
#[derive(Debug, Clone, Eq, PartialEq, Ord, PartialOrd, Serialize)]
pub struct CycleClassSet {
    /// Sorted, deduplicated class IDs participating in the cycle.
    pub classes: Vec<ClassId>,
    /// Sorted, deduplicated owner IDs (as strings, from the report)
    /// participating in any class in `classes`. Stable for
    /// diagnostic byte-equality.
    pub owner_ids: Vec<String>,
}

/// Aggregated cycle evidence: zero or more multi-class SCCs.
#[derive(Debug, Clone, Default, Eq, PartialEq, Serialize)]
pub struct CycleEvidence {
    pub cycles: Vec<CycleClassSet>,
}

impl CycleEvidence {
    pub fn is_empty(&self) -> bool {
        self.cycles.is_empty()
    }
}

/// Reason a `contract` call could not proceed. Surfaces the cycle
/// evidence so the caller can attribute the rejection to a specific
/// owner pair.
#[derive(Debug, Clone, Eq, PartialEq, Serialize)]
pub enum ContractRejected {
    WouldCreateCycle { cycle: CycleEvidence },
    ExceedsCap { combined_lines: usize, cap: usize },
    ResidualSticky,
    SameClass,
}

/// Per-contraction rejection diagnostic emitted by `build_seed_quotient`.
/// Stable JSON shape — `reports/tree/<chunk>/seed_rejections.json`
/// consumers depend on field order.
#[derive(Debug, Clone, Eq, PartialEq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum SeedContractionRejected {
    AtomicUnit {
        unit_id: String,
        owner_ids: Vec<String>,
        rejected_pair: (String, String),
        cycle: CycleEvidence,
    },
    SpecModule {
        module_id: String,
        owner_ids: Vec<String>,
        rejected_pair: (String, String),
        cycle: CycleEvidence,
    },
    /// Pass-3 (atomic-DAG reachability closure) contraction rejected.
    /// Pre-commit-4 behavior was: silently form the closure into a
    /// "cell" even when cyclic; downstream realizability gate would
    /// then report the cycle as a generic SCC. Post-commit-4: the
    /// kernel refuses the merge at seeding time and emits this
    /// diagnostic naming the source/target atomic-DAG edge whose
    /// contraction would have created the cycle. See
    /// `plans/peel_proposer_contraction_model.md`, commit 4.
    AtomicReachability {
        /// The atomic-DAG edge id whose contraction was refused.
        edge_id: String,
        source_unit_id: String,
        target_unit_id: String,
        /// `(source_owner_id, target_owner_id)` — the
        /// representative owners (lowest `OwnerIdx` in each unit at
        /// rejection time) whose class-level contraction tripped
        /// the gate.
        rejected_pair: (String, String),
        /// Cycle evidence when the rejection is cycle-driven. Empty
        /// for non-cycle rejections (cap, residual stickiness).
        cycle: CycleEvidence,
    },
}

/// One spec-module declaration the seeding protocol consumes. The
/// `owner_ids` list is the set of owners the module's `members:`
/// resolves to; the seed pre-contracts them all into one class.
#[derive(Debug, Clone)]
pub struct SpecModuleGroup {
    pub module_id: String,
    pub owner_ids: Vec<String>,
}

/// One input group for `QuotientGraph::from_report_with_partition_extended`.
/// Used by the renderer to materialize cells-derived partitions with
/// per-class metadata the commit-2 greedy needs.
#[derive(Debug, Clone)]
pub struct PartitionGroup {
    pub owner_idxs: Vec<OwnerIdx>,
    /// `true` if this group corresponds to a pre-existing active
    /// spec module (the greedy may extend it by absorbing orphan
    /// residual classes). `false` if this group is a residual
    /// atomic-DAG closure or an ad-hoc grouping.
    pub is_pre_existing_module: bool,
    /// Optional human-readable label (e.g., module id). Carried by
    /// the kernel for diagnostic purposes only.
    pub label: Option<String>,
}

/// One step of the greedy merge loop. Returned by
/// `greedy_step` so callers (incremental-invariant property tests,
/// dry-run diagnostics) can step through one contraction at a time.
#[derive(Debug, Clone, Copy, Eq, PartialEq)]
pub struct GreedyStep {
    /// The two classes the step picked, in canonical (lower, higher)
    /// order. After the contract, only `surviving` remains.
    pub picked: (ClassId, ClassId),
    /// The class id that survived the contraction (always equals
    /// `picked.0.min(picked.1)`).
    pub surviving: ClassId,
}

/// Internal: one class's metadata. Class membership is tracked by
/// `owner_to_class`; this struct caches per-class aggregates that
/// `merge_preserves_invariants` consults.
#[derive(Debug, Clone)]
struct ClassData {
    /// Owners in this class, by `OwnerIdx`. Sorted.
    members: BTreeSet<OwnerIdx>,
    /// Summed source-line count across members.
    lines: usize,
    /// `true` if this class contains the residual catch-all.
    is_residual: bool,
    /// `true` if this class was seeded by a `PartitionGroup` with
    /// `is_pre_existing_module = true`. Sticky across merges (a
    /// merge of two pre-existing-module classes — only allowed in
    /// commit 3 — produces a class that is itself pre-existing).
    /// Default `false` for singletons constructed from
    /// `from_report` or for residual atomic-DAG-closure classes
    /// seeded by `from_report_with_partition`.
    is_pre_existing_module: bool,
}

/// The quotient graph: owners partitioned into classes, with the
/// cross-class constraining edges materialized on demand.
#[derive(Debug, Clone)]
pub struct QuotientGraph {
    /// Stable owner IDs in `OwnerIdx.0` order. Inherited from the
    /// source `OwnerGraphReport.nodes`.
    owner_ids: Vec<String>,
    /// Owner → current class. Dense, indexed by `OwnerIdx.0`.
    owner_to_class: Vec<ClassId>,
    /// Class metadata. Indexed by `ClassId.0`. Entries for emptied
    /// classes (post-contract) remain in place with empty `members`
    /// to keep IDs stable; queries skip them.
    classes: Vec<ClassData>,
    /// Constraining-edge owner adjacency: `(from_owner, to_owner)`
    /// pairs from `OwnerGraphReport.edges` whose
    /// `constrains_init_order` is true and whose endpoints both
    /// resolve to known owners. Source-of-truth for the cycle set.
    owner_constraining_edges: Vec<(OwnerIdx, OwnerIdx)>,
    /// **All** owner edges, with their weight (from `DepKind`).
    /// Used by the greedy's coupling metric. Self-loops and
    /// non-constraining edges are included; `class_cross_edges`
    /// filters out same-class pairs at query time.
    owner_weighted_edges: Vec<WeightedOwnerEdge>,
    /// Cap on per-class combined lines. Exceeding this is a rejected
    /// merge.
    cap_lines: usize,
    /// Cached cycle set, maintained incrementally across `contract`.
    /// Recomputed from scratch in `from_report*`, then updated in
    /// place. Invariants: classes monotonically decrease (a contracted
    /// class id is rewritten to its survivor); cycles that collapse
    /// to a single class are dropped.
    cached_cycles: Vec<CycleClassSet>,
    /// Class → indices into `cached_cycles` whose `classes` list
    /// contains this class. Permits O(min(|cycles touching c1|,
    /// |cycles touching c2|)) `merge_preserves_invariants` and
    /// `contract`-time cycle maintenance.
    class_to_cycle_indices: BTreeMap<ClassId, Vec<usize>>,
    /// Class-level constraining-edge adjacency (out-edges). Self-loops
    /// are dropped; multi-edges between the same class pair are
    /// counted in the multiplicity map below.
    class_out: BTreeMap<ClassId, BTreeSet<ClassId>>,
    /// Symmetric (in-edges).
    class_in: BTreeMap<ClassId, BTreeSet<ClassId>>,
    /// Multiplicity of each (from_class, to_class) constraining-edge
    /// pair. Drives incremental updates: when the multiplicity drops
    /// to 0, the adjacency entry is removed.
    class_edge_multiplicity: BTreeMap<(ClassId, ClassId), usize>,
    /// Coupling weight per (from_class, to_class) cross-class pair.
    /// Sum of `edge_weight` for every owner edge between the two
    /// classes (constraining or not). Used by the greedy's pick_best
    /// coupling metric. Updated on contract by relabeling endpoints.
    class_edge_weight: BTreeMap<(ClassId, ClassId), u64>,
    /// Number of *outgoing* owner edges from each class (any kind,
    /// constraining or not). Used as the denominator of the coupling
    /// metric: `min(|out(c1)|, |out(c2)|)`.
    class_out_edge_count: BTreeMap<ClassId, usize>,
}

/// One owner-edge with its `DepKind`-derived weight. Stored on the
/// kernel so the greedy can evaluate the coupling metric without
/// re-parsing the input report.
#[derive(Debug, Clone, Copy)]
struct WeightedOwnerEdge {
    from: OwnerIdx,
    to: OwnerIdx,
    weight: u32,
}

fn edge_weight(kind: DepKind) -> u32 {
    match kind {
        DepKind::EagerUse | DepKind::EagerRebind => 4,
        DepKind::Sequenced => 2,
        DepKind::LazyUse | DepKind::LazyRebind => 1,
        DepKind::LocalEffect => 2,
    }
}

impl QuotientGraph {
    /// Build a fresh quotient over `report.nodes`, each owner in its
    /// own singleton class. `cap_lines` is the size cap consulted by
    /// `merge_preserves_invariants`.
    pub fn from_report(report: &OwnerGraphReport, cap_lines: usize) -> Self {
        let owner_ids: Vec<String> = report.nodes.iter().map(|n| n.id.clone()).collect();
        let owner_index: HashMap<&str, OwnerIdx> = owner_ids
            .iter()
            .enumerate()
            .map(|(i, id)| (id.as_str(), OwnerIdx(i)))
            .collect();

        let mut classes = Vec::<ClassData>::with_capacity(owner_ids.len());
        let mut owner_to_class = Vec::<ClassId>::with_capacity(owner_ids.len());
        for (i, node) in report.nodes.iter().enumerate() {
            let mut members = BTreeSet::new();
            members.insert(OwnerIdx(i));
            // `is_residual` marks the literal residual_entry
            // catch-all class only, not every owner currently
            // destined for residual_entry. The catch-all is
            // identified by its module id; the commit-2 greedy
            // refuses to absorb any orphan INTO it, but freely
            // merges residual-orphan singletons among themselves
            // or into pre-existing active module classes.
            classes.push(ClassData {
                members,
                lines: owner_line_count_from_report(node),
                is_residual: node.destination.id == RESIDUAL_ENTRY_MODULE_ID,
                is_pre_existing_module: false,
            });
            owner_to_class.push(ClassId(i));
        }

        let mut owner_constraining_edges: Vec<(OwnerIdx, OwnerIdx)> = Vec::new();
        let mut owner_weighted_edges: Vec<WeightedOwnerEdge> =
            Vec::with_capacity(report.edges.len());
        for edge in &report.edges {
            let (Some(&s), Some(&t)) = (
                owner_index.get(edge.source.as_str()),
                owner_index.get(edge.target.as_str()),
            ) else {
                continue;
            };
            owner_weighted_edges.push(WeightedOwnerEdge {
                from: s,
                to: t,
                weight: edge_weight(edge.edge_kind),
            });
            if !edge.constrains_init_order || s == t {
                continue;
            }
            owner_constraining_edges.push((s, t));
        }

        let mut q = QuotientGraph {
            owner_ids,
            owner_to_class,
            classes,
            owner_constraining_edges,
            owner_weighted_edges,
            cap_lines,
            cached_cycles: Vec::new(),
            class_to_cycle_indices: BTreeMap::new(),
            class_out: BTreeMap::new(),
            class_in: BTreeMap::new(),
            class_edge_multiplicity: BTreeMap::new(),
            class_edge_weight: BTreeMap::new(),
            class_out_edge_count: BTreeMap::new(),
        };
        q.rebuild_class_adjacency();
        q.rebuild_cycle_cache();
        q
    }

    /// Build a quotient over `report.nodes` and immediately contract
    /// each owner group into a single class. Unlike `contract`, this
    /// bypasses the realizability gate — the partition is taken as
    /// authoritative. Returns the quotient plus a list of class IDs,
    /// one per input group, in the same order as `groups`.
    ///
    /// Used by `peel::factorize::emit_proposals` to render off a
    /// cells-derived quotient (Path B in
    /// `plans/peel_proposer_contraction_model.md`'s commit 1b): the
    /// cell-discovery pass produces equivalence classes that are not
    /// derivable from the seeding protocol's gated contractions, so
    /// the kernel hosts them as a partition rather than as a sequence
    /// of gated contractions.
    ///
    /// Groups containing owners already implicitly co-located with
    /// other groups (overlap) are not supported and will panic; the
    /// caller is expected to pre-coalesce overlapping groups, which
    /// `proposal_cells_from_atomic_graph` already does.
    pub fn from_report_with_partition(
        report: &OwnerGraphReport,
        cap_lines: usize,
        groups: &[Vec<OwnerIdx>],
    ) -> (Self, Vec<ClassId>) {
        let extended_groups: Vec<PartitionGroup> = groups
            .iter()
            .map(|owner_idxs| PartitionGroup {
                owner_idxs: owner_idxs.clone(),
                is_pre_existing_module: false,
                label: None,
            })
            .collect();
        Self::from_report_with_partition_extended(report, cap_lines, &extended_groups)
    }

    /// Like `from_report_with_partition`, but each group carries
    /// per-class metadata (`is_pre_existing_module`, optional
    /// `label`). The greedy's mergeability check consults
    /// `is_pre_existing_module` to restrict commit-2 merges to
    /// "extend existing module by orphaned residual class."
    pub fn from_report_with_partition_extended(
        report: &OwnerGraphReport,
        cap_lines: usize,
        groups: &[PartitionGroup],
    ) -> (Self, Vec<ClassId>) {
        let mut q = Self::from_report(report, cap_lines);
        let mut group_class_ids = Vec::with_capacity(groups.len());
        for group in groups {
            let mut winner: Option<ClassId> = None;
            for &owner in &group.owner_idxs {
                let c = q.class_of(owner);
                match winner {
                    None => winner = Some(c),
                    Some(w) if c == w => {}
                    Some(w) => {
                        let merged = q
                            .merge_classes_unchecked(w, c)
                            .expect("partition group owners are pre-coalesced");
                        winner = Some(merged);
                    }
                }
            }
            let survivor = winner.expect("partition group must be non-empty");
            if group.is_pre_existing_module {
                q.classes[survivor.0].is_pre_existing_module = true;
            }
            group_class_ids.push(survivor);
        }
        // Partition seeding bypasses the gate, so the cached
        // adjacency / cycle set can drift from the per-merge
        // incremental update. Rebuild from scratch so callers see
        // the correct initial state.
        q.rebuild_class_adjacency();
        q.rebuild_cycle_cache();
        (q, group_class_ids)
    }

    /// The class an owner currently belongs to.
    pub fn class_of(&self, o: OwnerIdx) -> ClassId {
        self.owner_to_class[o.0]
    }

    /// Look up the owner index for a stable owner-id string. Returns
    /// `None` for ids not present in the source report.
    pub fn owner_idx_of(&self, owner_id: &str) -> Option<OwnerIdx> {
        self.owner_ids
            .iter()
            .position(|id| id == owner_id)
            .map(OwnerIdx)
    }

    /// Stable owner id string for an `OwnerIdx`.
    pub fn owner_id(&self, o: OwnerIdx) -> &str {
        &self.owner_ids[o.0]
    }

    /// Members of a class in `OwnerIdx` order.
    pub fn class_members(&self, c: ClassId) -> impl Iterator<Item = OwnerIdx> + '_ {
        self.classes[c.0].members.iter().copied()
    }

    /// Total source-line count summed across a class's members.
    pub fn class_lines(&self, c: ClassId) -> usize {
        self.classes[c.0].lines
    }

    /// `true` if a class contains the residual catch-all owner.
    pub fn class_is_residual(&self, c: ClassId) -> bool {
        self.classes[c.0].is_residual
    }

    /// Iterator over all live (non-empty) class IDs.
    pub fn iter_classes(&self) -> impl Iterator<Item = ClassId> + '_ {
        self.classes
            .iter()
            .enumerate()
            .filter_map(|(i, c)| (!c.members.is_empty()).then_some(ClassId(i)))
    }

    /// Current unrealizable cycle evidence. Multi-class SCCs in the
    /// constraining-edge quotient. O(|cached_cycles|) — reads the
    /// incrementally-maintained cache, which is rebuilt only at
    /// construction time and updated in place on each `contract`.
    pub fn cycle_set(&self) -> CycleEvidence {
        CycleEvidence {
            cycles: self.cached_cycles.clone(),
        }
    }

    /// Cheap query: would contracting `c1` and `c2` preserve the
    /// kernel's invariants? Specifically:
    ///
    /// 1. `c1 != c2`.
    /// 2. Not both classes are residual; if one is residual, the
    ///    other must be too (residual is sticky — never absorb a
    ///    non-residual class into the residual catch-all).
    /// 3. `class_lines(c1) + class_lines(c2) <= cap_lines`.
    /// 4. Post-merge cycle set ⊆ current cycle set (always true for
    ///    a merge — see the plan's "Why merges don't create cycles"
    ///    — but checked defensively against future gate clauses).
    ///
    /// No state mutation.
    pub fn merge_preserves_invariants(&self, c1: ClassId, c2: ClassId) -> bool {
        self.check_merge(c1, c2).is_ok()
    }

    /// Diagnostic: what cycles would the merge create or surface?
    /// Returns `None` if the merge preserves invariants. Returns
    /// `Some(evidence)` if either:
    /// - a pre-existing unrealizable cycle includes both endpoints
    ///   (the merge doesn't dissolve it because the SCC has other
    ///   members), or
    /// - the hypothetical merged graph would have a new multi-class
    ///   SCC through the merged class.
    ///
    /// The check has two fast paths:
    /// 1. **Cycle cache lookup**: if any cached cycle contains both
    ///    `c1` and `c2` AND has > 2 classes, the cycle persists
    ///    post-merge (the merge only collapses c1 ↔ c2; the other
    ///    members still cycle through). O(min(|cycles touching c1|,
    ///    |cycles touching c2|)).
    /// 2. **Localized reachability**: for the not-cached-cycle case,
    ///    use the class adjacency to check if the merged class's
    ///    successors can reach it back, i.e. "is M reachable from any
    ///    out-neighbor of the merged class in the projected graph?"
    ///    A bounded DFS in the class quotient graph, typically over
    ///    a small neighborhood for the commit-2 orphan-into-module
    ///    shape.
    pub fn would_be_cycles_after_contract(
        &self,
        c1: ClassId,
        c2: ClassId,
    ) -> Option<CycleEvidence> {
        // Path 1: cached cycle through both endpoints with > 2
        // classes survives the merge.
        let (probe, other) = match (
            self.class_to_cycle_indices.get(&c1),
            self.class_to_cycle_indices.get(&c2),
        ) {
            (Some(a), Some(b)) => {
                if a.len() <= b.len() {
                    (a, c2)
                } else {
                    (b, c1)
                }
            }
            _ => (&Vec::new() as &Vec<usize>, c2),
        };
        let mut surfaced: Vec<CycleClassSet> = Vec::new();
        for &idx in probe {
            let cycle = &self.cached_cycles[idx];
            if cycle.classes.contains(&other) && cycle.classes.len() > 2 {
                surfaced.push(cycle.clone());
            }
        }
        if !surfaced.is_empty() {
            surfaced.sort();
            surfaced.dedup();
            return Some(CycleEvidence { cycles: surfaced });
        }

        // Path 2: localized reachability — does merging c1 and c2
        // create a new multi-class SCC through the merged class?
        // The merged class's class-level out-neighbors (other than
        // the merged class itself) must not reach c1 or c2 in the
        // post-merge graph.
        if self.merge_creates_new_cycle(c1, c2) {
            // Produce evidence by computing the new SCC explicitly.
            // Slow path, only taken when a new cycle was detected.
            let detailed = self.compute_cycles_with_overlay(Some((c1, c2)));
            // Filter to only cycles that include the merged class.
            let merged_class = if c1 < c2 { c1 } else { c2 };
            let new_cycles: Vec<CycleClassSet> = detailed
                .cycles
                .into_iter()
                .filter(|cycle| cycle.classes.contains(&merged_class))
                .collect();
            return Some(CycleEvidence { cycles: new_cycles });
        }
        None
    }

    /// Fast check: does merging c1 and c2 introduce a new multi-class
    /// SCC through the merged class? Walks the class-level adjacency
    /// in the projected (post-merge) graph from the merged class's
    /// out-neighbors; returns true if any of them can reach the
    /// merged class.
    fn merge_creates_new_cycle(&self, c1: ClassId, c2: ClassId) -> bool {
        if c1 == c2 {
            return false;
        }
        // Canonicalize so the merged class id is `target` (= min) and
        // the absorbed class id is `loser`. Mirrors
        // `merge_classes_unchecked`'s winner/loser choice so the
        // projection direction here matches the post-merge layout.
        let (target, loser) = if c1 < c2 { (c1, c2) } else { (c2, c1) };
        // Out-neighbors of the merged class = (out_of(c1) ∪ out_of(c2)) \ {c1, c2}.
        let mut frontier: Vec<ClassId> = Vec::new();
        let mut seen: BTreeSet<ClassId> = BTreeSet::new();
        for &(s, t) in &self.owner_constraining_edges {
            let cs = self.owner_to_class[s.0];
            let ct = self.owner_to_class[t.0];
            if (cs == target || cs == loser) && ct != target && ct != loser && seen.insert(ct) {
                frontier.push(ct);
            }
        }
        if frontier.is_empty() {
            return false;
        }
        // BFS in the class-projected constraining-edge adjacency.
        // We can reuse the owner edges, projecting at each step.
        // Build a class adjacency on demand (one pass). Project
        // `loser` → `target` so the merged class id is `target`.
        let mut adj: BTreeMap<ClassId, BTreeSet<ClassId>> = BTreeMap::new();
        for &(s, t) in &self.owner_constraining_edges {
            let cs_raw = self.owner_to_class[s.0];
            let ct_raw = self.owner_to_class[t.0];
            let cs = if cs_raw == loser { target } else { cs_raw };
            let ct = if ct_raw == loser { target } else { ct_raw };
            if cs == ct {
                continue;
            }
            adj.entry(cs).or_default().insert(ct);
        }
        let mut stack = frontier;
        while let Some(node) = stack.pop() {
            if node == target {
                return true;
            }
            if let Some(next) = adj.get(&node) {
                for &n in next {
                    if seen.insert(n) {
                        stack.push(n);
                    }
                }
            }
        }
        false
    }

    /// Apply a contraction. Returns `Err(ContractRejected)` if any
    /// invariant would be violated; the caller should have checked
    /// via `merge_preserves_invariants` first. Belt-and-braces.
    ///
    /// On success, `c1` (the lower of the two class IDs) absorbs
    /// `c2`; `c2`'s members are reassigned, its slot is left empty
    /// in `classes`. Subsequent calls should use the surviving class
    /// id (`c1.min(c2)`).
    pub fn contract(&mut self, c1: ClassId, c2: ClassId) -> Result<ClassId, ContractRejected> {
        self.check_merge(c1, c2)?;
        self.merge_classes_unchecked(c1, c2)
    }

    /// Merge two classes without consulting the realizability /
    /// residual / cap gates. The lower of the two `ClassId`s
    /// survives; the higher is emptied. Returns the survivor.
    ///
    /// `SameClass` is still rejected (caller error). All other gate
    /// clauses are bypassed — this method is the partition-driven
    /// entrypoint used by `from_report_with_partition`. External
    /// callers should prefer `contract`.
    fn merge_classes_unchecked(
        &mut self,
        c1: ClassId,
        c2: ClassId,
    ) -> Result<ClassId, ContractRejected> {
        if c1 == c2 {
            return Err(ContractRejected::SameClass);
        }
        let (winner, loser) = if c1 < c2 { (c1, c2) } else { (c2, c1) };
        // Move members from loser to winner.
        let loser_members = std::mem::take(&mut self.classes[loser.0].members);
        let loser_lines = self.classes[loser.0].lines;
        let loser_residual = self.classes[loser.0].is_residual;
        let loser_pre_existing = self.classes[loser.0].is_pre_existing_module;
        self.classes[loser.0].lines = 0;
        self.classes[loser.0].is_residual = false;
        self.classes[loser.0].is_pre_existing_module = false;
        for member in &loser_members {
            self.owner_to_class[member.0] = winner;
        }
        self.classes[winner.0].members.extend(loser_members);
        self.classes[winner.0].lines = self.classes[winner.0].lines.saturating_add(loser_lines);
        if loser_residual {
            self.classes[winner.0].is_residual = true;
        }
        if loser_pre_existing {
            self.classes[winner.0].is_pre_existing_module = true;
        }
        self.update_class_adjacency_after_merge(winner, loser);
        self.update_cycle_cache_after_merge(winner, loser);
        Ok(winner)
    }

    fn check_merge(&self, c1: ClassId, c2: ClassId) -> Result<(), ContractRejected> {
        if c1 == c2 {
            return Err(ContractRejected::SameClass);
        }
        let cls1 = &self.classes[c1.0];
        let cls2 = &self.classes[c2.0];
        if cls1.members.is_empty() || cls2.members.is_empty() {
            return Err(ContractRejected::SameClass);
        }
        // Residual stickiness: if exactly one is residual, reject.
        // (Two residual classes never coexist with the canonical
        // construction since only one owner is residual today; the
        // check is defensive.)
        if cls1.is_residual != cls2.is_residual {
            return Err(ContractRejected::ResidualSticky);
        }
        let combined = cls1.lines.saturating_add(cls2.lines);
        if combined > self.cap_lines {
            return Err(ContractRejected::ExceedsCap {
                combined_lines: combined,
                cap: self.cap_lines,
            });
        }
        if let Some(cycle) = self.would_be_cycles_after_contract(c1, c2) {
            return Err(ContractRejected::WouldCreateCycle { cycle });
        }
        Ok(())
    }

    /// Compute the constraining-edge cycle set, optionally with one
    /// hypothetical contraction overlaid on the current quotient.
    ///
    /// Owner-edge endpoints are projected to (possibly-overlaid)
    /// class IDs; same-class edges are dropped; the resulting
    /// directed multigraph is run through Tarjan. Multi-class SCCs
    /// are the cycles. Within each SCC, both class IDs and owner
    /// IDs are sorted for stable diagnostic byte-equality.
    fn compute_cycles_with_overlay(&self, overlay: Option<(ClassId, ClassId)>) -> CycleEvidence {
        // Project a class through the overlay.
        let project = |c: ClassId| -> ClassId {
            if let Some((a, b)) = overlay {
                if c == a || c == b {
                    return if a < b { a } else { b };
                }
            }
            c
        };

        let mut graph: DiGraphMap<ClassId, ()> = DiGraphMap::new();
        for &(s, t) in &self.owner_constraining_edges {
            let cs = project(self.owner_to_class[s.0]);
            let ct = project(self.owner_to_class[t.0]);
            if cs == ct {
                continue;
            }
            graph.add_edge(cs, ct, ());
        }

        let mut cycles = Vec::<CycleClassSet>::new();
        for scc in tarjan_scc(&graph) {
            if scc.len() < 2 {
                continue;
            }
            let class_set: BTreeSet<ClassId> = scc.into_iter().collect();
            let mut classes: Vec<ClassId> = class_set.iter().copied().collect();
            classes.sort();
            let mut owner_ids = BTreeSet::<String>::new();
            for (i, _) in self.owner_to_class.iter().enumerate() {
                let projected = project(self.owner_to_class[i]);
                if class_set.contains(&projected) {
                    owner_ids.insert(self.owner_ids[i].clone());
                }
            }
            cycles.push(CycleClassSet {
                classes,
                owner_ids: owner_ids.into_iter().collect(),
            });
        }
        cycles.sort();
        CycleEvidence { cycles }
    }

    // ---------------------------------------------------------------
    // Incremental class adjacency + cycle-cache maintenance.
    // ---------------------------------------------------------------

    /// Rebuild class-level constraining-edge adjacency from scratch.
    /// O(|owner edges|). Called in `from_report*` and as a fallback;
    /// merges should use `update_class_adjacency_after_merge`.
    fn rebuild_class_adjacency(&mut self) {
        self.class_out.clear();
        self.class_in.clear();
        self.class_edge_multiplicity.clear();
        self.class_edge_weight.clear();
        self.class_out_edge_count.clear();
        for &(s, t) in &self.owner_constraining_edges {
            let cs = self.owner_to_class[s.0];
            let ct = self.owner_to_class[t.0];
            if cs == ct {
                continue;
            }
            self.class_out.entry(cs).or_default().insert(ct);
            self.class_in.entry(ct).or_default().insert(cs);
            *self.class_edge_multiplicity.entry((cs, ct)).or_insert(0) += 1;
        }
        for &edge in &self.owner_weighted_edges {
            let cs = self.owner_to_class[edge.from.0];
            let ct = self.owner_to_class[edge.to.0];
            if cs == ct {
                continue;
            }
            *self.class_edge_weight.entry((cs, ct)).or_insert(0) += edge.weight as u64;
            *self.class_out_edge_count.entry(cs).or_insert(0) += 1;
        }
    }

    /// Rebuild the cycle-set cache from scratch via Tarjan over the
    /// projected constraining-edge graph. O(|V| + |E|).
    fn rebuild_cycle_cache(&mut self) {
        let evidence = self.compute_cycles_with_overlay(None);
        self.cached_cycles = evidence.cycles;
        self.rebuild_class_to_cycle_indices();
    }

    fn rebuild_class_to_cycle_indices(&mut self) {
        self.class_to_cycle_indices.clear();
        for (idx, cycle) in self.cached_cycles.iter().enumerate() {
            for &class in &cycle.classes {
                self.class_to_cycle_indices
                    .entry(class)
                    .or_default()
                    .push(idx);
            }
        }
    }

    /// Update class adjacency after `loser` is absorbed into `winner`.
    /// Relabels all loser-incident entries to winner, dropping self-
    /// loops. O(|out_edges(loser)| + |in_edges(loser)|) — typically
    /// small for the commit-2 orphan shape.
    fn update_class_adjacency_after_merge(&mut self, winner: ClassId, loser: ClassId) {
        // Out-edges from loser are re-pointed to winner.
        let loser_out = self.class_out.remove(&loser).unwrap_or_default();
        for to in loser_out {
            // Remove loser -> to from `class_in[to]`.
            if let Some(in_set) = self.class_in.get_mut(&to) {
                in_set.remove(&loser);
            }
            let mult = self
                .class_edge_multiplicity
                .remove(&(loser, to))
                .unwrap_or(0);
            if to == winner {
                // Self-loop after merge — drop entirely.
                continue;
            }
            if mult > 0 {
                *self
                    .class_edge_multiplicity
                    .entry((winner, to))
                    .or_insert(0) += mult;
                self.class_out.entry(winner).or_default().insert(to);
                self.class_in.entry(to).or_default().insert(winner);
            }
        }
        // In-edges to loser are re-pointed to winner.
        let loser_in = self.class_in.remove(&loser).unwrap_or_default();
        for from in loser_in {
            if let Some(out_set) = self.class_out.get_mut(&from) {
                out_set.remove(&loser);
            }
            let mult = self
                .class_edge_multiplicity
                .remove(&(from, loser))
                .unwrap_or(0);
            if from == winner {
                continue;
            }
            if mult > 0 {
                *self
                    .class_edge_multiplicity
                    .entry((from, winner))
                    .or_insert(0) += mult;
                self.class_in.entry(winner).or_default().insert(from);
                self.class_out.entry(from).or_default().insert(winner);
            }
        }
        // Weight + out-edge count: walk owner edges to find affected
        // pairs. Cheaper than maintaining a per-owner incidence list:
        // the gaffer worst case has owners with bounded degree.
        // Rebuild the weight/count entries by re-walking
        // owner_weighted_edges incident to the merged class. Filter
        // to edges where either endpoint is now in `winner`.
        // (This is the only O(|E|) operation we accept per merge;
        // typical contracts are 100s of merges, so total O(|E| · |contracts|);
        // for gaffer scale that's ~5e7 ops, well under the budget.)
        //
        // The trade is simplicity: maintaining per-owner edge
        // indices to localize this to O(|incident edges|) would
        // require another vector. Skipping for now; revisit if the
        // benchmark exceeds budget.
        self.recompute_class_weight_for(winner);
    }

    /// Recompute coupling weight and out-edge count entries
    /// incident to `class` by re-walking weighted owner edges.
    /// Used after a merge to refresh weight/count for the merged
    /// class. Coupled with the adjacency relabeling done in
    /// `update_class_adjacency_after_merge`.
    fn recompute_class_weight_for(&mut self, class: ClassId) {
        // Clear weight + count entries incident to `class`.
        let to_drop: Vec<(ClassId, ClassId)> = self
            .class_edge_weight
            .keys()
            .filter(|(a, b)| *a == class || *b == class)
            .copied()
            .collect();
        for key in to_drop {
            self.class_edge_weight.remove(&key);
        }
        self.class_out_edge_count.remove(&class);
        // Re-walk; sum weights and count outs for any edges incident
        // to `class`.
        for &edge in &self.owner_weighted_edges {
            let cs = self.owner_to_class[edge.from.0];
            let ct = self.owner_to_class[edge.to.0];
            if cs == ct {
                continue;
            }
            if cs == class || ct == class {
                *self.class_edge_weight.entry((cs, ct)).or_insert(0) += edge.weight as u64;
            }
            if cs == class {
                *self.class_out_edge_count.entry(class).or_insert(0) += 1;
            }
        }
    }

    /// Update cached cycle set after `loser` is absorbed into `winner`.
    /// Walks only cycles touching either endpoint, relabels, and drops
    /// cycles that collapse to a single class.
    fn update_cycle_cache_after_merge(&mut self, winner: ClassId, loser: ClassId) {
        let mut affected_indices: BTreeSet<usize> = BTreeSet::new();
        if let Some(idxs) = self.class_to_cycle_indices.get(&loser) {
            affected_indices.extend(idxs.iter().copied());
        }
        if let Some(idxs) = self.class_to_cycle_indices.get(&winner) {
            affected_indices.extend(idxs.iter().copied());
        }
        if affected_indices.is_empty() {
            return;
        }
        let mut drop_indices: BTreeSet<usize> = BTreeSet::new();
        for idx in &affected_indices {
            let cycle = &mut self.cached_cycles[*idx];
            let mut new_classes: BTreeSet<ClassId> = BTreeSet::new();
            for &c in &cycle.classes {
                if c == loser {
                    new_classes.insert(winner);
                } else {
                    new_classes.insert(c);
                }
            }
            cycle.classes = new_classes.into_iter().collect();
            cycle.classes.sort();
            if cycle.classes.len() < 2 {
                drop_indices.insert(*idx);
            }
        }
        if !drop_indices.is_empty() {
            let mut new_cycles: Vec<CycleClassSet> = Vec::new();
            for (idx, cycle) in self.cached_cycles.iter().enumerate() {
                if !drop_indices.contains(&idx) {
                    new_cycles.push(cycle.clone());
                }
            }
            self.cached_cycles = new_cycles;
        }
        self.rebuild_class_to_cycle_indices();
    }

    /// `true` if a class is **pre-existing module-anchored** —
    /// i.e., it was constructed from a `PartitionGroup` with
    /// `is_pre_existing_module = true`, or marked by the seeding
    /// protocol's spec-module pass. The greedy uses this to
    /// restrict commit-2 merges to "extend module by orphan" and
    /// commit-3 merges to module↔module fusions.
    pub fn class_is_pre_existing_module(&self, c: ClassId) -> bool {
        self.classes[c.0].is_pre_existing_module
    }

    /// Mark a class as pre-existing-module-anchored. Called by the
    /// seeding protocol's spec-module pass; sticky across merges
    /// (any subsequent contraction propagates the bit).
    pub fn set_class_pre_existing_module(&mut self, c: ClassId) {
        self.classes[c.0].is_pre_existing_module = true;
    }

    /// Number of owner edges between `a` and `b` (in either
    /// direction), as constraining-edge multiplicities. Used by the
    /// coupling metric.
    fn cross_edge_count(&self, a: ClassId, b: ClassId) -> u64 {
        let ab = self
            .class_edge_multiplicity
            .get(&(a, b))
            .copied()
            .unwrap_or(0);
        let ba = self
            .class_edge_multiplicity
            .get(&(b, a))
            .copied()
            .unwrap_or(0);
        (ab + ba) as u64
    }

    fn coupling_weight(&self, a: ClassId, b: ClassId) -> u64 {
        let ab = self.class_edge_weight.get(&(a, b)).copied().unwrap_or(0);
        let ba = self.class_edge_weight.get(&(b, a)).copied().unwrap_or(0);
        ab + ba
    }

    fn class_out_count(&self, c: ClassId) -> u64 {
        self.class_out_edge_count.get(&c).copied().unwrap_or(0) as u64
    }

    /// All neighboring classes of `c` (out + in directions). Used by
    /// the greedy to enumerate candidate merge partners restricted to
    /// classes connected by a cross-edge.
    fn class_neighbors(&self, c: ClassId) -> BTreeSet<ClassId> {
        let mut out: BTreeSet<ClassId> = BTreeSet::new();
        if let Some(s) = self.class_out.get(&c) {
            out.extend(s.iter().copied());
        }
        if let Some(s) = self.class_in.get(&c) {
            out.extend(s.iter().copied());
        }
        out
    }
}

// ---------------------------------------------------------------------
// Greedy merge to convergence (commit 2).
// ---------------------------------------------------------------------

/// Commit-3 mergeability gate. Allows two shapes:
///   1. Two pre-existing-module classes (merge modules A and B).
///      May happen with or without first absorbing residual orphans
///      into either side via successive shape-(2) merges.
///   2. One pre-existing-module class + one orphan residual class
///      (extend module A with an orphan); requires the orphan's
///      cross-edges to pre-existing modules to target exactly one
///      module — the merge partner. The "unambiguous extension"
///      check matches today's
///      `promote_anonymous_only_cell_to_extension` post-pass.
///
/// Orphan↔orphan merges are NOT permitted by this gate: today's
/// cell-discovery pass already closes residual atomic-DAG
/// reachability into single classes, so any orphan↔orphan grouping
/// that should happen is already represented as a single class
/// pre-greedy. Allowing orphan↔orphan here would let greedy fuse
/// unrelated residuals based purely on cross-edge presence, which
/// is over-aggressive on real inputs.
///
/// Common preconditions:
/// - Distinct classes.
/// - Neither is the residual catchall.
/// - At least one cross-edge connects the two.
/// - Combined lines under the cap (`merge_preserves_invariants`).
/// - Cycle gate holds (`merge_preserves_invariants`).
pub fn mergeable_commit2(q: &QuotientGraph, c1: ClassId, c2: ClassId) -> bool {
    if c1 == c2 {
        return false;
    }
    // Residual is sticky.
    if q.class_is_residual(c1) || q.class_is_residual(c2) {
        return false;
    }
    // Connected by at least one cross-edge.
    if q.cross_edge_count(c1, c2) == 0 {
        return false;
    }
    let pre1 = q.class_is_pre_existing_module(c1);
    let pre2 = q.class_is_pre_existing_module(c2);
    // At least one operand must be a pre-existing-module class.
    if !pre1 && !pre2 {
        return false;
    }
    // Shape (2): orphan + module → require unambiguous extension
    // target. If the orphan touches multiple modules via cross-edges,
    // the spec author must disambiguate; the greedy refuses.
    if pre1 != pre2 {
        let orphan = if pre1 { c2 } else { c1 };
        let mut module_neighbors: usize = 0;
        for n in q.class_neighbors(orphan) {
            if n == orphan {
                continue;
            }
            if q.class_is_pre_existing_module(n) && !q.class_is_residual(n) {
                module_neighbors += 1;
            }
        }
        if module_neighbors != 1 {
            return false;
        }
    }
    // Shape (1): pre↔pre — no additional precondition beyond the
    // common checks above.
    q.merge_preserves_invariants(c1, c2)
}

/// One pass of the greedy: enumerate candidate merges, pick the best,
/// apply. Returns `None` at convergence (no candidates).
pub fn greedy_step(q: &mut QuotientGraph) -> Option<GreedyStep> {
    let candidate = pick_best_candidate(q)?;
    let (a, b) = candidate.pair;
    let survivor = q.contract(a, b).ok()?;
    Some(GreedyStep {
        picked: (a.min(b), a.max(b)),
        surviving: survivor,
    })
}

/// Run `greedy_step` to convergence. Returns the sequence of
/// (c1, c2) contractions in the order they were applied. Each
/// returned pair uses canonical (lower, higher) ClassId order — the
/// surviving class is always the lower of the two.
pub fn greedy_merge_to_convergence(q: &mut QuotientGraph) -> Vec<(ClassId, ClassId)> {
    let mut steps: Vec<(ClassId, ClassId)> = Vec::new();
    while let Some(step) = greedy_step(q) {
        steps.push(step.picked);
    }
    steps
}

/// Ranked candidate for `pick_best`.
#[derive(Debug, Clone, Copy)]
struct RankedCandidate {
    /// Canonical pair (lower ClassId, higher ClassId).
    pair: (ClassId, ClassId),
    /// `pick_best` sort key (lower is better). Construction:
    /// - byte 0 (most significant): inverse of "cycle-set
    ///   reduction" — 0 if the merge strictly reduces the cycle set,
    ///   1 otherwise. Vestigial in normal flow (seed is realizable);
    ///   tiebreaker for unrealizable seeds.
    /// - bytes 1..9: inverse of coupling-numerator (so higher
    ///   coupling sorts earlier).
    /// - bytes 9..17: result-size (lines), smaller first.
    /// - bytes 17..25: canonical pair (a, b) lex.
    sort_key: [u8; 33],
}

fn pick_best_candidate(q: &QuotientGraph) -> Option<RankedCandidate> {
    // Enumerate candidate pairs: any (c, n) where c is a pre-existing
    // module class and n is a non-pre-existing non-residual neighbor.
    // The mergeable_commit2 gate is the source of truth; we use the
    // pre-existing-module side as the iteration anchor so we don't
    // re-evaluate symmetric pairs twice.
    let mut best: Option<RankedCandidate> = None;
    for c in q.iter_classes() {
        if !q.class_is_pre_existing_module(c) || q.class_is_residual(c) {
            continue;
        }
        let neighbors = q.class_neighbors(c);
        for n in neighbors {
            if n == c {
                continue;
            }
            if !mergeable_commit2(q, c, n) {
                continue;
            }
            let candidate = rank_candidate(q, c, n);
            best = match best {
                None => Some(candidate),
                Some(prev) if candidate.sort_key < prev.sort_key => Some(candidate),
                Some(prev) => Some(prev),
            };
        }
    }
    best
}

fn rank_candidate(q: &QuotientGraph, a: ClassId, b: ClassId) -> RankedCandidate {
    let (low, high) = if a < b { (a, b) } else { (b, a) };
    let mut key = [0u8; 33];

    // Cycle-reduction key: 0 if merge strictly reduces |cycle_set|, 1
    // otherwise. Currently the cycle set is always preserved or
    // shrunk; a true "reduction" happens when low and high are in a
    // 2-class cycle. We check via the cached cycle index.
    let mut reduces = false;
    if let (Some(la), Some(lb)) = (
        q.class_to_cycle_indices.get(&low),
        q.class_to_cycle_indices.get(&high),
    ) {
        // Intersection of cycle indices.
        let set_a: BTreeSet<usize> = la.iter().copied().collect();
        for idx in lb {
            if set_a.contains(idx) {
                reduces = true;
                break;
            }
        }
    }
    key[0] = if reduces { 0 } else { 1 };

    // Coupling: higher = better → invert.
    let coupling_num = q.coupling_weight(low, high);
    let coupling_denom = q.class_out_count(low).min(q.class_out_count(high)).max(1);
    // Encode as 16-bit fixed-point: scale by 1e6 to keep precision.
    let coupling_fixed: u64 =
        ((coupling_num as u128) * 1_000_000 / (coupling_denom as u128)) as u64;
    let inv_coupling: u64 = u64::MAX - coupling_fixed;
    key[1..9].copy_from_slice(&inv_coupling.to_be_bytes());

    // Result size (lines) — smaller better, natural order.
    let combined_lines = (q.class_lines(low) + q.class_lines(high)) as u64;
    key[9..17].copy_from_slice(&combined_lines.to_be_bytes());

    // Canonical pair lex.
    key[17..25].copy_from_slice(&(low.0 as u64).to_be_bytes());
    key[25..33].copy_from_slice(&(high.0 as u64).to_be_bytes());

    RankedCandidate {
        pair: (low, high),
        sort_key: key,
    }
}

/// Estimate of one owner's line count from the JSON report node.
/// Mirrors `peel::factorize::owner_line_count`.
fn owner_line_count_from_report(node: &analysis::OwnerGraphNodeReport) -> usize {
    node.source_location
        .as_ref()
        .map(|loc| {
            loc.end_line
                .saturating_sub(loc.start_line)
                .saturating_add(1)
        })
        .unwrap_or(0)
}

/// Apply the seeding protocol: atomic units first, then spec modules.
/// Each forced contraction is gated by
/// `merge_preserves_invariants`; rejected contractions push a
/// `SeedContractionRejected` diagnostic into the returned vec and the
/// kernel continues with the remaining contractions.
///
/// `canonical_order` matches the plan: atomic units by lowest
/// `OwnerIdx` member (then unit id for ties); spec modules by module
/// path lex (then module id for ties). Within a group, members merge
/// into the lowest-`OwnerIdx` pivot in `OwnerIdx` order.
pub fn build_seed_quotient(
    report: &OwnerGraphReport,
    atomic_units: &[analysis::AtomicUnitReport],
    spec_modules: &[SpecModuleGroup],
    cap_lines: usize,
) -> (QuotientGraph, Vec<SeedContractionRejected>) {
    let mut q = QuotientGraph::from_report(report, cap_lines);
    let mut rejected = Vec::<SeedContractionRejected>::new();

    // ---- Pass 1: atomic units. Canonical order: lowest OwnerIdx
    //      member, then unit id.
    let mut units: Vec<(&analysis::AtomicUnitReport, Option<OwnerIdx>)> = atomic_units
        .iter()
        .map(|unit| {
            (
                unit,
                lowest_owner_idx(&q, unit.owner_ids.iter().map(String::as_str)),
            )
        })
        .collect();
    units.sort_by(|(a, ai), (b, bi)| ai.cmp(bi).then_with(|| a.id.cmp(&b.id)));
    for (unit, _) in units {
        let owner_idxs = resolve_owner_idxs(&q, &unit.owner_ids);
        if owner_idxs.len() < 2 {
            continue;
        }
        let pivot = owner_idxs[0];
        for &member in &owner_idxs[1..] {
            let c_pivot = q.class_of(pivot);
            let c_member = q.class_of(member);
            if c_pivot == c_member {
                continue;
            }
            match q.contract(c_pivot, c_member) {
                Ok(_) => {}
                Err(ContractRejected::WouldCreateCycle { cycle }) => {
                    rejected.push(SeedContractionRejected::AtomicUnit {
                        unit_id: unit.id.clone(),
                        owner_ids: unit.owner_ids.clone(),
                        rejected_pair: (
                            q.owner_id(pivot).to_string(),
                            q.owner_id(member).to_string(),
                        ),
                        cycle,
                    });
                }
                Err(_) => {
                    rejected.push(SeedContractionRejected::AtomicUnit {
                        unit_id: unit.id.clone(),
                        owner_ids: unit.owner_ids.clone(),
                        rejected_pair: (
                            q.owner_id(pivot).to_string(),
                            q.owner_id(member).to_string(),
                        ),
                        cycle: CycleEvidence::default(),
                    });
                }
            }
        }
    }

    // ---- Pass 2: spec modules. Canonical order: module id lex.
    //      Every spec-module owner's surviving class is marked
    //      `is_pre_existing_module = true` so the downstream greedy
    //      can identify it as a viable absorption target (single-
    //      owner modules included).
    let mut modules: Vec<&SpecModuleGroup> = spec_modules.iter().collect();
    modules.sort_by(|a, b| a.module_id.cmp(&b.module_id));
    for module in modules {
        let owner_idxs = resolve_owner_idxs(&q, &module.owner_ids);
        if owner_idxs.is_empty() {
            continue;
        }
        let pivot = owner_idxs[0];
        for &member in owner_idxs.iter().skip(1) {
            let c_pivot = q.class_of(pivot);
            let c_member = q.class_of(member);
            if c_pivot == c_member {
                continue;
            }
            match q.contract(c_pivot, c_member) {
                Ok(_) => {}
                Err(ContractRejected::WouldCreateCycle { cycle }) => {
                    rejected.push(SeedContractionRejected::SpecModule {
                        module_id: module.module_id.clone(),
                        owner_ids: module.owner_ids.clone(),
                        rejected_pair: (
                            q.owner_id(pivot).to_string(),
                            q.owner_id(member).to_string(),
                        ),
                        cycle,
                    });
                }
                Err(_) => {
                    rejected.push(SeedContractionRejected::SpecModule {
                        module_id: module.module_id.clone(),
                        owner_ids: module.owner_ids.clone(),
                        rejected_pair: (
                            q.owner_id(pivot).to_string(),
                            q.owner_id(member).to_string(),
                        ),
                        cycle: CycleEvidence::default(),
                    });
                }
            }
        }
        // Mark every spec-module owner's surviving class as
        // pre-existing-module-anchored (sticky across later
        // pass-3 / greedy merges; needed for the greedy gate to
        // recognize the orphan-absorption shape).
        for &owner in &owner_idxs {
            let c = q.class_of(owner);
            q.set_class_pre_existing_module(c);
        }
    }

    // ---- Pass 3: atomic-DAG reachability. For each atomic-DAG
    //      edge `u → v` whose target unit has any residual member,
    //      contract `class(rep(u))` with `class(rep(v))` through
    //      the gated protocol. Subsumes today's
    //      `proposal_cells_from_atomic_graph` (atomic-DAG
    //      transitive closure + overlap coalesce) by reading the
    //      same edge set, but rejections fire at the per-edge
    //      granularity instead of silently forming cyclic cells.
    //
    //      Overlap coalesce: when two edges `u₁ → v` and `u₂ → v`
    //      both contract into the same target class, the second
    //      contraction sees the merged class (because the kernel's
    //      `class_of` is read after the first contract). The
    //      effect equivalent to today's `coalesce_overlapping_sets`
    //      falls out for free.
    //
    //      Iteration to fixed point: a single linear scan over
    //      atomic edges is enough for the success case (contractions
    //      commute when only merging). Cycle-driven rejections may
    //      become success after other merges (or remain rejections);
    //      we iterate until a pass produces zero successful
    //      contractions, then emit diagnostics from the final state.
    //      Termination: each successful pass strictly reduces the
    //      class count by ≥1; bounded by initial class count.
    //
    //      Diagnostic emission: dedupe by atomic-DAG edge id (each
    //      edge produces at most one diagnostic). Diagnostics are
    //      emitted in canonical (atomic-DAG edge id lex) order on
    //      the final, fixed-point quotient state.
    let atomic_edges_relevant: Vec<&analysis::AtomicUnitEdgeReport> = {
        let unit_has_residual: std::collections::HashMap<&str, bool> = atomic_units
            .iter()
            .map(|unit| {
                (
                    unit.id.as_str(),
                    unit.destinations.iter().any(|dest| dest.residual),
                )
            })
            .collect();
        let mut edges: Vec<&analysis::AtomicUnitEdgeReport> = report
            .atomic_graph
            .edges
            .iter()
            .filter(|e| e.constrains_init_order && e.source != e.target)
            .filter(|e| {
                unit_has_residual
                    .get(e.target.as_str())
                    .copied()
                    .unwrap_or(false)
            })
            .collect();
        edges.sort_by(|a, b| a.id.cmp(&b.id));
        edges
    };
    let unit_owner_idxs: std::collections::HashMap<&str, Vec<OwnerIdx>> = atomic_units
        .iter()
        .map(|unit| (unit.id.as_str(), resolve_owner_idxs(&q, &unit.owner_ids)))
        .collect();
    loop {
        let mut applied = 0usize;
        for edge in &atomic_edges_relevant {
            let Some(source_owners) = unit_owner_idxs.get(edge.source.as_str()) else {
                continue;
            };
            let Some(target_owners) = unit_owner_idxs.get(edge.target.as_str()) else {
                continue;
            };
            let (Some(&src_pivot), Some(&tgt_pivot)) =
                (source_owners.first(), target_owners.first())
            else {
                continue;
            };
            let cs = q.class_of(src_pivot);
            let ct = q.class_of(tgt_pivot);
            if cs == ct {
                continue;
            }
            if q.contract(cs, ct).is_ok() {
                applied += 1;
            }
        }
        if applied == 0 {
            break;
        }
    }
    // Walk edges once more to record diagnostics for the pairs that
    // still cannot merge at fixed point.
    for edge in &atomic_edges_relevant {
        let Some(source_owners) = unit_owner_idxs.get(edge.source.as_str()) else {
            continue;
        };
        let Some(target_owners) = unit_owner_idxs.get(edge.target.as_str()) else {
            continue;
        };
        let (Some(&src_pivot), Some(&tgt_pivot)) = (source_owners.first(), target_owners.first())
        else {
            continue;
        };
        let cs = q.class_of(src_pivot);
        let ct = q.class_of(tgt_pivot);
        if cs == ct {
            continue;
        }
        match q.contract(cs, ct) {
            Ok(_) => {
                // Should be unreachable: fixed-point loop already
                // exited on zero successful contractions.
                continue;
            }
            Err(ContractRejected::WouldCreateCycle { cycle }) => {
                rejected.push(SeedContractionRejected::AtomicReachability {
                    edge_id: edge.id.clone(),
                    source_unit_id: edge.source.clone(),
                    target_unit_id: edge.target.clone(),
                    rejected_pair: (
                        q.owner_id(src_pivot).to_string(),
                        q.owner_id(tgt_pivot).to_string(),
                    ),
                    cycle,
                });
            }
            Err(_) => {
                rejected.push(SeedContractionRejected::AtomicReachability {
                    edge_id: edge.id.clone(),
                    source_unit_id: edge.source.clone(),
                    target_unit_id: edge.target.clone(),
                    rejected_pair: (
                        q.owner_id(src_pivot).to_string(),
                        q.owner_id(tgt_pivot).to_string(),
                    ),
                    cycle: CycleEvidence::default(),
                });
            }
        }
    }

    (q, rejected)
}

fn resolve_owner_idxs(q: &QuotientGraph, owner_ids: &[String]) -> Vec<OwnerIdx> {
    let mut idxs: Vec<OwnerIdx> = owner_ids
        .iter()
        .filter_map(|id| q.owner_idx_of(id))
        .collect();
    idxs.sort();
    idxs
}

fn lowest_owner_idx<'a>(
    q: &QuotientGraph,
    owner_ids: impl Iterator<Item = &'a str>,
) -> Option<OwnerIdx> {
    owner_ids.filter_map(|id| q.owner_idx_of(id)).min()
}

// ---------- Compile-time guarantee: no public refinement op exists ----------
//
// The kernel API exposes `contract`, `merge_preserves_invariants`,
// `would_be_cycles_after_contract`, and accessor methods only. There
// is no `split`, no `un_contract`, no `set_class`, no method that
// takes `&mut self` other than `contract`. Adding one would have to be
// done deliberately by editing this file, at which point the
// reviewer's eye would catch it. This is the "easiest as a
// compile-time guarantee (no public method exists)" approach the
// plan calls for; the test `contract_never_un_contracts` in
// `quotient_integration_test.rs` exercises the post-condition.

#[cfg(test)]
mod tests {
    // Inline tests live next to the kernel for fast iteration but
    // would only run under the (currently-broken) `:peel_test`
    // target. The `:peel_quotient_integration_test` target compiles
    // an integration test (`peel/quotient_integration_test.rs`)
    // against the `:peel` library's public API, which is the path
    // that actually exercises the kernel today.
    //
    // Leave this scaffolding in place so when `peel_test` is fixed,
    // dropping a unit test here just works.
}
