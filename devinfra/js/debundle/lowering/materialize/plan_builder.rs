//! `ChunkPlanBuilder` owns the per-chunk mutable state that
//! `materialize_logical_chunk` used to thread as five loose `&mut`
//! maps through eight phases. Each phase becomes a method on the
//! builder; the same lookup (`bindings_catalogue` + `binding_assignment`)
//! that previously appeared in eight subtly different forms now lives
//! behind the builder's encapsulation.
//!
//! See `ARCH_REVIEW_2026_05.md` § "`materialize_logical_chunk` is a
//! 750-line god function with parallel mutable state" for the
//! original motivation.

use super::*;

/// Output of `ChunkPlanBuilder::finalize`: everything downstream
/// `lower_chunk` + the chunk-report builder need from the plan
/// construction phase.
pub(super) struct ChunkPlan {
    pub(super) module_plans: Vec<ModulePlan>,
    pub(super) binding_assignment: HashMap<Id, usize>,
    pub(super) bindings_catalogue: HashMap<Id, BindingKind>,
    pub(super) anonymous_ordinal_assignment: BTreeMap<usize, usize>,
    pub(super) unmatched_spec_claims: Vec<crate::UnmatchedSpecClaim>,
}

/// Builds a `ChunkPlan` from spec requests and chunk AST analysis.
///
/// Owns the five mutable maps (`binding_assignment`,
/// `bindings_catalogue`, `anonymous_ordinal_assignment`, `module_plans`,
/// `residual_plan_index`) that the previous shape passed through every
/// helper as `&mut` arguments. All duplicate-claim / cross-claim
/// invariants on the canonical state live behind the builder's
/// methods.
pub(super) struct ChunkPlanBuilder {
    /// Per-binding-`Id` index into `module_plans`. Authoritative
    /// source of "which logical module owns this binding".
    binding_assignment: HashMap<Id, usize>,
    /// Per-source-body-index → `module_plans` index, for anonymous
    /// (non-declared) top-level statements claimed by spec
    /// `anonymous_statements` entries.
    anonymous_ordinal_assignment: BTreeMap<usize, usize>,
    /// The plans being constructed, in append order. Final indices
    /// stable: `binding_assignment` and `anonymous_ordinal_assignment`
    /// hold positional references.
    module_plans: Vec<ModulePlan>,
    /// `BindingKind` view of every claimed binding (Owned vs Imported).
    /// Owned entries duplicate `binding_assignment`'s mapping in a
    /// different shape; Imported entries are exclusive to this map.
    bindings_catalogue: HashMap<Id, BindingKind>,
    /// Index into `module_plans` of the "catchall" plan that
    /// unclaimed bindings sweep into, when one exists. `None` when
    /// the chunk has no residual landing site (default
    /// `InlineInEntry` with no fallback request, or `MiniFactors`).
    residual_plan_index: Option<usize>,
    /// Spec claims that named a binding for which no top-level
    /// declaration exists in this chunk. Materialization keeps
    /// running with the missing claim treated as if absent; the
    /// caller fails the pipeline at the end with the rolled-up list.
    unmatched_spec_claims: Vec<crate::UnmatchedSpecClaim>,
}

impl ChunkPlanBuilder {
    pub(super) fn new() -> Self {
        Self {
            binding_assignment: HashMap::new(),
            anonymous_ordinal_assignment: BTreeMap::new(),
            module_plans: Vec::new(),
            bindings_catalogue: HashMap::new(),
            residual_plan_index: None,
            unmatched_spec_claims: Vec::new(),
        }
    }

    pub(super) fn finalize(self) -> ChunkPlan {
        ChunkPlan {
            module_plans: self.module_plans,
            binding_assignment: self.binding_assignment,
            bindings_catalogue: self.bindings_catalogue,
            anonymous_ordinal_assignment: self.anonymous_ordinal_assignment,
            unmatched_spec_claims: self.unmatched_spec_claims,
        }
    }

    /// Access the mutable interior for callers that still hold the
    /// pre-refactor inline shape. Will shrink as each phase moves
    /// into a builder method.
    pub(super) fn parts_mut(
        &mut self,
    ) -> (
        &mut HashMap<Id, usize>,
        &mut BTreeMap<usize, usize>,
        &mut Vec<ModulePlan>,
        &mut HashMap<Id, BindingKind>,
        &mut Option<usize>,
        &mut Vec<crate::UnmatchedSpecClaim>,
    ) {
        (
            &mut self.binding_assignment,
            &mut self.anonymous_ordinal_assignment,
            &mut self.module_plans,
            &mut self.bindings_catalogue,
            &mut self.residual_plan_index,
            &mut self.unmatched_spec_claims,
        )
    }
}
