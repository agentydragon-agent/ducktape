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

/// Per-explicit-request inputs the builder reads but does not own.
pub(super) struct ExplicitRequestContext<'a> {
    pub(super) runtime_module: &'a Module,
    pub(super) declaration_by_name: &'a HashMap<Id, usize>,
    pub(super) chunk_top_level_mark: swc_common::Mark,
    pub(super) target_dir: &'a str,
    pub(super) chunk_id: &'a str,
    pub(super) target_file: &'a str,
    pub(super) runtime_import_facts: &'a RuntimeImportFacts,
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
    /// Name-keyed index into `bindings_catalogue` for the
    /// duplicate-claim check inside `add_explicit_request`. The
    /// previous shape — a linear scan of the entire `bindings_catalogue`
    /// HashMap on every member of every request — was the dominant
    /// cost in `build_module_plans` on chunks with thousands of spec
    /// modules (O(N^2) over the growing catalogue). Every catalogue
    /// key is constructed via `top_level_id(name,
    /// chunk_top_level_mark)`, so the `name` alone uniquely
    /// identifies the catalogue entry within a chunk; we mirror
    /// inserts into this index and look up by `&str` to keep
    /// duplicate detection O(1) per member.
    ///
    /// Only consulted during `add_explicit_request`; later phases
    /// (destructure siblings, residual sweep) append without
    /// name-collision checks. The map is dropped by
    /// `drop_explicit_request_scratch`.
    catalogue_index_by_name: HashMap<String, BindingKind>,
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
            catalogue_index_by_name: HashMap::new(),
        }
    }

    /// Process one explicit (non-residual) logical-module request:
    /// resolve its anonymous-statement matches, claim each named
    /// member, and append a `ModulePlan`. Duplicate-claim detection
    /// across all explicit requests is keyed by binding-name via the
    /// builder's `catalogue_index_by_name` scratch index.
    pub(super) fn add_explicit_request(
        &mut self,
        index: usize,
        request: &mut LogicalRequest,
        ctx: &ExplicitRequestContext<'_>,
        imported_binding_resolver: &mut ArtifactSourceImportResolutionCache<'_>,
        imported_from_by_src: &mut BTreeMap<String, String>,
    ) -> Result<()> {
        let mut bindings = HashMap::<String, String>::new();
        let anonymous_statement_ordinals =
            resolve_anonymous_statement_ordinals(request, ctx.runtime_module)?;
        for ordinal in &anonymous_statement_ordinals {
            if let Some(existing) = self.anonymous_ordinal_assignment.get(ordinal).copied() {
                let existing_id: String = self
                    .module_plans
                    .get(existing)
                    .map(|plan: &ModulePlan| plan.id.clone())
                    .unwrap_or_else(|| format!("<plan#{existing}>"));
                bail!(
                    "anonymous_statements[].match in module {} also matches the \
                     top-level statement at ordinal {} already claimed by module {}; \
                     each anonymous statement may belong to at most one logical \
                     module.",
                    request.id,
                    ordinal,
                    existing_id,
                );
            }
            self.anonymous_ordinal_assignment.insert(*ordinal, index);
        }
        let dest_target_file = target_file_for_request(ctx.target_dir, &request.target_path)?;
        let module_id = ModuleId(LogicalModuleIndex(index));
        for member in &request.members {
            if let Some(existing_kind) = self.catalogue_index_by_name.get(member.binding.as_str()) {
                let existing_id = match existing_kind {
                    BindingKind::Owned {
                        owner: ModuleId(LogicalModuleIndex(owner_index)),
                    } => self
                        .module_plans
                        .get(*owner_index)
                        .map(|plan| plan.id.clone())
                        .unwrap_or_else(|| format!("<plan#{owner_index}>")),
                    BindingKind::Imported {
                        re_exporter: ModuleId(LogicalModuleIndex(re_index)),
                        ..
                    } => self
                        .module_plans
                        .get(*re_index)
                        .map(|plan| plan.id.clone())
                        .unwrap_or_else(|| format!("<plan#{re_index}>")),
                };
                bail!(
                    "Duplicate binding claim for {:?} in chunk {:?}: already \
                     claimed by module {existing_id} and now also claimed by module \
                     {}. Each binding may belong to exactly one logical module. \
                     Different selector forms (`{{name: foo}}` vs \
                     `{{name: foo, kind: class_declaration}}`) that resolve to the \
                     same source declaration still count as duplicates. To expose a \
                     binding under multiple readable names, list all the renames in \
                     one module.",
                    member.binding,
                    ctx.chunk_id,
                    request.id,
                );
            }
            if member.is_import_specifier {
                let (imported_name, imported_from) = resolve_imported_binding(
                    imported_binding_resolver,
                    ctx.runtime_import_facts,
                    ctx.chunk_id,
                    ctx.target_file,
                    &member.binding,
                    imported_from_by_src,
                )?;
                let kind = BindingKind::Imported {
                    imported_name: imported_name.into(),
                    imported_from,
                    re_exporter: module_id,
                    public_name: member.export_name.as_str().into(),
                };
                self.catalogue_index_by_name
                    .insert(member.binding.clone(), kind.clone());
                self.bindings_catalogue
                    .insert(top_level_id(&member.binding, ctx.chunk_top_level_mark), kind);
            } else {
                bindings.insert(member.binding.clone(), member.export_name.clone());
            }
        }
        for (binding, export_name) in &bindings {
            let binding_id = top_level_id(binding, ctx.chunk_top_level_mark);
            if ctx.declaration_by_name.contains_key(&binding_id) {
                self.binding_assignment.insert(binding_id.clone(), index);
                let kind = BindingKind::Owned { owner: module_id };
                self.catalogue_index_by_name
                    .insert(binding.clone(), kind.clone());
                self.bindings_catalogue.insert(binding_id, kind);
            } else {
                // The spec claimed a binding name that does not
                // appear as a top-level declaration in this chunk —
                // the previous behavior silently dropped the claim,
                // leaving the destination module short one export
                // and the binding falling into the residual sweep.
                // Record it so the pipeline can fail at the end
                // with the full list across every chunk; meanwhile
                // keep lowering as if the spec had not claimed the
                // name (lower_chunk only touches binding ids it can
                // resolve, so the missing claim is a no-op here).
                self.unmatched_spec_claims.push(crate::UnmatchedSpecClaim {
                    chunk_id: ctx.chunk_id.to_string(),
                    module_id: request.id.clone(),
                    binding_name: binding.clone(),
                    export_name: export_name.clone(),
                });
            }
        }
        let binding_comments: BTreeMap<String, String> = request
            .members
            .iter()
            .filter_map(|member| {
                member
                    .comment
                    .as_ref()
                    .map(|c| (member.binding.clone(), c.clone()))
            })
            .collect();
        self.module_plans.push(ModulePlan {
            id: request.id.clone(),
            target_file: dest_target_file,
            target_path: request.target_path.clone(),
            explicit: true,
            bindings,
            anonymous_statement_ordinals,
            comment: request.comment.clone(),
            binding_comments,
        });
        Ok(())
    }

    /// Drop the name-keyed catalogue scratch index now that the
    /// explicit-requests loop is finished. Destructure siblings and
    /// the residual sweep don't consult this index.
    pub(super) fn drop_explicit_request_scratch(&mut self) {
        self.catalogue_index_by_name = HashMap::new();
    }

    /// Destructure-atomicity: a destructuring declarator like
    /// `const { x, y } = obj` binds multiple names from a single
    /// pattern that the lowerer's `split_var_decl` moves as one
    /// unit. If the spec claims any one binding from such a pattern,
    /// every sibling binding must travel to the same module —
    /// otherwise the residual's export list would list a name whose
    /// declarator has already moved away, and `node` would reject the
    /// resulting module with `SyntaxError: Export 'y' is not defined
    /// in module`.
    ///
    /// Implicitly-pulled siblings join the claimed module with their
    /// own binding name as the export name. They aren't separately
    /// spec'd, but the destructure pattern must keep its full name
    /// set together regardless. Conflicting claims (two siblings
    /// claimed by different modules) are rejected.
    pub(super) fn pull_destructure_siblings(
        &mut self,
        destructure_siblings: &BTreeMap<String, BTreeSet<String>>,
        chunk_top_level_mark: swc_common::Mark,
    ) -> Result<()> {
        for (claimed_name, sibling_set) in destructure_siblings {
            let claimed_id = top_level_id(claimed_name, chunk_top_level_mark);
            let Some(&owner_index) = self.binding_assignment.get(&claimed_id) else {
                continue;
            };
            let owner_id = ModuleId(LogicalModuleIndex(owner_index));
            for sibling in sibling_set {
                if sibling == claimed_name {
                    continue;
                }
                let sibling_id = top_level_id(sibling, chunk_top_level_mark);
                match self.binding_assignment.get(&sibling_id).copied() {
                    None => {
                        self.binding_assignment.insert(sibling_id.clone(), owner_index);
                        self.bindings_catalogue
                            .insert(sibling_id, BindingKind::Owned { owner: owner_id });
                        let plan = &mut self.module_plans[owner_index];
                        plan.bindings.insert(sibling.clone(), sibling.clone());
                    }
                    Some(other_index) if other_index != owner_index => {
                        let owner_plan_id = self.module_plans[owner_index].id.clone();
                        let other_plan_id = self.module_plans[other_index].id.clone();
                        bail!(
                            "destructure declarator binds {claimed_name} (claimed by module \
                             {owner_plan_id}) and {sibling} (claimed by module {other_plan_id}); \
                             destructuring declarators must move atomically — claim both \
                             bindings from the same module or claim neither.",
                        );
                    }
                    Some(_) => {}
                }
            }
        }
        Ok(())
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
