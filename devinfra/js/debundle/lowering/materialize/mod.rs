//! Per-chunk materialization: take an `OwnerGraphAndUnits` + spec plan, run the
//! chunk through `lower_chunk`, and emit a `MaterializedLogicalChunk` whose
//! files/applied/report are spliced into the artifact by
//! `apply_materialized_logical_chunks`.

mod apply;
mod plan_builder;
mod rebind_folding;

pub(super) use apply::apply_materialized_logical_chunks;
use plan_builder::{ChunkPlan, ChunkPlanBuilder, ExplicitRequestContext};
use rebind_folding::fold_rebind_atomic_units;

use super::io::write_chunk_report_json;
use super::ordinal::statement_ordinal_for_body_index;
use super::util::{render_atomic_unit_cause_guidance, target_file_for_request};
use super::*;
use crate::time_phase;
use output_layout::{ATOMIC_UNIT_CONFLICTS_REPORT, CYCLES_REPORT, OWNER_GRAPH_REPORT};

pub(super) struct MaterializeLogicalChunkInputs<'a> {
    pub(super) artifact: &'a ChunkBundle,
    pub(super) artifact_indexes: &'a ArtifactIndexes,
    pub(super) logical_modules: &'a BTreeMap<String, BTreeMap<String, LogicalModule>>,
    pub(super) chunk_renames: &'a BTreeMap<String, ChunkRenames>,
    pub(super) unassigned_mode: &'a BTreeMap<String, UnassignedMode>,
    pub(super) chunk_analysis_options: &'a BTreeMap<String, ChunkAnalysisOptions>,
    pub(super) file: Option<&'a str>,
    pub(super) target_dir: &'a str,
    pub(super) report_out_dir: Option<&'a Path>,
    pub(super) chunk_id: &'a str,
}

pub(super) struct MaterializedLogicalChunk {
    pub(super) chunk_id: ChunkId,
    pub(super) target_file: String,
    pub(super) source_path: String,
    pub(super) files: Vec<JsFile>,
    pub(super) file_records: Vec<(String, FileRole)>,
    pub(super) applied: Vec<SelectedModuleLowering>,
    pub(super) directory_dependency_facts: Vec<DirectoryDependencyFact>,
    pub(super) validation: ChunkValidationSummary,
    pub(super) report: ChunkModulesReport,
    /// Spec member claims that named a binding for which no
    /// top-level declaration exists in this chunk. Materialization
    /// continues — the binding silently falls through to the
    /// residual sweep — but `materialize_logical_modules` rolls
    /// these up across every chunk and fails the pipeline at the
    /// end with the full list.
    pub(super) unmatched_spec_claims: Vec<crate::UnmatchedSpecClaim>,
}

pub(super) fn materialize_logical_chunk(
    inputs: MaterializeLogicalChunkInputs<'_>,
) -> Result<MaterializedLogicalChunk> {
    let MaterializeLogicalChunkInputs {
        artifact,
        artifact_indexes,
        logical_modules,
        chunk_renames,
        unassigned_mode,
        chunk_analysis_options,
        file,
        target_dir,
        report_out_dir,
        chunk_id,
    } = inputs;
    // The spec validator (`validate_transform_spec`) enforces that
    // every materialised chunk has an `unassigned_mode` entry, so
    // this lookup must not miss. Missing here is a bug in the
    // validator, not a recoverable spec error.
    let chunk_unassigned_mode = unassigned_mode.get(chunk_id).cloned().with_context(|| {
        format!("materialize_logical_modules missing unassigned_mode for chunk: {chunk_id}")
    })?;
    let chunk_id_interned = artifact
        .chunk_table
        .get(chunk_id)
        .with_context(|| format!("materialize_logical_modules unknown chunk: {chunk_id}"))?;
    let chunk_started = Instant::now();
    let mut timings = PhaseTimings::default();
    let target_file = time_phase!(timings, "resolve_entry", {
        file.map(normalize_module_path)
            .transpose()?
            .or_else(|| get_chunk_entry_path(artifact, chunk_id_interned))
            .with_context(|| {
                format!(
                    "materialize_logical_modules could not determine entry file for chunk: {chunk_id}"
                )
            })
    })?;
    let runtime_file = artifact
        .js_chunk(chunk_id_interned)?
        .get_file(&target_file)
        .with_context(|| {
            format!("materialize_logical_modules missing entry file for chunk: {chunk_id}")
        })?;
    let runtime_ast = runtime_file.ast().with_context(|| {
        format!("materialize_logical_modules missing entry AST for chunk: {chunk_id}")
    })?;
    // Chunk-wide `top_level_mark` for resolving spec-derived String
    // binding names to hygiene-aware `Id`s via `top_level_id`.
    let chunk_top_level_mark = runtime_ast.top_level_mark;
    let header_lines = runtime_file.header_lines.clone();
    let source_path = runtime_file.metadata.source_path.clone();
    let chunk_ast_analysis = time_phase!(timings, "analyze_chunk_ast", {
        analyze_chunk_ast(&runtime_ast.module)
    });
    let ChunkAstAnalysis {
        runtime_import_facts,
        declarations,
        declaration_by_name,
        destructure_siblings,
        pre_existing_entry_exports,
        pre_existing_public_export_names,
    } = chunk_ast_analysis;
    let requests = time_phase!(timings, "build_requests", {
        logical_requests_for_chunk(
            logical_modules.get(chunk_id),
            &chunk_unassigned_mode,
            chunk_renames.contains_key(chunk_id),
            chunk_id,
            target_dir,
        )
    })?;
    let mut explicit_requests = requests
        .iter()
        .filter(|request| !request.residual)
        .cloned()
        .collect::<Vec<_>>();
    let residual_request = requests.iter().find(|request| request.residual).cloned();

    let build_module_plans_started = Instant::now();
    let mut builder = ChunkPlanBuilder::new();
    let mut imported_binding_resolver =
        ArtifactSourceImportResolutionCache::new(artifact, artifact_indexes);
    let mut imported_from_by_src = BTreeMap::<String, String>::new();
    let explicit_request_ctx = ExplicitRequestContext {
        runtime_module: &runtime_ast.module,
        declaration_by_name: &declaration_by_name,
        chunk_top_level_mark,
        target_dir,
        chunk_id,
        target_file: &target_file,
        runtime_import_facts: &runtime_import_facts,
    };
    for (index, request) in explicit_requests.iter_mut().enumerate() {
        builder.add_explicit_request(
            index,
            request,
            &explicit_request_ctx,
            &mut imported_binding_resolver,
            &mut imported_from_by_src,
        )?;
    }
    drop(imported_binding_resolver);
    builder.drop_explicit_request_scratch();

    let (
        binding_assignment,
        anonymous_ordinal_assignment,
        module_plans,
        bindings_catalogue,
        residual_plan_index,
        _unmatched_spec_claims,
    ) = builder.parts_mut();

    // Destructure-atomicity: a destructuring declarator like
    // `const { x, y } = obj` binds multiple names from a single
    // pattern that the lowerer's `split_var_decl` moves as one
    // unit. If the spec claims any one binding from such a
    // pattern, every sibling binding must travel to the same
    // module — otherwise the residual's export list would list a
    // name whose declarator has already moved away, and `node`
    // would reject the resulting module with
    // `SyntaxError: Export 'y' is not defined in module`.
    //
    // Implicitly-pulled siblings join the claimed module with
    // their own binding name as the export name. They aren't
    // separately spec'd, but the destructure pattern must keep
    // its full name set together regardless. Conflicting claims
    // (two siblings claimed by different modules) are rejected.
    for (claimed_name, sibling_set) in &destructure_siblings {
        let claimed_id = top_level_id(claimed_name, chunk_top_level_mark);
        let Some(&owner_index) = binding_assignment.get(&claimed_id) else {
            continue;
        };
        let owner_id = ModuleId(LogicalModuleIndex(owner_index));
        for sibling in sibling_set {
            if sibling == claimed_name {
                continue;
            }
            let sibling_id = top_level_id(sibling, chunk_top_level_mark);
            match binding_assignment.get(&sibling_id).copied() {
                None => {
                    binding_assignment.insert(sibling_id.clone(), owner_index);
                    bindings_catalogue.insert(sibling_id, BindingKind::Owned { owner: owner_id });
                    let plan = &mut module_plans[owner_index];
                    plan.bindings.insert(sibling.clone(), sibling.clone());
                }
                Some(other_index) if other_index != owner_index => {
                    let owner_plan_id = module_plans[owner_index].id.clone();
                    let other_plan_id = module_plans[other_index].id.clone();
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

    // The catchall destination index (`residual_plan_index`) lives
    // on the builder. When set, it points either to a synthesized
    // memberless residual plan (built below) or to an explicit
    // logical-module plan whose target matches `unassigned_mode:
    // catchall_file { target }` and which is therefore the
    // designated overflow destination. `None` means the chunk has no
    // residual landing site (default `InlineInEntry` mode with no
    // fallback request, or `MiniFactors` mode).
    let catchall_target_for_overflow = chunk_unassigned_mode.catchall_file_target();
    if let Some(residual) = &residual_request {
        let residual_index = module_plans.len();
        let residual_module_id = ModuleId(LogicalModuleIndex(residual_index));
        let mut residual_bindings = HashMap::<String, String>::new();
        for decl in &declarations {
            for (name, id) in &decl.bindings {
                if !binding_assignment.contains_key(id) {
                    binding_assignment.insert(id.clone(), residual_index);
                    residual_bindings.insert(name.clone(), name.clone());
                    bindings_catalogue.insert(
                        id.clone(),
                        BindingKind::Owned {
                            owner: residual_module_id,
                        },
                    );
                }
            }
        }
        if !residual_bindings.is_empty() {
            module_plans.push(ModulePlan {
                id: residual.id.clone(),
                target_file: target_file_for_request(target_dir, &residual.target_path)?,
                target_path: residual.target_path.clone(),
                explicit: false,
                bindings: residual_bindings,
                anonymous_statement_ordinals: Vec::new(),
                comment: None,
                binding_comments: BTreeMap::new(),
            });
            *residual_plan_index = Some(residual_index);
        }
    } else if let Some(catchall_target) = catchall_target_for_overflow {
        // No memberless residual request was synthesized — an
        // explicit `logical_modules` entry already pinned itself at
        // the catchall target. Append unclaimed bindings to that
        // plan so the residual sweep still has a home, and flip
        // its `explicit` flag so downstream consumers see it as
        // the residual destination (residual flag on the factorization
        // module, OutputRole::ResidualModule in artifact metadata, and
        // `residual: true` in modules.json).
        let owner_index = module_plans
            .iter()
            .position(|plan| plan.target_path == catchall_target);
        if let Some(owner_index) = owner_index {
            let owner_id = ModuleId(LogicalModuleIndex(owner_index));
            let owner_plan = &mut module_plans[owner_index];
            owner_plan.explicit = false;
            for decl in &declarations {
                for (name, id) in &decl.bindings {
                    if !binding_assignment.contains_key(id) {
                        binding_assignment.insert(id.clone(), owner_index);
                        owner_plan
                            .bindings
                            .entry(name.clone())
                            .or_insert_with(|| name.clone());
                        bindings_catalogue
                            .insert(id.clone(), BindingKind::Owned { owner: owner_id });
                    }
                }
            }
            *residual_plan_index = Some(owner_index);
        }
    }
    timings.add("build_module_plans", build_module_plans_started.elapsed());

    let chunk_renames_map = time_phase!(timings, "collect_chunk_renames", {
        chunk_renames
            .get(chunk_id)
            .map(collect_chunk_renames)
            .transpose()
    })?
    .unwrap_or_default();

    let (
        factorization,
        redundant_purity_hints,
        module_plans,
        binding_assignment,
        anonymous_ordinal_assignment,
        unmatched_spec_claims,
    ) = {
        // Spec annotations carried on any member form (logical-module
        // member, chunk_renames member) propagate the same way:
        // collect them by local binding name and feed them into fact
        // analysis. They are semantic trust assertions, not ownership
        // claims; binding patches routed through chunk_renames still
        // do not force factorizer grouping.
        let analysis_hints: AnalysisHints = time_phase!(timings, "collect_analysis_hints", {
            let mut hints = AnalysisHints::default();
            for req in &explicit_requests {
                for m in &req.members {
                    apply_member_hints(&mut hints, &m.binding, m.purity, &m.pure_members, m.effect);
                }
            }
            if let Some(cr) = chunk_renames.get(chunk_id) {
                for m in &cr.members {
                    apply_member_hints(
                        &mut hints,
                        &m.selector.binding.name,
                        m.purity,
                        &m.pure_members,
                        m.effect,
                    );
                }
            }
            hints
        });
        let line_index = time_phase!(timings, "build_source_line_index", {
            runtime_ast.line_index()
        });
        // Stage A: spec-independent analysis (facts + owner graph +
        // structural atomic units). See `stage_one.rs` for the
        // composer; DESIGN.md §"Pipeline split (Stage A / Stage B)"
        // for the boundary's role. v1 keeps Stage A in memory; v2
        // adds per-concept JSON sidecars + a `materialize_from_*`
        // entry point so a Bazel rule can split into two cacheable
        // actions.
        let owner_graph_options = OwnerGraphOptions {
            dataflow_aware_s_chain: chunk_analysis_options
                .get(chunk_id)
                .is_some_and(|opts| opts.dataflow_aware_s_chain),
        };
        let stage_one = time_phase!(timings, "compute_stage_one_analysis", {
            compute_stage_one_analysis(
                &runtime_ast.module,
                &analysis_hints,
                Some(&source_path),
                |span| line_index.line_range_for_span(span),
                owner_graph_options,
            )
        });
        // Stage A on-disk sidecars: snapshot the spec-independent
        // analysis (AST + facts + atomic units + manifest) under
        // `<chunk_id>/chunk_analysis/` so a future
        // `materialize_from_analysis` reader (task #78) can pick up
        // Stage B from a cached Stage A action. Conditional on
        // `report_out_dir`: the in-memory pipeline still works without
        // them, and the e2e suites that don't request a report dir
        // shouldn't pay the I/O cost. See `stage_one_sidecars.rs`.
        if let Some(report_out_dir) = report_out_dir {
            time_phase!(timings, "write_stage_one_sidecars", {
                write_stage_one_sidecars(report_out_dir, chunk_id, &stage_one)
            })?;
        }
        let StageOneAnalysis {
            fact_analysis: analysis,
            owner_graph_and_units: precomputed,
        } = stage_one;
        // Per-hint warnings on stderr: each `purity: pure` spec hint
        // the analyzer infers automatically (binding's body classifies
        // Pure without the override, or admits as PlainData). Surfaced
        // every build so spec authors are nudged to prune load-free
        // hints — every such hint is an extra trust assertion the
        // validator can't re-verify, and the shrinking trust surface
        // is the point of recursive purity inference.
        for hint in &analysis.redundant_purity_hints {
            eprintln!(
                "warning: chunk {chunk_id}: `purity: pure` hint on binding `{binding}` is redundant — \
                 the analyzer infers {reason} for this binding without the hint and the override is a no-op. \
                 Remove the hint from the spec.",
                binding = hint.binding_name,
                reason = match hint.reason {
                    RedundantPurityReason::InferredPureFunction =>
                        "pure (the function body classifies Pure by recursive analysis)",
                    RedundantPurityReason::InferredPlainDataBinding =>
                        "PlainData (chunk-local const/let plain literal with no chunk-wide writes through the binding)",
                },
            );
        }
        for hint in &analysis.redundant_pure_member_hints {
            eprintln!(
                "warning: chunk {chunk_id}: `pure_members: [{property}]` on binding `{binding}` \
                 is redundant — the analyzer infers {reason} without the hint. \
                 Remove the entry from the spec.",
                binding = hint.binding_name,
                property = hint.property,
                reason = match hint.reason {
                    RedundantPureMemberReason::WhitelistedStaticCall =>
                        "pure via PURE_STATIC_CALLS (already on the global-receiver whitelist)",
                },
            );
        }
        if let Some(ord) = analysis.top_level_await {
            anyhow::bail!(
                "materialize_logical_modules: chunk {chunk_id} has top-level `await` \
                 at statement #{ordinal} (TLA); the debundler's realizability theorem \
                 does not cover async modules (DESIGN.md A2). Wrap the awaited code \
                 in an async function or rewrite as a synchronous initialization.",
                ordinal = ord.0,
            );
        }
        time_phase!(timings, "fold_rebind_atomic_units", {
            fold_rebind_atomic_units(
                &precomputed,
                binding_assignment,
                bindings_catalogue,
                module_plans,
                *residual_plan_index,
            );
        });
        if matches!(chunk_unassigned_mode, UnassignedMode::MiniFactors) {
            time_phase!(timings, "synthesize_mini_factor_plans", {
                synthesize_mini_factor_plans(
                    &precomputed,
                    &runtime_ast.module.body,
                    *residual_plan_index,
                    module_plans,
                    binding_assignment,
                    bindings_catalogue,
                    anonymous_ordinal_assignment,
                    chunk_top_level_mark,
                    target_dir,
                )
            })?;
        }
        // Release the `parts_mut` borrow before consuming the builder.
        // From here on, plan state is owned by the returned `ChunkPlan`.
        let ChunkPlan {
            module_plans,
            binding_assignment,
            bindings_catalogue,
            anonymous_ordinal_assignment,
            unmatched_spec_claims,
        } = builder.finalize();
        let mut logical_modules: Vec<FactorizationLogicalModule> =
            time_phase!(timings, "project_factorization_modules", {
                module_plans
                    .iter()
                    .map(|plan| FactorizationLogicalModule {
                        id: plan.id.clone(),
                        target_file: plan.target_file.clone(),
                        residual: !plan.explicit,
                        rename_map: plan
                            .bindings
                            .iter()
                            .map(|(local, exported)| {
                                (
                                    top_level_id(local, chunk_top_level_mark),
                                    exported.as_str().into(),
                                )
                            })
                            .collect(),
                        // ChunkFactorization's owner graph uses post-comma-list-split
                        // `StatementOrdinal`s; convert body indices here so
                        // the destination override targets the right owner
                        // node (an anon body item is always a single
                        // post-split position, but earlier comma-list
                        // var-decls in the chunk shift the count).
                        anonymous_statement_ordinals: plan
                            .anonymous_statement_ordinals
                            .iter()
                            .map(|body_idx| {
                                statement_ordinal_for_body_index(
                                    &runtime_ast.module.body,
                                    *body_idx,
                                )
                            })
                            .collect(),
                    })
                    .collect()
            });
        // Commit 1 transitional behavior: the partition's "default
        // destination" — the module owners with no claim fall back to —
        // is a factorization-only sentinel logical module appended past
        // `module_plans.len()`. The emit loop iterates `module_plans`,
        // so the sentinel never gets emitted as a file. Anonymous
        // statements without an explicit logical-module
        // `anonymous_statements` match thus stay in the sentinel,
        // preserving the pre-refactor split where anon-fallback was a
        // distinct destination from the residual logical module (which
        // only held named-unclaimed bindings). Commit 2 collapses this
        // sentinel back into the residual module via explicit
        // `anonymous_statement_ordinals` routing.
        let sentinel_residual_target = chunk_unassigned_mode
            .catchall_file_target()
            .map(|t| target_file_for_request(target_dir, t))
            .transpose()?
            .unwrap_or_else(|| target_file.clone());
        let sentinel_idx = logical_modules.len();
        logical_modules.push(FactorizationLogicalModule {
            id: format!("{chunk_id}::anon_residual_sentinel"),
            target_file: sentinel_residual_target,
            residual: true,
            rename_map: HashMap::new(),
            anonymous_statement_ordinals: Vec::new(),
        });
        let default_destination = ModuleId(LogicalModuleIndex(sentinel_idx));
        let redundant_purity_hints = analysis.redundant_purity_hints;
        let factorization_chunk_renames: HashMap<Id, swc_atoms::Atom> = chunk_renames_map
            .iter()
            .map(|(local, exported)| {
                (
                    top_level_id(local, chunk_top_level_mark),
                    exported.as_str().into(),
                )
            })
            .collect();
        let factorization = time_phase!(timings, "build_factorization", {
            ChunkFactorization::build_with(
                chunk_id.to_string(),
                analysis.facts,
                precomputed,
                bindings_catalogue,
                logical_modules,
                factorization_chunk_renames,
                default_destination,
            )
        });
        (
            factorization,
            redundant_purity_hints,
            module_plans,
            binding_assignment,
            anonymous_ordinal_assignment,
            unmatched_spec_claims,
        )
    };
    let factorization_report = time_phase!(timings, "validate_factorization", {
        factorization.validate()
    });
    if let Some(report_out_dir) = report_out_dir {
        let owner_graph_report = time_phase!(timings, "build_owner_graph_report", {
            factorization.owner_graph_report()
        });
        time_phase!(timings, "write_owner_graph_report", {
            write_chunk_report_json(
                report_out_dir,
                chunk_id,
                OWNER_GRAPH_REPORT,
                &owner_graph_report,
            )
        })?;
    }

    if !factorization_report.atomic_unit_conflicts.is_empty() {
        if let Some(report_out_dir) = report_out_dir {
            time_phase!(timings, "write_atomic_unit_conflicts_report", {
                write_chunk_report_json(
                    report_out_dir,
                    chunk_id,
                    ATOMIC_UNIT_CONFLICTS_REPORT,
                    &factorization_report.atomic_unit_conflicts,
                )
            })?;
        }
        let summary = render_atomic_unit_conflict_summary(
            &factorization_report.atomic_unit_conflicts,
            &|id| factorization.analysis.module_name(id),
        );
        let causes = render_atomic_unit_cause_guidance(&factorization_report.atomic_unit_conflicts);
        bail!(
            "materialize_logical_modules: chunk {chunk_id} has {n} atomic-factor-unit conflict(s) — the spec assigns members of one atomic factor unit to different destination modules, forming a cycle in the module dep graph that the constraining-edge SCC analysis says is unrealizable. Atomic factor units come from FACTORIZE.md's `G_atomic` SCC over the owner graph; every member must co-locate. {causes}Resolve by reconciling each unit's claims into a single destination. Full evidence written to reports/tree/{chunk_id}/atomic_unit_conflicts.json; owner graph written to reports/tree/{chunk_id}/owner_graph.json. Summary:\n{summary}",
            n = factorization_report.atomic_unit_conflicts.len(),
        );
    }

    if !factorization_report.cycles.is_empty() {
        if let Some(report_out_dir) = report_out_dir {
            time_phase!(timings, "write_cycles_report", {
                write_chunk_report_json(
                    report_out_dir,
                    chunk_id,
                    CYCLES_REPORT,
                    &factorization_report.cycles,
                )
            })?;
        }
        let summary = render_cycle_summary(&factorization_report.cycles);
        bail!(
            "materialize_logical_modules: chunk {chunk_id} — spec is unrealizable: {n} module-quotient SCC(s) with at-init / side-effect edges between members. Each SCC names the binding pairs whose split forced the cycle; co-locate them or break a back-edge. Full per-cycle evidence at reports/tree/{chunk_id}/cycles.json; owner graph at reports/tree/{chunk_id}/owner_graph.json. Summary:\n{summary}",
            n = factorization_report.cycles.len(),
        );
    }

    let lowered = time_phase!(timings, "lower_chunk_total", {
        lower_chunk(LowerChunkInputs {
            artifact,
            artifact_indexes,
            runtime_ast,
            header_lines: &header_lines,
            entry_file: &target_file,
            chunk_id,
            source_path: &source_path,
            declarations: &declarations,
            declaration_by_name: &declaration_by_name,
            module_plans: &module_plans,
            binding_assignment: &binding_assignment,
            chunk_top_level_mark,
            anonymous_ordinal_assignment: &anonymous_ordinal_assignment,
            factorization: &factorization,
            chunk_renames: &chunk_renames_map,
            runtime_import_facts: &runtime_import_facts,
            pre_existing_entry_exports: &pre_existing_entry_exports,
            pre_existing_public_export_names: &pre_existing_public_export_names,
        })
    })?;
    let LoweredChunk {
        files,
        file_records,
        applied,
        timings: lower_timings,
    } = lowered;
    timings.extend_prefixed("lower", lower_timings);

    let final_modules = time_phase!(timings, "build_final_module_report", {
        module_plans
            .iter()
            .map(|plan| {
                let mut sorted: Vec<(&String, &String)> = plan.bindings.iter().collect();
                sorted.sort_by(|a, b| a.0.cmp(b.0));
                let binding_names: Vec<String> = sorted.iter().map(|(k, _)| (*k).clone()).collect();
                let member_names: Vec<String> = sorted.iter().map(|(_, v)| (*v).clone()).collect();
                let binding_ids: Vec<Id> = binding_names
                    .iter()
                    .map(|name| top_level_id(name, chunk_top_level_mark))
                    .collect();
                let owner_ids = factorization
                    .analysis
                    .owner_report_ids_for_bindings(binding_ids.iter());
                FinalModuleContent {
                    binding_names,
                    file: plan.target_file.clone(),
                    id: plan.id.clone(),
                    member_names,
                    path: plan.target_path.clone(),
                    owner_ids,
                    residual: !plan.explicit,
                }
            })
            .collect::<Vec<_>>()
    });
    let directory_dependency_facts = time_phase!(timings, "build_directory_dependency_facts", {
        build_directory_dependency_facts(chunk_id, &factorization)
    });
    let validation = ChunkValidationSummary {
        status: "ok",
        linker_order: factorization_report.linker_order.clone(),
    };
    let timings = timings.into_durations(chunk_started.elapsed());
    let report = ChunkModulesReport {
        chunk_id: chunk_id.to_string(),
        counts: ChunkModulesCounts {
            applied: applied.len(),
            selected_owners: binding_assignment.len(),
        },
        final_module_contents: final_modules,
        requested_logical_modules: requests
            .iter()
            .map(|request| RequestedLogicalModule {
                id: request.id.clone(),
                target_path: request.target_path.clone(),
                residual: request.residual,
            })
            .collect(),
        redundant_purity_hints,
        timings,
    };
    Ok(MaterializedLogicalChunk {
        chunk_id: chunk_id_interned,
        unmatched_spec_claims,
        target_file,
        source_path,
        files,
        file_records,
        applied,
        directory_dependency_facts,
        validation,
        report,
    })
}

fn apply_member_hints(
    hints: &mut AnalysisHints,
    binding_name: &str,
    purity: MemberPurity,
    pure_members: &[String],
    effect: MemberEffect,
) {
    if purity == MemberPurity::Pure {
        hints.declared_pure.insert(binding_name.to_string());
    }
    if purity == MemberPurity::PureNew {
        hints.declared_pure_new.insert(binding_name.to_string());
    }
    if !pure_members.is_empty() {
        hints
            .declared_pure_members
            .entry(binding_name.to_string())
            .or_default()
            .extend(pure_members.iter().cloned());
    }
    if let Some(effect) = known_effect_from_member_effect(effect) {
        hints.known_effects.insert(binding_name.to_string(), effect);
    }
}

fn build_directory_dependency_facts(
    chunk_id: &str,
    factorization: &ChunkFactorization,
) -> Vec<DirectoryDependencyFact> {
    let mut facts = Vec::new();
    for edge in factorization.analysis.owner_graph.iter_edges() {
        let source_module = factorization.partition.of(edge.from);
        let target_module = factorization.partition.of(edge.to);
        if source_module == target_module {
            continue;
        }
        let Some(source_file) = module_output_file(chunk_id, factorization, source_module) else {
            continue;
        };
        let Some(target_file) = module_output_file(chunk_id, factorization, target_module) else {
            continue;
        };
        let symbol = edge.reason.binding().map(|id| {
            format!(
                "{}#{}",
                target_file,
                factorization.analysis.export_name_for(id)
            )
        });
        facts.push(DirectoryDependencyFact {
            source_file,
            target_file,
            edge_kind: edge.reason.kind(),
            symbol,
        });
    }
    facts.sort_by(|left, right| {
        left.source_file
            .cmp(&right.source_file)
            .then_with(|| left.target_file.cmp(&right.target_file))
            .then_with(|| left.edge_kind.cmp(&right.edge_kind))
            .then_with(|| left.symbol.cmp(&right.symbol))
    });
    facts
}

fn module_output_file(
    chunk_id: &str,
    factorization: &ChunkFactorization,
    module: ModuleId,
) -> Option<String> {
    let ModuleId(LogicalModuleIndex(idx)) = module;
    factorization
        .analysis
        .logical_modules
        .get(idx)
        .map(|logical| join_module_path(&[chunk_id, &logical.target_file]))
}
