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
//! This kernel is the **first cut** (correctness, not speed): the
//! cycle set is rebuilt from scratch on every query and on every
//! mutation. Commit 4 will replace it with persistent SCC + post-order
//! state.
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

use std::collections::{BTreeMap, BTreeSet};

use analysis::{OwnerGraphReport, RESIDUAL_ENTRY_MODULE_ID};
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
}

/// One spec-module declaration the seeding protocol consumes. The
/// `owner_ids` list is the set of owners the module's `members:`
/// resolves to; the seed pre-contracts them all into one class.
#[derive(Debug, Clone)]
pub struct SpecModuleGroup {
    pub module_id: String,
    pub owner_ids: Vec<String>,
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
    /// resolve to known owners. Source-of-truth; the cycle set is
    /// computed from this each query.
    owner_constraining_edges: Vec<(OwnerIdx, OwnerIdx)>,
    /// Cap on per-class combined lines. Exceeding this is a rejected
    /// merge.
    cap_lines: usize,
}

impl QuotientGraph {
    /// Build a fresh quotient over `report.nodes`, each owner in its
    /// own singleton class. `cap_lines` is the size cap consulted by
    /// `merge_preserves_invariants`.
    pub fn from_report(report: &OwnerGraphReport, cap_lines: usize) -> Self {
        let owner_ids: Vec<String> = report.nodes.iter().map(|n| n.id.clone()).collect();
        let owner_index: BTreeMap<String, OwnerIdx> = owner_ids
            .iter()
            .enumerate()
            .map(|(i, id)| (id.clone(), OwnerIdx(i)))
            .collect();

        let mut classes = Vec::<ClassData>::with_capacity(owner_ids.len());
        let mut owner_to_class = Vec::<ClassId>::with_capacity(owner_ids.len());
        for (i, node) in report.nodes.iter().enumerate() {
            let mut members = BTreeSet::new();
            members.insert(OwnerIdx(i));
            classes.push(ClassData {
                members,
                lines: owner_line_count_from_report(node),
                is_residual: node.destination.residual
                    || node.destination.id == RESIDUAL_ENTRY_MODULE_ID,
            });
            owner_to_class.push(ClassId(i));
        }

        let mut owner_constraining_edges: Vec<(OwnerIdx, OwnerIdx)> = Vec::new();
        for edge in &report.edges {
            if !edge.constrains_init_order {
                continue;
            }
            let (Some(&s), Some(&t)) =
                (owner_index.get(&edge.source), owner_index.get(&edge.target))
            else {
                continue;
            };
            if s == t {
                continue;
            }
            owner_constraining_edges.push((s, t));
        }

        QuotientGraph {
            owner_ids,
            owner_to_class,
            classes,
            owner_constraining_edges,
            cap_lines,
        }
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
        let mut q = Self::from_report(report, cap_lines);
        let mut group_class_ids = Vec::with_capacity(groups.len());
        for group in groups {
            let mut winner: Option<ClassId> = None;
            for &owner in group {
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
            group_class_ids.push(winner.expect("partition group must be non-empty"));
        }
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
    /// constraining-edge quotient.
    pub fn cycle_set(&self) -> CycleEvidence {
        self.compute_cycles_with_overlay(None)
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
    /// - the merge would violate residual-stickiness or the cap
    ///   (evidence empty), or
    /// - a strictly new cycle would appear in the post-merge cycle
    ///   set (evidence: the new cycles).
    ///
    /// The merge cannot create new cycles under today's gate (proof
    /// in the plan). The diagnostic exists so the seed protocol can
    /// surface the *current* unrealizable cycle the spec author's
    /// declared grouping would inhabit — i.e. the cycle the seed
    /// would have to live inside if the contraction proceeded.
    pub fn would_be_cycles_after_contract(
        &self,
        c1: ClassId,
        c2: ClassId,
    ) -> Option<CycleEvidence> {
        let pre = self.cycle_set();
        let post = self.compute_cycles_with_overlay(Some((c1, c2)));
        // Cycles strictly added by the merge (defensive — should
        // always be empty under today's gate).
        let pre_keys: BTreeSet<Vec<ClassId>> =
            pre.cycles.iter().map(|c| c.classes.clone()).collect();
        let mut added: Vec<CycleClassSet> = post
            .cycles
            .iter()
            .filter(|c| !pre_keys.contains(&c.classes))
            .cloned()
            .collect();

        // Surface the pre-existing cycle that *includes* both
        // endpoints, if any — that's the cycle the seed protocol
        // wants to attribute the rejection to. (The merge wouldn't
        // create it; the spec's grouping inherits it.)
        let mut surfaced: Vec<CycleClassSet> = pre
            .cycles
            .iter()
            .filter(|c| c.classes.contains(&c1) && c.classes.contains(&c2))
            .cloned()
            .collect();
        surfaced.append(&mut added);
        if surfaced.is_empty() {
            None
        } else {
            surfaced.sort();
            surfaced.dedup();
            Some(CycleEvidence { cycles: surfaced })
        }
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
        self.classes[loser.0].lines = 0;
        self.classes[loser.0].is_residual = false;
        for member in &loser_members {
            self.owner_to_class[member.0] = winner;
        }
        self.classes[winner.0].members.extend(loser_members);
        self.classes[winner.0].lines = self.classes[winner.0].lines.saturating_add(loser_lines);
        if loser_residual {
            self.classes[winner.0].is_residual = true;
        }
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
    let mut modules: Vec<&SpecModuleGroup> = spec_modules.iter().collect();
    modules.sort_by(|a, b| a.module_id.cmp(&b.module_id));
    for module in modules {
        let owner_idxs = resolve_owner_idxs(&q, &module.owner_ids);
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
