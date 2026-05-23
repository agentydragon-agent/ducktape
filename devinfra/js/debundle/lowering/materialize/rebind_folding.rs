use super::*;

/// Resolve rebind-only atomic-unit "soft" conflicts by silently
/// extending the explicit claim's plan to cover any member of the
/// cycle that has no explicit destination.
///
/// Atomic factor units symmetrize `LazyRebind`/`EagerRebind` edges
/// (see <atomic_units.rs>) because ESM imports are read-only — a
/// peel that places the rebind's write site in one module and its
/// declaration in another would emit code that throws `TypeError:
/// Assignment to constant variable` the first time the assignment
/// fires. Without this pass, such a spec would surface as an
/// `atomic_unit_conflict` and the materializer would bail.
///
/// When exactly one member of the cycle carries an explicit claim
/// and the rest are unclaimed (or were already swept into the
/// residual landing site), the conflict is the spec author's
/// implicit oversight rather than a contradiction: they peeled the
/// writer but left the declarer at the default destination, not
/// realizing the cycle pulls them together. Extending the writer's
/// module to cover the declarer keeps the rebind intra-module —
/// the writer's assignment resolves locally — and preserves the
/// spec's peel intent.
///
/// Multi-explicit-destination conflicts fall through unchanged so
/// the materializer's bail surfaces the contradiction. Conflicts
/// with non-rebind causes (`LocalEffect`, eager cycles, sequenced
/// side-effect chains) also fall through — those have their own
/// resolution stories and are intentionally surfaced as hard
/// errors.
pub(super) fn fold_rebind_atomic_units(
    precomputed: &OwnerGraphAndUnits,
    binding_assignment: &mut HashMap<Id, usize>,
    bindings_catalogue: &mut HashMap<Id, BindingKind>,
    module_plans: &mut [ModulePlan],
    residual_plan_index: Option<usize>,
) {
    let owner_graph = &precomputed.owner_graph;
    'unit: for unit in &precomputed.atomic_units {
        if unit.causes.is_empty() {
            continue;
        }
        let rebind_only = unit
            .causes
            .iter()
            .all(|cause| matches!(cause, DepKind::LazyRebind | DepKind::EagerRebind));
        if !rebind_only {
            continue;
        }
        let mut explicit_dest: Option<usize> = None;
        let mut owners_to_fold: Vec<OwnerId> = Vec::new();
        for &owner_id in &unit.members {
            let Some(node) = owner_graph.node(owner_id) else {
                continue;
            };
            if node.declared.is_empty() {
                // Anonymous statements don't appear in `binding_assignment`;
                // their routing is via `anonymous_ordinal_assignment`. They
                // can't be the carrier of a rebind cause anyway — a rebind
                // edge needs a declared target — so skipping them is safe.
                continue;
            }
            let mut owner_claim: Option<usize> = None;
            for binding_id in &node.declared {
                let Some(&idx) = binding_assignment.get(binding_id) else {
                    continue;
                };
                // A binding that was swept into the residual landing site
                // counts as "unclaimed" for fold purposes — the user didn't
                // explicitly route it there, the sweep did.
                if Some(idx) == residual_plan_index {
                    continue;
                }
                owner_claim = Some(idx);
                break;
            }
            match owner_claim {
                Some(idx) => match explicit_dest {
                    None => explicit_dest = Some(idx),
                    Some(existing) if existing != idx => continue 'unit,
                    _ => {}
                },
                None => owners_to_fold.push(owner_id),
            }
        }
        let Some(dest) = explicit_dest else {
            continue;
        };
        if owners_to_fold.is_empty() {
            continue;
        }
        let module_id = ModuleId(LogicalModuleIndex(dest));
        for owner_id in owners_to_fold {
            let Some(node) = owner_graph.node(owner_id) else {
                continue;
            };
            for binding_id in &node.declared {
                let was_assigned = binding_assignment.get(binding_id).copied();
                binding_assignment.insert(binding_id.clone(), dest);
                bindings_catalogue
                    .insert(binding_id.clone(), BindingKind::Owned { owner: module_id });
                let name = binding_id.0.as_ref().to_string();
                module_plans[dest]
                    .bindings
                    .entry(name.clone())
                    .or_insert_with(|| name.clone());
                if let Some(was) = was_assigned
                    && Some(was) == residual_plan_index
                {
                    module_plans[was].bindings.remove(&name);
                }
            }
        }
    }
}
