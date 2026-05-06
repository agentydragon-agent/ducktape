use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::path::{Path, PathBuf};
use std::time::Instant;

use anyhow::{Context, Result, bail};
use serde::Serialize;
use swc_common::{DUMMY_SP, SyntaxContext};
use swc_ecma_ast::*;
use swc_ecma_visit::{Visit, VisitMut, VisitMutWith, VisitWith};

use artifact::{
    ArtifactCounts, ArtifactManifest, ArtifactSourceImportResolver, ChunkFileRecord,
    ChunkLogicalModulesSummary, ChunkMetadata, FileMetadata, FileRole, JsChunk, JsFile,
    JsPipelineArtifact, ModuleExtractionState, RootLogicalModulesSummary, SelectedModuleLowering,
    get_chunk_entry_path, join_module_path, manifest_relative_path, module_path_dirname,
    module_path_from_path, normalize_module_path, relative_module_path,
};
use js_ast::{ParsedJsModule, line_range_for_span, set_str_value, str_value};
use schedule_validator::{
    BindingKind, BindingName, LogicalModule as ScheduleLogicalModule, LogicalModuleIndex, ModuleId,
    Schedule, analyze_chunk_with_source_locations, render_cycle_summary,
};
use spec::{BindingSourceKind, ChunkRenames, LogicalModule, MemberPurity, ResidualModule};

const LOWERING_FILE_PRAGMA: &str =
    "// @ducktape-generated kind=lowerer-helper stage=selected_module_lowering ignore=detectors";
const LOWERING_GENERATOR_HEADER: &str = "// @ducktape-generator selected_module_lowering";

#[derive(Debug, Clone, Serialize)]
pub struct LogicalModuleManifest {
    pub chunks: Vec<LogicalChunkReport>,
    pub counts: LogicalModuleCounts,
    pub duration_ms: f64,
    pub report_out_dir: Option<String>,
}

#[derive(Debug, Clone, Serialize)]
pub struct LogicalModuleCounts {
    pub applied: usize,
    pub final_modules: usize,
    pub explicit_logical_modules: usize,
    pub residual_logical_modules: usize,
}

#[derive(Debug, Clone, Serialize)]
pub struct LogicalChunkReport {
    pub chunk_id: String,
    pub counts: LogicalChunkCounts,
    pub final_module_contents: Vec<FinalModuleContent>,
    pub requested_logical_modules: Vec<RequestedLogicalModule>,
    pub timings_ms: BTreeMap<String, f64>,
}

#[derive(Debug, Clone, Serialize)]
pub struct LogicalChunkCounts {
    pub applied: usize,
    pub explicit_logical_modules: usize,
    pub final_modules: usize,
    pub residual_logical_modules: usize,
    pub selected_owners: usize,
}

#[derive(Debug, Clone, Serialize)]
pub struct FinalModuleContent {
    pub binding_names: Vec<String>,
    pub file: String,
    pub id: String,
    pub member_names: Vec<String>,
    pub path: String,
    pub owner_ids: Vec<String>,
    pub residual: bool,
}

#[derive(Debug, Clone, Serialize)]
pub struct RequestedLogicalModule {
    pub id: String,
    pub target_path: String,
    pub residual: bool,
}

#[derive(Debug, Clone)]
pub struct MaterializeLogicalModulesOptions {
    pub chunk_ids: Vec<String>,
    pub file: Option<String>,
    pub prune_other_chunks: bool,
    pub force: bool,
    pub report_out_dir: Option<PathBuf>,
    pub report_summary_path: Option<PathBuf>,
    pub target_dir: String,
}

#[derive(Debug, Clone)]
struct LogicalRequest {
    id: String,
    target_path: String,
    residual: bool,
    members: Vec<MemberRequest>,
}

#[derive(Debug, Clone)]
struct MemberRequest {
    binding: String,
    export_name: String,
    /// When `true`, the member's source is an import specifier in the
    /// source chunk (not a top-level decl). The materializer looks up
    /// the import statement by `binding` in the chunk body and rewrites
    /// it to a re-import in the destination module.
    is_import_specifier: bool,
    /// Spec-level purity annotation. `Pure` asserts that calls to the
    /// bound function have no observable side effects — the validator
    /// trusts the annotation and drops S edges for `<binding>(...)`
    /// call sites. `Default` means "not annotated, fall back to
    /// inferred classification". An author-trust contract; see
    /// AGENTS.md "Declared purity" and DESIGN.md A9.
    purity: MemberPurity,
}

#[derive(Debug, Clone)]
struct TopLevelDecl {
    ordinal: usize,
    names: Vec<String>,
    exported: bool,
}

#[derive(Debug, Clone)]
struct ModulePlan {
    id: String,
    target_file: String,
    /// Logical module path the spec asked for (e.g. `"ai/mcp/foo"`).
    /// Distinct from `target_file`, which is the chunk-relative
    /// emitted file path (e.g. `"modules/foo.js"`).
    target_path: String,
    explicit: bool,
    /// Local-name → public-export-name for every owned binding this
    /// plan claims (i.e. members whose `selector.binding.kind` is
    /// _not_ `ImportSpecifier`). ImportSpecifier-bound members live
    /// in `Schedule.bindings` as `BindingKind::Imported` and their
    /// emit is driven from there.
    bindings: BTreeMap<String, String>,
}

pub fn materialize_logical_modules(
    artifact: &mut JsPipelineArtifact,
    logical_modules: &BTreeMap<String, BTreeMap<String, LogicalModule>>,
    residual_modules: &BTreeMap<String, ResidualModule>,
    chunk_renames: &BTreeMap<String, ChunkRenames>,
    options: MaterializeLogicalModulesOptions,
) -> Result<LogicalModuleManifest> {
    if options.chunk_ids.is_empty() {
        bail!("materialize_logical_modules requires at least one chunk_id");
    }
    let started = Instant::now();
    let target_dir = normalize_optional_relative_dir(&options.target_dir)?;
    let mut selected_chunk_ids = Vec::new();
    let mut seen = BTreeSet::new();
    for chunk_id in &options.chunk_ids {
        let normalized = normalize_module_path(chunk_id)?;
        if seen.insert(normalized.clone()) {
            selected_chunk_ids.push(normalized);
        }
    }

    let mut report_out_dir = None;
    if let Some(dir) = &options.report_out_dir {
        prepare_output_dir(dir, options.force)?;
        report_out_dir = Some(dir.clone());
    }

    if options.prune_other_chunks {
        prune_artifact_to_chunk_ids(artifact, &selected_chunk_ids);
    }

    let mut reports = Vec::new();
    let mut applied = Vec::<SelectedModuleLowering>::new();
    for chunk_id in selected_chunk_ids {
        let chunk_started = Instant::now();
        let target_file = options
            .file
            .as_ref()
            .map(|file| normalize_module_path(file))
            .transpose()?
            .or_else(|| get_chunk_entry_path(artifact, &chunk_id))
            .with_context(|| {
                format!(
                    "materialize_logical_modules could not determine entry file for chunk: {chunk_id}"
                )
            })?;
        let runtime_file = artifact
            .chunks
            .get(&chunk_id)
            .and_then(|chunk| chunk.files.get(&target_file))
            .with_context(|| {
                format!("materialize_logical_modules missing entry file for chunk: {chunk_id}")
            })?;
        let runtime_ast = runtime_file.ast.as_ref().with_context(|| {
            format!("materialize_logical_modules missing entry AST for chunk: {chunk_id}")
        })?;
        let header_lines = runtime_file.header_lines.clone();
        let source_path = runtime_file
            .metadata
            .source_path
            .clone()
            .or_else(|| artifact.chunk_source_path(&chunk_id))
            .unwrap_or_else(|| format!("{chunk_id}.js"));
        let runtime_import_facts = collect_runtime_import_facts(&runtime_ast.module.body);
        let requests = logical_requests_for_chunk(
            logical_modules.get(&chunk_id),
            residual_modules.get(&chunk_id),
            chunk_renames.contains_key(&chunk_id),
            &chunk_id,
            &target_dir,
        )?;
        let mut explicit_requests = requests
            .iter()
            .filter(|request| !request.residual)
            .cloned()
            .collect::<Vec<_>>();
        let residual_request = requests.iter().find(|request| request.residual).cloned();

        let declarations = collect_top_level_declarations(&runtime_ast.module);
        let declaration_by_name = declarations
            .iter()
            .flat_map(|decl| decl.names.iter().map(|name| (name.clone(), decl.ordinal)))
            .collect::<BTreeMap<_, _>>();

        let mut binding_assignment = BTreeMap::<String, usize>::new();
        let mut module_plans = Vec::new();
        let mut bindings_catalogue = BTreeMap::<BindingName, BindingKind>::new();
        let mut imported_binding_resolver = ArtifactSourceImportResolutionCache::new(artifact);
        for (index, request) in explicit_requests.iter_mut().enumerate() {
            let mut bindings = BTreeMap::new();
            let dest_target_file = target_file_for_request(&target_dir, &request.target_path)?;
            let module_id = ModuleId::Logical(LogicalModuleIndex(index));
            for member in &request.members {
                if member.is_import_specifier {
                    // ImportSpecifier-bound: re-export of a source-chunk
                    // import. Accumulate into BindingKind::Imported so
                    // multiple modules can re-export the same binding
                    // under different public names.
                    let (imported_name, imported_from) = resolve_imported_binding(
                        &mut imported_binding_resolver,
                        &runtime_import_facts,
                        &chunk_id,
                        &target_file,
                        &member.binding,
                    )?;
                    let entry = bindings_catalogue
                        .entry(member.binding.clone())
                        .or_insert_with(|| BindingKind::Imported {
                            imported_name: imported_name.clone(),
                            imported_from: imported_from.clone(),
                            re_exported_by: BTreeMap::new(),
                        });
                    if let BindingKind::Imported { re_exported_by, .. } = entry {
                        re_exported_by.insert(module_id, member.export_name.clone());
                    }
                } else {
                    bindings.insert(member.binding.clone(), member.export_name.clone());
                }
            }
            for binding in bindings.keys() {
                if declaration_by_name.contains_key(binding) {
                    binding_assignment.insert(binding.clone(), index);
                    bindings_catalogue
                        .insert(binding.clone(), BindingKind::Owned { owner: module_id });
                }
            }
            module_plans.push(ModulePlan {
                id: request.id.clone(),
                target_file: dest_target_file,
                target_path: request.target_path.clone(),
                explicit: true,
                bindings,
            });
        }
        drop(imported_binding_resolver);

        if let Some(residual) = residual_request {
            let residual_index = module_plans.len();
            let residual_module_id = ModuleId::Logical(LogicalModuleIndex(residual_index));
            // Bindings staying in residual can still carry a public name. The
            // gaffer-side `.yaml.deferred` workflow routes its rename ops
            // through the residual op so that bindings deferred from peeled
            // modules don't revert to scrambled names while waiting to be
            // re-peeled. Source-name members map back to themselves.
            let residual_renames: BTreeMap<&str, &str> = residual
                .members
                .iter()
                .map(|m| (m.binding.as_str(), m.export_name.as_str()))
                .collect();
            let mut residual_bindings = BTreeMap::new();
            for decl in &declarations {
                for name in &decl.names {
                    if !binding_assignment.contains_key(name) {
                        binding_assignment.insert(name.clone(), residual_index);
                        let export_name = residual_renames
                            .get(name.as_str())
                            .map(|s| s.to_string())
                            .unwrap_or_else(|| name.clone());
                        residual_bindings.insert(name.clone(), export_name);
                        bindings_catalogue.insert(
                            name.clone(),
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
                    target_file: target_file_for_request(&target_dir, &residual.target_path)?,
                    target_path: residual.target_path.clone(),
                    explicit: false,
                    bindings: residual_bindings,
                });
            }
        }

        let chunk_renames_map = chunk_renames
            .get(&chunk_id)
            .map(collect_chunk_renames)
            .transpose()?
            .unwrap_or_default();

        // Run the schedule validator (see <DESIGN.md>). Computed here
        // (before `lower_chunk` mutates the artifact) to keep the
        // immutable borrow on `runtime_ast` simple. The report is
        // emitted as `<chunk_id>/schedule.json`; cycles abort the
        // pipeline.
        let schedule = {
            // Spec-declared pure bindings: every member with
            // `purity: "pure"`. The classifier short-circuits
            // `<binding>(...)` call sites to `Pure` regardless of
            // body content. Author-trust contract; see DESIGN.md
            // A9 + AGENTS.md "Declared purity".
            let declared_pure: BTreeSet<String> = explicit_requests
                .iter()
                .flat_map(|req| req.members.iter())
                .filter(|m| m.purity == MemberPurity::Pure)
                .map(|m| m.binding.clone())
                .collect();
            let analysis = analyze_chunk_with_source_locations(
                &runtime_ast.module,
                &declared_pure,
                Some(&source_path),
                |span| line_range_for_span(runtime_ast, span),
            );
            // Refuse chunks with top-level `await`. DESIGN.md
            // assumption A2 — the proof's reverse-DFS argument
            // doesn't apply to AsyncCycleRoot semantics, so the
            // realizability theorem doesn't extend. Rejecting here
            // turns the assumption into an enforced precondition.
            if let Some(ord) = analysis.top_level_await {
                anyhow::bail!(
                    "materialize_logical_modules: chunk {chunk_id} has top-level `await` \
                     at statement #{ordinal} (TLA); the debundler's realizability theorem \
                     does not cover async modules (DESIGN.md A2). Wrap the awaited code \
                     in an async function or rewrite as a synchronous initialization.",
                    ordinal = ord.0,
                );
            }
            let logical_modules: Vec<ScheduleLogicalModule> = module_plans
                .iter()
                .map(|plan| ScheduleLogicalModule {
                    id: plan.id.clone(),
                    target_file: plan.target_file.clone(),
                    residual: !plan.explicit,
                    rename_map: plan.bindings.clone(),
                })
                .collect();
            Schedule::build(
                chunk_id.clone(),
                analysis.facts,
                bindings_catalogue,
                logical_modules,
                chunk_renames_map.clone(),
            )
        };
        let schedule_report = schedule.validate();
        if let Some(report_out_dir) = &report_out_dir {
            write_chunk_report_json(report_out_dir, &chunk_id, "schedule.json", &schedule_report)?;
            write_chunk_report_json(
                report_out_dir,
                &chunk_id,
                "owner_graph.json",
                &schedule.owner_graph_report(),
            )?;
        }

        // Hard gate: a cyclic spec is unrealizable; refuse to emit
        // instead of producing a runtime-broken bundle. The full
        // cycle evidence and owner graph are written as side-output
        // JSON for downstream tooling; stderr gets a compact summary
        // so the bail message stays under the typical CI log-tail
        // threshold (Bazel truncates at ~1 MiB by default).
        if !schedule_report.cycles.is_empty() {
            if let Some(report_out_dir) = &report_out_dir {
                write_chunk_report_json(
                    report_out_dir,
                    &chunk_id,
                    "cycles.json",
                    &schedule_report.cycles,
                )?;
            }
            let summary = render_cycle_summary(&schedule_report.cycles);
            bail!(
                "materialize_logical_modules: chunk {chunk_id} has {} cycle(s) in the imports + side-effect module dep graph; spec is unrealizable. Resolve by colocating cyclically-coupled bindings or moving the constraining owner endpoints. Full cycle evidence written to <reports>/{chunk_id}/cycles.json; owner graph written to <reports>/{chunk_id}/owner_graph.json. Summary:\n{summary}",
                schedule_report.cycles.len(),
            );
        }

        let lowered = lower_chunk(LowerChunkInputs {
            artifact,
            runtime_ast,
            header_lines: &header_lines,
            entry_file: &target_file,
            chunk_id: &chunk_id,
            source_path: &source_path,
            declarations: &declarations,
            declaration_by_name: &declaration_by_name,
            module_plans: &module_plans,
            binding_assignment: &binding_assignment,
            schedule: &schedule,
            chunk_renames: &chunk_renames_map,
            runtime_import_facts: &runtime_import_facts,
        })?;
        let mut files = BTreeMap::new();
        for file in lowered.files {
            files.insert(file.path.clone(), file);
        }
        let module_extraction_state = ModuleExtractionState {
            runtime_file: target_file.clone(),
            target_dir: target_dir.clone(),
        };
        artifact.chunks.insert(
            chunk_id.clone(),
            JsChunk {
                entry_file: target_file.clone(),
                files,
                metadata: ChunkMetadata {
                    source_path: Some(source_path.clone()),
                    module_extraction_state: Some(module_extraction_state),
                },
            },
        );
        if !artifact.chunk_order.contains(&chunk_id) {
            artifact.chunk_order.push(chunk_id.clone());
        }

        let selected_lowerings = lowered.applied.clone();
        if let Some(manifest) = artifact.chunk_manifests.get_mut(&chunk_id) {
            manifest.entry_file = target_file.clone();
            manifest.files = lowered
                .file_records
                .iter()
                .map(|(file, role)| ChunkFileRecord {
                    file: file.clone(),
                    role: *role,
                })
                .collect();
            manifest.logical_modules = Some(ChunkLogicalModulesSummary {
                count: module_plans.len(),
                module_ids: module_plans.iter().map(|plan| plan.id.clone()).collect(),
                target_dir: target_dir.clone(),
            });
            manifest.selected_module_lowerings = Some(selected_lowerings.clone());
        }

        let final_modules = module_plans
            .iter()
            .map(|plan| FinalModuleContent {
                binding_names: plan.bindings.keys().cloned().collect(),
                file: plan.target_file.clone(),
                id: plan.id.clone(),
                member_names: plan.bindings.values().cloned().collect(),
                path: plan.target_path.clone(),
                owner_ids: schedule
                    .owner_report_ids_for_bindings(plan.bindings.keys().map(String::as_str)),
                residual: !plan.explicit,
            })
            .collect::<Vec<_>>();
        let report = LogicalChunkReport {
            chunk_id: chunk_id.clone(),
            counts: LogicalChunkCounts {
                applied: selected_lowerings.len(),
                explicit_logical_modules: module_plans.iter().filter(|plan| plan.explicit).count(),
                final_modules: module_plans.len(),
                residual_logical_modules: module_plans.iter().filter(|plan| !plan.explicit).count(),
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
            timings_ms: BTreeMap::from([(
                "total".to_string(),
                chunk_started.elapsed().as_secs_f64() * 1000.0,
            )]),
        };
        if let Some(report_out_dir) = &report_out_dir {
            write_chunk_report_json(report_out_dir, &chunk_id, "logical_modules.json", &report)?;
        }
        applied.extend(selected_lowerings);
        reports.push(report);
    }

    update_root_manifest(artifact, &reports, &applied);
    let manifest = LogicalModuleManifest {
        counts: LogicalModuleCounts {
            applied: applied.len(),
            final_modules: reports
                .iter()
                .map(|report| report.counts.final_modules)
                .sum(),
            explicit_logical_modules: reports
                .iter()
                .map(|report| report.counts.explicit_logical_modules)
                .sum(),
            residual_logical_modules: reports
                .iter()
                .map(|report| report.counts.residual_logical_modules)
                .sum(),
        },
        chunks: reports,
        duration_ms: started.elapsed().as_secs_f64() * 1000.0,
        report_out_dir: report_out_dir.as_ref().map(|path| {
            options.report_summary_path.as_ref().map_or_else(
                || module_path_from_path(path),
                |s| manifest_relative_path(s, path),
            )
        }),
    };

    if let Some(summary_path) = options.report_summary_path {
        if let Some(parent) = summary_path.parent() {
            fs::create_dir_all(parent)?;
        }
        fs::write(
            summary_path,
            serde_json::to_string_pretty(&manifest)? + "\n",
        )?;
    }
    Ok(manifest)
}

struct LoweredChunk {
    files: Vec<JsFile>,
    file_records: Vec<(String, FileRole)>,
    applied: Vec<SelectedModuleLowering>,
}

struct LowerChunkInputs<'a> {
    artifact: &'a JsPipelineArtifact,
    runtime_ast: &'a ParsedJsModule,
    header_lines: &'a [String],
    entry_file: &'a str,
    chunk_id: &'a str,
    source_path: &'a str,
    declarations: &'a [TopLevelDecl],
    declaration_by_name: &'a BTreeMap<String, usize>,
    module_plans: &'a [ModulePlan],
    binding_assignment: &'a BTreeMap<String, usize>,
    schedule: &'a Schedule,
    runtime_import_facts: &'a RuntimeImportFacts,
    /// In-place renames from `TransformSpec::chunk_renames`. Applied
    /// to bindings staying in entry's body — i.e. those *not* in
    /// `binding_assignment`. Bindings claimed by a logical module
    /// take their rename from the module plan; entries here for
    /// those bindings are silently dropped.
    chunk_renames: &'a BTreeMap<String, String>,
}

#[derive(Debug, Default)]
struct ModuleBodyFacts {
    imported_locals: BTreeSet<String>,
    provided_locals: BTreeSet<String>,
    referenced_idents: BTreeSet<String>,
}

struct RuntimeImportFacts {
    imports: BTreeMap<String, RuntimeImportInfo>,
}

#[derive(Debug)]
struct ImportedReexport {
    local: String,
    imported_name: String,
    imported_from: String,
    public_name: String,
}

#[derive(Default)]
struct ModuleReferenceNeeds<'a> {
    cross_module_imports_by_provider: BTreeMap<usize, BTreeMap<String, String>>,
    residual_entry_imports: BTreeMap<String, String>,
    missing_residual_exports: BTreeSet<String>,
    runtime_reimports: BTreeMap<String, &'a RuntimeImportInfo>,
}

type SourceImportResolutionKey = (String, String, String);
type SourceImportResolution = Option<(String, String, String)>;

struct ArtifactSourceImportResolutionCache<'a> {
    artifact: &'a JsPipelineArtifact,
    resolutions: BTreeMap<SourceImportResolutionKey, SourceImportResolution>,
    resolver: Option<ArtifactSourceImportResolver<'a>>,
}

impl<'a> ArtifactSourceImportResolutionCache<'a> {
    fn new(artifact: &'a JsPipelineArtifact) -> Self {
        Self {
            artifact,
            resolutions: BTreeMap::new(),
            resolver: None,
        }
    }

    fn resolve(
        &mut self,
        source: &str,
        caller_chunk_id: &str,
        caller_file: &str,
    ) -> Result<SourceImportResolution> {
        if source.is_empty() || (!source.starts_with('.') && !source.starts_with('/')) {
            return Ok(None);
        }
        let key = (
            source.to_string(),
            caller_chunk_id.to_string(),
            caller_file.to_string(),
        );
        if let Some(resolved) = self.resolutions.get(&key) {
            return Ok(resolved.clone());
        }
        if self.resolver.is_none() {
            self.resolver = Some(self.artifact.source_import_resolver()?);
        }
        let resolved = self
            .resolver
            .as_ref()
            .expect("resolver initialized")
            .resolve(source, caller_chunk_id, caller_file)?;
        self.resolutions.insert(key, resolved.clone());
        Ok(resolved)
    }
}

fn lower_chunk(inputs: LowerChunkInputs<'_>) -> Result<LoweredChunk> {
    let LowerChunkInputs {
        artifact,
        runtime_ast,
        header_lines,
        entry_file,
        chunk_id,
        source_path,
        declarations,
        declaration_by_name,
        module_plans,
        binding_assignment,
        schedule,
        runtime_import_facts,
        chunk_renames,
    } = inputs;
    let mut selected_ordinals = BTreeSet::new();
    for decl in declarations {
        if decl
            .names
            .iter()
            .any(|name| binding_assignment.contains_key(name))
        {
            selected_ordinals.insert(decl.ordinal);
        }
    }

    let mut selected_by_module = vec![Vec::<ModuleItem>::new(); module_plans.len()];
    let mut selected_exports_by_module =
        vec![Option::<BTreeMap<String, String>>::None; module_plans.len()];
    for (module_index, plan) in module_plans.iter().enumerate() {
        if plan.bindings.is_empty() {
            continue;
        }
        // Drop bindings that don't exist anywhere (no entry in
        // `binding_assignment`). Without this, a stale spec entry
        // for a binding that is not a top-level decl in the chunk
        // would emit `export { <renamed> }` with no backing decl
        // and Node bails at module load with `SyntaxError: Export
        // '<renamed>' is not defined in module`.
        let exports: BTreeMap<String, String> = plan
            .bindings
            .iter()
            .filter(|(name, _)| binding_assignment.contains_key(*name))
            .map(|(k, v)| (k.clone(), v.clone()))
            .collect();
        if !exports.is_empty() {
            selected_exports_by_module[module_index] = Some(exports);
        }
    }

    let mut entry_body = Vec::new();
    let import_insert_index = runtime_ast
        .module
        .body
        .iter()
        .take_while(|item| matches!(item, ModuleItem::ModuleDecl(ModuleDecl::Import(_))))
        .count();
    for (ordinal, item) in runtime_ast.module.body.iter().enumerate() {
        if !selected_ordinals.contains(&ordinal) {
            entry_body.push(item.clone());
            continue;
        }
        let mut remaining =
            remaining_item_after_selection(item, binding_assignment, &mut selected_by_module)?;
        entry_body.append(&mut remaining);
    }
    // Two passes: build entry imports in plan order (so the
    // first plan to claim a binding wins disambiguation), then
    // sort the resulting imports by `linker_order` so ECMA-262's
    // depth-first link traversal evaluates dependencies first.
    // Plan-order disambiguation + linker-order placement keeps
    // the import-collision contract while satisfying Lemma 2's
    // emit-side constraint. See DESIGN.md "Module dep graphs"
    // and "Lemma 2".
    let mut entry_imports: Vec<(usize, ModuleItem)> = Vec::new();
    let mut occupied = collect_occupied_local_names(&entry_body);
    let mut body_renames = BTreeMap::<String, String>::new();
    // Seed body_renames with `chunk_renames` entries for bindings
    // staying in entry's body (not claimed by any logical module).
    // Bindings owned by a logical module take their rename from the
    // module plan via the disambiguate-imports pass below;
    // chunk_renames entries for those bindings are silently
    // dropped here (the logical-module rename wins).
    //
    // Each accepted target name is reserved in `occupied` before the
    // import-disambiguation pass runs, so a later cross-module
    // import doesn't mint a fresh local that collides with one of
    // the chunk_renames' targets. Conflicting targets (target name
    // already taken by a body local that isn't being renamed away,
    // or by another chunk_renames entry, or invalid as an
    // identifier) bail rather than producing invalid JS silently.
    let mut renamed_away = BTreeSet::<String>::new();
    for binding in chunk_renames.keys() {
        if binding_assignment.contains_key(binding) {
            continue;
        }
        renamed_away.insert(binding.clone());
    }
    for (binding, export_name) in chunk_renames {
        if binding_assignment.contains_key(binding) {
            continue;
        }
        if !is_valid_js_identifier(export_name) {
            bail!(
                "chunk_renames target {export_name} for binding {binding} is not a valid JS identifier",
            );
        }
        if export_name != binding {
            // A body local that's also being renamed away vacates
            // its slot in `occupied` — it's safe to reuse. Anything
            // else still in `occupied` would collide.
            let target_already_taken =
                occupied.contains(export_name) && !renamed_away.contains(export_name);
            if target_already_taken {
                bail!(
                    "chunk_renames target {export_name} for binding {binding} collides with an existing top-level local",
                );
            }
        }
        if !occupied.insert(export_name.clone()) && export_name != binding {
            // `occupied.insert` returns false if already present;
            // for the rename-to-self case (export_name == binding)
            // that's expected. For any other case the target was
            // already chosen by a previous chunk_renames entry —
            // duplicate target.
            bail!(
                "chunk_renames target {export_name} for binding {binding} duplicates an earlier rename target",
            );
        }
        body_renames.insert(binding.clone(), export_name.clone());
    }
    for (module_index, plan) in module_plans.iter().enumerate() {
        if plan.bindings.is_empty() {
            continue;
        }
        // Drop bindings that don't exist anywhere (no entry in
        // `binding_assignment`). Bindings owned by another plan stay
        // in the import — they're a separate "two plans claim the
        // same binding" disambiguation case handled by
        // `disambiguate_import_locals`.
        let live_bindings: BTreeMap<String, String> = plan
            .bindings
            .iter()
            .filter(|(name, _)| binding_assignment.contains_key(*name))
            .map(|(k, v)| (k.clone(), v.clone()))
            .collect();
        if live_bindings.is_empty() {
            continue;
        }
        let mut emit_renames = BTreeMap::<String, String>::new();
        let resolved = disambiguate_import_locals(&live_bindings, &mut occupied, &mut emit_renames);
        // A rename only propagates to consumer-body references when the
        // moved decl actually belongs to this plan. Plans that listed a
        // binding without owning the decl emit a dangling import; the
        // body refs continue to resolve to whichever binding owned the
        // original local name.
        for (local, fresh) in emit_renames {
            if binding_assignment.get(&local).copied() == Some(module_index) {
                body_renames.insert(local, fresh);
            }
        }
        entry_imports.push((
            module_index,
            import_decl_for_plan(entry_file, &plan.target_file, &resolved),
        ));
    }
    // Sort the (plan-order-disambiguated) imports by linker_order
    // so the first import in the entry source corresponds to the
    // earliest-in-L provider. Stable sort preserves plan-order for
    // ties (e.g. when two providers have no dep-graph relation).
    entry_imports.sort_by_key(|(idx, _)| {
        schedule
            .linker_position(ModuleId::Logical(LogicalModuleIndex(*idx)))
            .unwrap_or(usize::MAX)
    });
    let entry_imports: Vec<ModuleItem> = entry_imports.into_iter().map(|(_, it)| it).collect();
    let entry_binding_renames = body_renames.clone();
    if !body_renames.is_empty() {
        // Re-exports `export { local }` (without `from`) collapse `local`
        // and the public exported name into a single ident. Renaming the
        // orig would also rename the public name, breaking downstream
        // consumers — so rewrite them to `export { fresh as local }`
        // before the generic renamer visits the rest.
        for item in entry_body.iter_mut() {
            preserve_export_specifier_names(item, &body_renames);
        }
        let mut renamer = IdentifierRenamer {
            renames: &body_renames,
        };
        for item in entry_body.iter_mut() {
            item.visit_mut_with(&mut renamer);
        }
    }
    if !entry_imports.is_empty() {
        let tail = entry_body.split_off(import_insert_index);
        entry_body.extend(entry_imports);
        entry_body.extend(tail);
    }
    for export in entry_exports_for_moved_bindings(declarations, binding_assignment) {
        entry_body.push(export);
    }
    trim_dead_named_specifiers(&mut entry_body, &schedule.bindings);
    let entry_exports_by_original_local =
        collect_entry_exports_by_original_local(&entry_body, &entry_binding_renames);
    let imported_reexports_by_module =
        collect_imported_reexports_by_module(schedule, module_plans.len());
    let mut source_import_cache = ArtifactSourceImportResolutionCache::new(artifact);

    let mut files = vec![JsFile {
        path: entry_file.to_string(),
        content: None,
        ast: Some(ParsedJsModule {
            cm: runtime_ast.cm.clone(),
            module: Module {
                span: DUMMY_SP,
                body: entry_body,
                shebang: None,
            },
        }),
        header_lines: header_lines.to_vec(),
        metadata: FileMetadata {
            chunk_id: Some(chunk_id.to_string()),
            chunk_file: Some(entry_file.to_string()),
            role: Some(FileRole::Entry),
            source_path: Some(source_path.to_string()),
            ..Default::default()
        },
    }];
    let mut file_records = vec![(entry_file.to_string(), FileRole::Entry)];
    let mut applied = Vec::new();

    for (index, plan) in module_plans.iter().enumerate() {
        let mut body = std::mem::take(&mut selected_by_module[index]);
        let local_renames = naturalize_module_body(&mut body, plan);
        let body_facts = collect_module_body_facts(&body);
        let ModuleReferenceNeeds {
            cross_module_imports_by_provider,
            residual_entry_imports,
            missing_residual_exports,
            runtime_reimports,
        } = plan_module_reference_needs(
            index,
            &body_facts,
            schedule,
            declaration_by_name,
            binding_assignment,
            &entry_exports_by_original_local,
            runtime_import_facts,
        );
        let mut module_imports = cross_module_imports_for_plan(
            &plan.target_file,
            cross_module_imports_by_provider,
            schedule,
        );
        let mut residual_entry_imports = residual_entry_imports_for_moved_body(
            &plan.id,
            entry_file,
            &plan.target_file,
            residual_entry_imports,
            missing_residual_exports,
        )?;
        // Re-import any source-chunk import-specifier-bound locals that
        // moved code in `body` references but no top-level decl
        // satisfies (e.g. `const { decode } = gge;` where `gge` was an
        // ImportSpecifier in the source chunk's runtime body). Without
        // this, the moved code references a free variable and Node
        // throws `ReferenceError: gge is not defined` at runtime.
        let mut runtime_reimports = source_chunk_imports_for_moved_body(
            &mut source_import_cache,
            chunk_id,
            entry_file,
            &plan.target_file,
            runtime_reimports,
        )?;
        module_imports.append(&mut residual_entry_imports);
        module_imports.append(&mut runtime_reimports);
        module_imports.append(&mut body);
        body = module_imports;
        rewrite_runtime_sources_for_target(&mut body, &plan.target_file);
        // ImportSpecifier-bound members (`BindingKind::Imported` in
        // `schedule.bindings`): for each `Imported` binding whose
        // `re_exported_by` map names this module, emit a re-import
        // (using the local name as the alias) plus mirror the
        // public-name export. Per-destination relative paths are
        // computed here so multiple modules at different output
        // depths each get a correctly-relativised path.
        let mut import_member_exports = BTreeMap::<String, String>::new();
        let import_count = body
            .iter()
            .take_while(|item| matches!(item, ModuleItem::ModuleDecl(ModuleDecl::Import(_))))
            .count();
        // `imported_from` on `BindingKind::Imported` is output-tree-
        // rooted absolute; `plan.target_file` is chunk-rooted. Lift
        // the destination to the same coordinate system before
        // computing the relative path.
        let dest_abs = join_module_path(&[chunk_id, &plan.target_file]);
        for (offset, reexport) in imported_reexports_by_module[index].iter().enumerate() {
            let src = relative_source(&dest_abs, &reexport.imported_from);
            body.insert(
                import_count + offset,
                imported_binding_import_decl(&reexport.local, &reexport.imported_name, &src),
            );
            import_member_exports.insert(reexport.local.clone(), reexport.public_name.clone());
        }
        if let Some(exports) = &selected_exports_by_module[index] {
            let mut exports = final_module_exports(exports, &local_renames);
            exports.extend(
                import_member_exports
                    .iter()
                    .map(|(k, v)| (k.clone(), v.clone())),
            );
            body.push(export_named_for_bindings(&exports));
        } else if !import_member_exports.is_empty() {
            body.push(export_named_for_bindings(&import_member_exports));
        }
        let binding_names = plan.bindings.keys().cloned().collect::<Vec<_>>();
        let owner_ids =
            schedule.owner_report_ids_for_bindings(plan.bindings.keys().map(String::as_str));
        let header = vec![
            LOWERING_FILE_PRAGMA.to_string(),
            LOWERING_GENERATOR_HEADER.to_string(),
            format!(
                "// Selected-module lowered region; original owner ids: {}.",
                owner_ids.join(", ")
            ),
            format!(
                "// Selected-module lowered region; source bindings: {}.",
                binding_names.join(", ")
            ),
        ];
        files.push(JsFile {
            path: plan.target_file.clone(),
            content: None,
            ast: Some(ParsedJsModule {
                cm: runtime_ast.cm.clone(),
                module: Module {
                    span: DUMMY_SP,
                    body,
                    shebang: None,
                },
            }),
            header_lines: header,
            metadata: FileMetadata {
                chunk_id: Some(chunk_id.to_string()),
                chunk_file: Some(plan.target_file.clone()),
                role: Some(FileRole::Module),
                source_path: Some(source_path.to_string()),
                generated_stage: Some("selected_module_lowering".to_string()),
            },
        });
        file_records.push((plan.target_file.clone(), FileRole::Module));
        applied.push(SelectedModuleLowering {
            binding_names,
            chunk_id: chunk_id.to_string(),
            exported_names: plan.bindings.values().cloned().collect(),
            file: entry_file.to_string(),
            id: plan.id.clone(),
            owner_ids,
            residual: !plan.explicit,
            target_file: plan.target_file.clone(),
            target_path: plan.target_path.clone(),
        });
    }

    Ok(LoweredChunk {
        files,
        file_records,
        applied,
    })
}

fn logical_requests_for_chunk(
    chunk_logical_modules: Option<&BTreeMap<String, LogicalModule>>,
    chunk_residual: Option<&ResidualModule>,
    chunk_renames_present: bool,
    chunk_id: &str,
    target_dir: &str,
) -> Result<Vec<LogicalRequest>> {
    let mut requests = Vec::new();
    if let Some(by_target_path) = chunk_logical_modules {
        for (target_path, module) in by_target_path {
            let id = format!("{chunk_id}::{target_path}");
            let members = build_members(&module.members);
            reject_duplicate_export_names("logical_module", &id, &members)?;
            reject_duplicate_member_bindings("logical_module", &id, &members)?;
            requests.push(LogicalRequest {
                id,
                target_path: target_path.clone(),
                residual: false,
                members,
            });
        }
    }
    if let Some(residual) = chunk_residual {
        let id = format!("{chunk_id}::residual");
        let target_path = residual
            .target
            .clone()
            .unwrap_or_else(|| "residual/unhandled".to_string());
        let members = build_members(&residual.members);
        reject_duplicate_export_names("residual_module", &id, &members)?;
        reject_duplicate_member_bindings("residual_module", &id, &members)?;
        requests.push(LogicalRequest {
            id,
            target_path,
            residual: true,
            members,
        });
    }
    // Fallback: when the spec is silent about this chunk (no
    // `logical_modules` or `residual_modules` entry), inject a
    // memberless residual so the materializer has at least one
    // module to point unowned decls at. Skipped when the spec has
    // any `chunk_renames` for the chunk — that signals the spec
    // wants bindings to stay in `ResidualEntry`-land (no
    // `Logical(R)` module, no separate residual file emitted), with
    // renames applied in-place by the lowerer.
    if requests.is_empty() && !chunk_renames_present {
        requests.push(LogicalRequest {
            id: format!("{chunk_id}::residual"),
            target_path: join_module_path(&[target_dir, "unhandled"]),
            residual: true,
            members: Vec::new(),
        });
    }
    Ok(requests)
}

/// Collect a `ChunkRenames` block into a `binding_name -> export_name`
/// map. Bindings that appear more than once across `members` fail
/// fast — silently last-write-wins on a binding rename is the same
/// hazard as duplicate logical-module member bindings.
/// True iff `s` is a valid JavaScript identifier — start char is
/// `[A-Za-z_$]` and rest is `[A-Za-z0-9_$]`. Reserved words are not
/// rejected (a target named e.g. `class` or `let` would still trip
/// at parse time downstream, but that's a louder failure than this
/// shallow check would catch). The intent is to filter typos
/// (`with-dash`, `0digit`, empty string) from spec authors.
fn is_valid_js_identifier(s: &str) -> bool {
    let mut chars = s.chars();
    let first = match chars.next() {
        Some(c) => c,
        None => return false,
    };
    if !(first.is_ascii_alphabetic() || first == '_' || first == '$') {
        return false;
    }
    chars.all(|c| c.is_ascii_alphanumeric() || c == '_' || c == '$')
}

fn collect_chunk_renames(chunk_renames: &ChunkRenames) -> Result<BTreeMap<String, String>> {
    let mut renames = BTreeMap::<String, String>::new();
    let id = chunk_renames.id.as_deref().unwrap_or("chunk_renames");
    for member in &chunk_renames.members {
        let binding = member.selector.binding.name.clone();
        let export_name = member.name.clone().unwrap_or_else(|| binding.clone());
        if let Some(existing) = renames.get(&binding) {
            if existing != &export_name {
                bail!(
                    "chunk_renames {id}: binding {binding} already renamed to \
                     {existing}; refusing to overwrite with {export_name}"
                );
            }
        } else {
            renames.insert(binding, export_name);
        }
    }
    Ok(renames)
}

fn build_members(members: &[spec::Member]) -> Vec<MemberRequest> {
    members
        .iter()
        .map(|m| {
            let binding = m.selector.binding.name.clone();
            let export_name = m.name.clone().unwrap_or_else(|| binding.clone());
            MemberRequest {
                is_import_specifier: matches!(
                    m.selector.binding.kind,
                    Some(BindingSourceKind::ImportSpecifier)
                ),
                binding,
                export_name,
                purity: m.purity,
            }
        })
        .collect()
}

fn collect_top_level_declarations(module: &Module) -> Vec<TopLevelDecl> {
    let mut out = Vec::new();
    for (ordinal, item) in module.body.iter().enumerate() {
        let (names, exported) = top_level_declaration_names(item);
        if names.is_empty() {
            continue;
        }
        out.push(TopLevelDecl {
            ordinal,
            names,
            exported,
        });
    }
    out
}

fn top_level_declaration_names(item: &ModuleItem) -> (Vec<String>, bool) {
    match item {
        ModuleItem::Stmt(Stmt::Decl(decl)) => (declaration_names(decl), false),
        ModuleItem::ModuleDecl(ModuleDecl::ExportDecl(export_decl)) => {
            (declaration_names(&export_decl.decl), true)
        }
        _ => (Vec::new(), false),
    }
}

fn declaration_names(decl: &Decl) -> Vec<String> {
    match decl {
        Decl::Fn(function) => vec![function.ident.sym.to_string()],
        Decl::Class(class) => vec![class.ident.sym.to_string()],
        Decl::Var(var) => var
            .decls
            .iter()
            .flat_map(|decl| binding_names(&decl.name))
            .collect(),
        _ => Vec::new(),
    }
}

fn binding_names(pattern: &Pat) -> Vec<String> {
    match pattern {
        Pat::Ident(ident) => vec![ident.id.sym.to_string()],
        Pat::Rest(rest) => binding_names(&rest.arg),
        Pat::Assign(assign) => binding_names(&assign.left),
        Pat::Array(array) => array
            .elems
            .iter()
            .flatten()
            .flat_map(binding_names)
            .collect(),
        Pat::Object(object) => object
            .props
            .iter()
            .flat_map(|prop| match prop {
                ObjectPatProp::KeyValue(key_value) => binding_names(&key_value.value),
                ObjectPatProp::Assign(assign) => vec![assign.key.id.sym.to_string()],
                ObjectPatProp::Rest(rest) => binding_names(&rest.arg),
            })
            .collect(),
        _ => Vec::new(),
    }
}

#[derive(Default)]
struct RefCollector {
    names: BTreeSet<String>,
    shadowed_scopes: Vec<BTreeSet<String>>,
}

impl Visit for RefCollector {
    fn visit_ident(&mut self, node: &Ident) {
        let name = node.sym.as_ref();
        if !self.is_shadowed(name) {
            self.names.insert(name.to_string());
        }
    }

    fn visit_binding_ident(&mut self, _node: &BindingIdent) {}

    fn visit_import_decl(&mut self, _node: &ImportDecl) {}

    fn visit_function(&mut self, node: &Function) {
        let shadowed = node
            .params
            .iter()
            .flat_map(|param| binding_names(&param.pat))
            .collect::<BTreeSet<_>>();
        self.with_shadowed_scope(shadowed, |collector| node.visit_children_with(collector));
    }

    fn visit_arrow_expr(&mut self, node: &ArrowExpr) {
        let shadowed = node
            .params
            .iter()
            .flat_map(binding_names)
            .collect::<BTreeSet<_>>();
        self.with_shadowed_scope(shadowed, |collector| node.visit_children_with(collector));
    }

    fn visit_member_expr(&mut self, node: &MemberExpr) {
        node.obj.visit_with(self);
        if let MemberProp::Computed(computed) = &node.prop {
            computed.expr.visit_with(self);
        }
    }

    fn visit_prop_name(&mut self, node: &PropName) {
        if let PropName::Computed(computed) = node {
            computed.expr.visit_with(self);
        }
    }

    fn visit_jsx_element_name(&mut self, _node: &JSXElementName) {}

    fn visit_jsx_attr_name(&mut self, _node: &JSXAttrName) {}
}

impl RefCollector {
    fn is_shadowed(&self, name: &str) -> bool {
        self.shadowed_scopes
            .iter()
            .rev()
            .any(|scope| scope.contains(name))
    }

    fn with_shadowed_scope<F: FnOnce(&mut Self)>(&mut self, names: BTreeSet<String>, f: F) {
        self.shadowed_scopes.push(names);
        f(self);
        self.shadowed_scopes.pop();
    }
}

/// Drop `ImportSpecifier::Named` specifiers from a residual entry
/// body whose locals are unused after a logical-module move and
/// whose binding name is claimed by `Schedule.bindings`. If all
/// of an import directive's specifiers are dropped, the directive
/// is converted to a side-effect-only `import "<src>";` rather
/// than removed — the imported source-module's evaluation must
/// still be triggered from the residual entry, since some plans
/// (e.g. ImportSpecifier-only logical modules with no `Owned`
/// bindings) are not imported by the residual at runtime and so
/// cannot stand in for the source-module evaluation.
///
/// Default and namespace specifiers are kept as-is (a namespace
/// access can be hidden behind a computed property read;
/// defaults are similarly hard to ref-count safely).
/// Side-effect-only imports (`import "./mod.js"` with no
/// specifiers) pass through unchanged — they had no specifiers
/// to begin with.
fn trim_dead_named_specifiers(
    body: &mut [ModuleItem],
    bindings: &BTreeMap<BindingName, BindingKind>,
) {
    let mut collector = RefCollector::default();
    for item in body.iter() {
        item.visit_with(&mut collector);
    }
    let refs = collector.names;
    for item in body.iter_mut() {
        let ModuleItem::ModuleDecl(ModuleDecl::Import(import)) = item else {
            continue;
        };
        // Side-effect-only imports never had specifiers; leave
        // them alone (they exist to evaluate the imported module).
        if import.specifiers.is_empty() {
            continue;
        }
        import.specifiers.retain(|spec| match spec {
            ImportSpecifier::Default(_) | ImportSpecifier::Namespace(_) => true,
            ImportSpecifier::Named(named) => {
                let local = named.local.sym.as_ref();
                let claimed = bindings.contains_key(local);
                let unused = !refs.contains(local);
                !(claimed && unused)
            }
        });
        // The directive's `specifiers: vec![]` shape is itself a
        // side-effect-only import — `import "./mod.js";`. Keeping
        // it preserves the source-module evaluation that the
        // original entry depended on, regardless of whether any
        // moved logical module is loaded by the residual.
    }
}

fn reject_duplicate_export_names(
    operation: &str,
    id: &str,
    members: &[MemberRequest],
) -> Result<()> {
    let mut seen = BTreeSet::new();
    let mut duplicates = BTreeSet::new();
    for member in members {
        if !seen.insert(member.export_name.clone()) {
            duplicates.insert(member.export_name.clone());
        }
    }
    if !duplicates.is_empty() {
        bail!(
            "{operation} {id} has duplicate exported logical names: {}",
            duplicates.into_iter().collect::<Vec<_>>().join(", ")
        );
    }
    Ok(())
}

fn reject_duplicate_member_bindings(
    operation: &str,
    id: &str,
    members: &[MemberRequest],
) -> Result<()> {
    let mut seen = BTreeSet::new();
    let mut duplicates = BTreeSet::new();
    for member in members {
        if !seen.insert(member.binding.clone()) {
            duplicates.insert(member.binding.clone());
        }
    }
    if !duplicates.is_empty() {
        bail!(
            "{operation} {id} has duplicate source bindings: {}",
            duplicates.into_iter().collect::<Vec<_>>().join(", ")
        );
    }
    Ok(())
}

fn collect_module_body_facts(body: &[ModuleItem]) -> ModuleBodyFacts {
    let mut facts = ModuleBodyFacts::default();
    let mut ref_collector = RefCollector::default();
    for item in body {
        item.visit_with(&mut ref_collector);
        facts
            .provided_locals
            .extend(top_level_declaration_names(item).0);
        if let ModuleItem::ModuleDecl(ModuleDecl::Import(import)) = item {
            for specifier in &import.specifiers {
                match specifier {
                    ImportSpecifier::Named(named) => {
                        facts.imported_locals.insert(named.local.sym.to_string());
                        facts.provided_locals.insert(named.local.sym.to_string());
                    }
                    ImportSpecifier::Default(default) => {
                        facts.imported_locals.insert(default.local.sym.to_string());
                        facts.provided_locals.insert(default.local.sym.to_string());
                    }
                    ImportSpecifier::Namespace(namespace) => {
                        facts
                            .imported_locals
                            .insert(namespace.local.sym.to_string());
                        facts
                            .provided_locals
                            .insert(namespace.local.sym.to_string());
                    }
                }
            }
        }
    }
    facts.referenced_idents = ref_collector.names;
    facts
}

fn collect_runtime_import_facts(runtime_body: &[ModuleItem]) -> RuntimeImportFacts {
    let mut imports = BTreeMap::<String, RuntimeImportInfo>::new();
    for item in runtime_body {
        let ModuleItem::ModuleDecl(ModuleDecl::Import(import)) = item else {
            continue;
        };
        let src = str_value(&import.src);
        for specifier in &import.specifiers {
            match specifier {
                ImportSpecifier::Named(named) => {
                    let local = named.local.sym.to_string();
                    let imported = match &named.imported {
                        Some(ModuleExportName::Ident(ident)) => ident.sym.to_string(),
                        Some(ModuleExportName::Str(s)) => str_value(s),
                        None => named.local.sym.to_string(),
                    };
                    imports.insert(
                        local,
                        RuntimeImportInfo {
                            kind: RuntimeImportKind::Named { imported },
                            src: src.clone(),
                        },
                    );
                }
                ImportSpecifier::Default(default) => {
                    imports.insert(
                        default.local.sym.to_string(),
                        RuntimeImportInfo {
                            kind: RuntimeImportKind::Default,
                            src: src.clone(),
                        },
                    );
                }
                ImportSpecifier::Namespace(namespace) => {
                    imports.insert(
                        namespace.local.sym.to_string(),
                        RuntimeImportInfo {
                            kind: RuntimeImportKind::Namespace,
                            src: src.clone(),
                        },
                    );
                }
            }
        }
    }
    RuntimeImportFacts { imports }
}

fn collect_imported_reexports_by_module(
    schedule: &Schedule,
    module_count: usize,
) -> Vec<Vec<ImportedReexport>> {
    let mut by_module: Vec<Vec<ImportedReexport>> = (0..module_count).map(|_| Vec::new()).collect();
    for (local, kind) in &schedule.bindings {
        let BindingKind::Imported {
            imported_name,
            imported_from,
            re_exported_by,
        } = kind
        else {
            continue;
        };
        for (module_id, public_name) in re_exported_by {
            let ModuleId::Logical(LogicalModuleIndex(index)) = module_id else {
                continue;
            };
            let Some(reexports) = by_module.get_mut(*index) else {
                continue;
            };
            reexports.push(ImportedReexport {
                local: local.clone(),
                imported_name: imported_name.clone(),
                imported_from: imported_from.clone(),
                public_name: public_name.clone(),
            });
        }
    }
    by_module
}

fn plan_module_reference_needs<'a>(
    module_index: usize,
    body_facts: &ModuleBodyFacts,
    schedule: &Schedule,
    declaration_by_name: &BTreeMap<String, usize>,
    binding_assignment: &BTreeMap<String, usize>,
    entry_exports_by_original_local: &BTreeMap<String, String>,
    runtime_import_facts: &'a RuntimeImportFacts,
) -> ModuleReferenceNeeds<'a> {
    let mut needs = ModuleReferenceNeeds::default();
    for name in &body_facts.referenced_idents {
        if let Some(ModuleId::Logical(LogicalModuleIndex(provider_index))) = schedule.owner_of(name)
        {
            if provider_index != module_index
                && let Some(provider) = schedule.logical_module(LogicalModuleIndex(provider_index))
                && let Some(exported_name) = provider.rename_map.get(name)
            {
                needs
                    .cross_module_imports_by_provider
                    .entry(provider_index)
                    .or_default()
                    .insert(name.clone(), exported_name.clone());
            }
            continue;
        }

        if !body_facts.provided_locals.contains(name)
            && !binding_assignment.contains_key(name)
            && declaration_by_name.contains_key(name)
        {
            if let Some(exported_name) = entry_exports_by_original_local.get(name) {
                needs
                    .residual_entry_imports
                    .insert(name.clone(), exported_name.clone());
            } else {
                needs.missing_residual_exports.insert(name.clone());
            }
            continue;
        }

        if body_facts.imported_locals.contains(name) {
            continue;
        }
        if let Some(info) = runtime_import_facts.imports.get(name) {
            needs.runtime_reimports.insert(name.clone(), info);
        }
    }
    needs
}

fn cross_module_imports_for_plan(
    from_file: &str,
    mut imports_by_provider: BTreeMap<usize, BTreeMap<String, String>>,
    schedule: &Schedule,
) -> Vec<ModuleItem> {
    // Sort providers by their position in the schedule's
    // `linker_order` (a topological linearization of `I ∪ S`).
    // ECMA-262's depth-first link traversal visits each module's
    // `import` directives in source order, and the deepest leaf
    // reached first evaluates first. Putting the earliest-in-`L`
    // provider at the top of the import list steers the traversal
    // toward an `I ∪ S`-respecting evaluation order. See DESIGN.md
    // "Lemma 2".
    let mut providers: Vec<usize> = imports_by_provider.keys().copied().collect();
    providers.sort_by_key(|&idx| {
        schedule
            .linker_position(ModuleId::Logical(LogicalModuleIndex(idx)))
            .unwrap_or(usize::MAX)
    });
    providers
        .into_iter()
        .filter_map(|provider_index| {
            let bindings = imports_by_provider.remove(&provider_index)?;
            schedule
                .logical_module(LogicalModuleIndex(provider_index))
                .map(|provider| import_decl_for_plan(from_file, &provider.target_file, &bindings))
        })
        .collect()
}

fn residual_entry_imports_for_moved_body(
    module_id: &str,
    entry_file: &str,
    from_file: &str,
    imports: BTreeMap<String, String>,
    missing_exports: BTreeSet<String>,
) -> Result<Vec<ModuleItem>> {
    if !missing_exports.is_empty() {
        bail!(
            "materialize_logical_modules: moved module {module_id} references residual entry binding(s) {} that are not exported by entry; refusing to emit free references. Keep those bindings with the moved module, expose them from entry, or use an explicit residual module.",
            missing_exports.into_iter().collect::<Vec<_>>().join(", "),
        );
    }
    if imports.is_empty() {
        return Ok(Vec::new());
    }
    Ok(vec![import_decl_for_plan(from_file, entry_file, &imports)])
}

fn collect_entry_exports_by_original_local(
    entry_body: &[ModuleItem],
    entry_renames: &BTreeMap<String, String>,
) -> BTreeMap<String, String> {
    let final_to_original = entry_renames
        .iter()
        .map(|(original, final_name)| (final_name.clone(), original.clone()))
        .collect::<BTreeMap<_, _>>();
    let mut exports = BTreeMap::<String, String>::new();
    for item in entry_body {
        match item {
            ModuleItem::ModuleDecl(ModuleDecl::ExportNamed(named)) if named.src.is_none() => {
                for specifier in &named.specifiers {
                    let ExportSpecifier::Named(specifier) = specifier else {
                        continue;
                    };
                    let Some(final_local) = module_export_ident_name(&specifier.orig) else {
                        continue;
                    };
                    let Some(exported_name) =
                        named_export_public_ident_name(&specifier.exported, &final_local)
                    else {
                        continue;
                    };
                    let original = final_to_original
                        .get(&final_local)
                        .cloned()
                        .unwrap_or(final_local);
                    exports.entry(original).or_insert(exported_name);
                }
            }
            ModuleItem::ModuleDecl(ModuleDecl::ExportDecl(export_decl)) => {
                for final_local in declaration_names(&export_decl.decl) {
                    let original = final_to_original
                        .get(&final_local)
                        .cloned()
                        .unwrap_or_else(|| final_local.clone());
                    exports.entry(original).or_insert(final_local);
                }
            }
            _ => {}
        }
    }
    exports
}

fn module_export_ident_name(name: &ModuleExportName) -> Option<String> {
    match name {
        ModuleExportName::Ident(ident) => Some(ident.sym.to_string()),
        ModuleExportName::Str(_) => None,
    }
}

fn named_export_public_ident_name(
    exported: &Option<ModuleExportName>,
    fallback: &str,
) -> Option<String> {
    match exported {
        Some(ModuleExportName::Ident(ident)) => Some(ident.sym.to_string()),
        Some(ModuleExportName::Str(_)) => None,
        None => Some(fallback.to_string()),
    }
}

fn final_module_exports(
    exports: &BTreeMap<String, String>,
    local_renames: &BTreeMap<String, String>,
) -> BTreeMap<String, String> {
    exports
        .iter()
        .map(|(local, exported)| {
            (
                local_renames
                    .get(local)
                    .cloned()
                    .unwrap_or_else(|| local.clone()),
                exported.clone(),
            )
        })
        .collect()
}

fn naturalize_module_body(body: &mut [ModuleItem], plan: &ModulePlan) -> BTreeMap<String, String> {
    let mut renames = BTreeMap::<String, String>::new();
    for (local, exported) in &plan.bindings {
        if local != exported && is_identifier_like(exported) {
            renames.insert(local.clone(), exported.clone());
        }
    }
    let mut heuristic = BTreeMap::<String, String>::new();
    for item in body.iter() {
        collect_naturalization_renames_from_item(item, &mut heuristic);
    }
    let renames = drop_target_collisions(renames, heuristic);
    if renames.is_empty() {
        for item in body.iter_mut() {
            item.visit_mut_with(&mut ShorthandNaturalizer);
        }
    } else {
        let mut naturalizer = RenameAndShorthandNaturalizer { renames: &renames };
        for item in body.iter_mut() {
            item.visit_mut_with(&mut naturalizer);
        }
    }
    renames
}

/// Merge `heuristic` into `plan_driven`, dropping any heuristic mapping
/// whose target is either already claimed by `plan_driven` or shared with
/// another heuristic source. Two sources renamed onto the same target
/// would collapse distinct bindings into a duplicate decl as soon as both
/// happen to live in the same scope.
fn drop_target_collisions(
    mut plan_driven: BTreeMap<String, String>,
    heuristic: BTreeMap<String, String>,
) -> BTreeMap<String, String> {
    // Only effective heuristic mappings (locals not already in plan_driven)
    // contribute to the collision count. Counting skipped entries inflates
    // counts[target] and can drop unrelated heuristic mappings that have only
    // one effective claimant.
    let mut counts = BTreeMap::<String, usize>::new();
    for target in plan_driven.values() {
        *counts.entry(target.clone()).or_default() += 1;
    }
    for (local, target) in &heuristic {
        if plan_driven.contains_key(local) {
            continue;
        }
        *counts.entry(target.clone()).or_default() += 1;
    }
    for (local, target) in heuristic {
        if plan_driven.contains_key(&local) {
            continue;
        }
        if counts.get(&target).copied().unwrap_or(0) > 1 {
            continue;
        }
        plan_driven.insert(local, target);
    }
    plan_driven
}

fn collect_naturalization_renames_from_item(
    item: &ModuleItem,
    renames: &mut BTreeMap<String, String>,
) {
    match item {
        ModuleItem::Stmt(Stmt::Decl(Decl::Fn(function))) => {
            collect_naturalization_renames_from_function(&function.function, renames);
        }
        ModuleItem::Stmt(Stmt::Decl(Decl::Class(class))) => {
            collect_naturalization_renames_from_class(&class.class, renames);
        }
        ModuleItem::Stmt(Stmt::Decl(Decl::Var(var))) => {
            for declarator in &var.decls {
                if let Some(init) = declarator.init.as_ref() {
                    collect_naturalization_renames_from_expr(init, renames);
                }
            }
        }
        ModuleItem::ModuleDecl(ModuleDecl::ExportDecl(export_decl)) => match &export_decl.decl {
            Decl::Fn(function) => {
                collect_naturalization_renames_from_function(&function.function, renames);
            }
            Decl::Class(class) => {
                collect_naturalization_renames_from_class(&class.class, renames);
            }
            Decl::Var(var) => {
                for declarator in &var.decls {
                    if let Some(init) = declarator.init.as_ref() {
                        collect_naturalization_renames_from_expr(init, renames);
                    }
                }
            }
            _ => {}
        },
        _ => {}
    }
}

fn collect_naturalization_renames_from_expr(expr: &Expr, renames: &mut BTreeMap<String, String>) {
    match expr {
        Expr::Fn(function) => {
            collect_naturalization_renames_from_function(&function.function, renames)
        }
        Expr::Arrow(arrow) => {
            for param in &arrow.params {
                collect_naturalization_renames_from_pattern(param, renames);
            }
        }
        Expr::Class(class) => collect_naturalization_renames_from_class(&class.class, renames),
        _ => {}
    }
}

fn collect_naturalization_renames_from_function(
    function: &Function,
    renames: &mut BTreeMap<String, String>,
) {
    for param in &function.params {
        collect_naturalization_renames_from_pattern(&param.pat, renames);
    }
    let Some(body) = function.body.as_ref() else {
        return;
    };
    collect_return_object_alias_renames(&body.stmts, renames);
}

fn collect_naturalization_renames_from_class(
    class: &Class,
    renames: &mut BTreeMap<String, String>,
) {
    for member in &class.body {
        let ClassMember::Constructor(constructor) = member else {
            continue;
        };
        let mut param_names = BTreeSet::new();
        for param in &constructor.params {
            if let ParamOrTsParamProp::Param(param) = param
                && let Pat::Ident(ident) = &param.pat
            {
                param_names.insert(ident.id.sym.to_string());
            }
        }
        let Some(body) = constructor.body.as_ref() else {
            continue;
        };
        for statement in &body.stmts {
            collect_constructor_assignment_renames(statement, &param_names, renames);
        }
    }
}

fn collect_naturalization_renames_from_pattern(pat: &Pat, renames: &mut BTreeMap<String, String>) {
    match pat {
        Pat::Object(object) => {
            for prop in &object.props {
                match prop {
                    ObjectPatProp::KeyValue(key_value) => {
                        if let PropName::Ident(key) = &key_value.key
                            && let Pat::Ident(value) = &*key_value.value
                        {
                            let from = value.id.sym.to_string();
                            let to = key.sym.to_string();
                            if from != to && is_identifier_like(&to) {
                                renames.insert(from, to);
                            }
                        }
                    }
                    ObjectPatProp::Assign(_) => {}
                    ObjectPatProp::Rest(rest) => {
                        collect_naturalization_renames_from_pattern(&rest.arg, renames);
                    }
                }
            }
        }
        Pat::Array(array) => {
            for elem in array.elems.iter().flatten() {
                collect_naturalization_renames_from_pattern(elem, renames);
            }
        }
        Pat::Assign(assign) => collect_naturalization_renames_from_pattern(&assign.left, renames),
        Pat::Rest(rest) => collect_naturalization_renames_from_pattern(&rest.arg, renames),
        _ => {}
    }
}

fn collect_return_object_alias_renames(stmts: &[Stmt], renames: &mut BTreeMap<String, String>) {
    for stmt in stmts {
        match stmt {
            Stmt::Return(return_stmt) => {
                if let Some(expr) = &return_stmt.arg
                    && let Expr::Object(object) = &**expr
                {
                    for prop in &object.props {
                        if let PropOrSpread::Prop(prop) = prop
                            && let Prop::KeyValue(key_value) = &**prop
                            && let PropName::Ident(key) = &key_value.key
                            && let Expr::Ident(value) = &*key_value.value
                        {
                            let from = value.sym.to_string();
                            let to = key.sym.to_string();
                            if from != to && is_identifier_like(&to) {
                                renames.insert(from, to);
                            }
                        }
                    }
                }
            }
            Stmt::Block(block) => collect_return_object_alias_renames(&block.stmts, renames),
            _ => {}
        }
    }
}

fn collect_constructor_assignment_renames(
    stmt: &Stmt,
    param_names: &BTreeSet<String>,
    renames: &mut BTreeMap<String, String>,
) {
    let Stmt::Expr(expr_stmt) = stmt else {
        return;
    };
    let Expr::Assign(assign) = &*expr_stmt.expr else {
        return;
    };
    if assign.op != AssignOp::Assign {
        return;
    }
    let Some(target_name) = this_property_name(&assign.left) else {
        return;
    };
    let Expr::Ident(value) = &*assign.right else {
        return;
    };
    let from = value.sym.to_string();
    if param_names.contains(&from) && from != target_name && is_identifier_like(&target_name) {
        renames.insert(from, target_name);
    }
}

fn this_property_name(target: &AssignTarget) -> Option<String> {
    let AssignTarget::Simple(SimpleAssignTarget::Member(member)) = target else {
        return None;
    };
    if !matches!(&*member.obj, Expr::This(_)) {
        return None;
    }
    match &member.prop {
        MemberProp::Ident(ident) => Some(ident.sym.to_string()),
        MemberProp::Computed(computed) => match &*computed.expr {
            Expr::Lit(Lit::Str(value)) if is_identifier_like(&str_value(value)) => {
                Some(str_value(value))
            }
            _ => None,
        },
        _ => None,
    }
}

struct IdentifierRenamer<'a> {
    renames: &'a BTreeMap<String, String>,
}

impl VisitMut for IdentifierRenamer<'_> {
    fn visit_mut_ident(&mut self, ident: &mut Ident) {
        if let Some(to) = self.renames.get(ident.sym.as_ref()) {
            ident.sym = to.clone().into();
        }
    }

    fn visit_mut_import_named_specifier(&mut self, spec: &mut ImportNamedSpecifier) {
        let original_local = spec.local.sym.clone();
        let Some(to) = self.renames.get(original_local.as_ref()) else {
            return;
        };
        if spec.imported.is_none() {
            spec.imported = Some(ModuleExportName::Ident(Ident::new_no_ctxt(
                original_local,
                DUMMY_SP,
            )));
        }
        spec.local.sym = to.clone().into();
    }

    fn visit_mut_prop_name(&mut self, prop_name: &mut PropName) {
        if let PropName::Computed(computed) = prop_name {
            computed.visit_mut_children_with(self);
        }
    }

    fn visit_mut_member_prop(&mut self, member_prop: &mut MemberProp) {
        if let MemberProp::Computed(computed) = member_prop {
            computed.visit_mut_children_with(self);
        }
    }

    fn visit_mut_named_export(&mut self, named: &mut NamedExport) {
        // Re-export specifiers' orig field (`export { x } from "./mod"`) is
        // the imported name in the source module, not a local binding here,
        // so don't touch it. Without `from`, orig is a local binding —
        // recurse into specifiers so visit_mut_export_named_specifier can
        // narrow which fields to rewrite.
        if named.src.is_none() {
            named.specifiers.visit_mut_with(self);
        }
    }

    fn visit_mut_export_named_specifier(&mut self, spec: &mut ExportNamedSpecifier) {
        // The `exported` field is a public-API name, not a local binding,
        // so it must not be rewritten when a colliding local is renamed.
        spec.orig.visit_mut_with(self);
    }
}

struct RenameAndShorthandNaturalizer<'a> {
    renames: &'a BTreeMap<String, String>,
}

impl VisitMut for RenameAndShorthandNaturalizer<'_> {
    fn visit_mut_ident(&mut self, ident: &mut Ident) {
        if let Some(to) = self.renames.get(ident.sym.as_ref()) {
            ident.sym = to.clone().into();
        }
    }

    fn visit_mut_import_named_specifier(&mut self, spec: &mut ImportNamedSpecifier) {
        let original_local = spec.local.sym.clone();
        let Some(to) = self.renames.get(original_local.as_ref()) else {
            return;
        };
        if spec.imported.is_none() {
            spec.imported = Some(ModuleExportName::Ident(Ident::new_no_ctxt(
                original_local,
                DUMMY_SP,
            )));
        }
        spec.local.sym = to.clone().into();
    }

    fn visit_mut_prop_name(&mut self, prop_name: &mut PropName) {
        if let PropName::Computed(computed) = prop_name {
            computed.visit_mut_children_with(self);
        }
    }

    fn visit_mut_member_prop(&mut self, member_prop: &mut MemberProp) {
        if let MemberProp::Computed(computed) = member_prop {
            computed.visit_mut_children_with(self);
        }
    }

    fn visit_mut_named_export(&mut self, named: &mut NamedExport) {
        if named.src.is_none() {
            named.specifiers.visit_mut_with(self);
        }
    }

    fn visit_mut_export_named_specifier(&mut self, spec: &mut ExportNamedSpecifier) {
        spec.orig.visit_mut_with(self);
    }

    fn visit_mut_object_pat(&mut self, object: &mut ObjectPat) {
        object.visit_mut_children_with(self);
        naturalize_object_pattern_shorthand(object);
    }

    fn visit_mut_object_lit(&mut self, object: &mut ObjectLit) {
        object.visit_mut_children_with(self);
        naturalize_object_literal_shorthand(object);
    }
}

struct ShorthandNaturalizer;

impl VisitMut for ShorthandNaturalizer {
    fn visit_mut_object_pat(&mut self, object: &mut ObjectPat) {
        object.visit_mut_children_with(self);
        naturalize_object_pattern_shorthand(object);
    }

    fn visit_mut_object_lit(&mut self, object: &mut ObjectLit) {
        object.visit_mut_children_with(self);
        naturalize_object_literal_shorthand(object);
    }
}

fn naturalize_object_pattern_shorthand(object: &mut ObjectPat) {
    for prop in &mut object.props {
        if let ObjectPatProp::KeyValue(key_value) = prop
            && let PropName::Ident(key) = &key_value.key
            && let Pat::Ident(value) = &*key_value.value
            && key.sym == value.id.sym
        {
            *prop = ObjectPatProp::Assign(AssignPatProp {
                span: DUMMY_SP,
                key: value.clone(),
                value: None,
            });
        }
    }
}

fn naturalize_object_literal_shorthand(object: &mut ObjectLit) {
    for prop in &mut object.props {
        if let PropOrSpread::Prop(prop_box) = prop
            && let Prop::KeyValue(key_value) = &**prop_box
            && let PropName::Ident(key) = &key_value.key
            && let Expr::Ident(value) = &*key_value.value
            && key.sym == value.sym
        {
            *prop = PropOrSpread::Prop(Box::new(Prop::Shorthand(value.clone())));
        }
    }
}

fn rewrite_runtime_sources_for_target(body: &mut [ModuleItem], target_file: &str) {
    let target_dir = Path::new(target_file)
        .parent()
        .and_then(Path::to_str)
        .unwrap_or("")
        .replace('\\', "/");
    let mut rewriter = RuntimeSourceRewriter { target_dir };
    for item in body {
        item.visit_mut_with(&mut rewriter);
    }
}

struct RuntimeSourceRewriter {
    target_dir: String,
}

impl RuntimeSourceRewriter {
    fn rewrite(&self, source: &str) -> String {
        let original = normalize_module_path(source).unwrap_or_else(|_| source.to_string());
        // Original import sources in lowered module bodies are chunk-root-relative;
        // the lowered file lives at <target_dir>/<basename> within the chunk, so the
        // rewritten specifier walks up out of target_dir to chunk root.
        let mut rel = relative_module_path(&self.target_dir, &original);
        if !rel.starts_with('.') {
            rel = format!("./{rel}");
        }
        rel
    }
}

impl VisitMut for RuntimeSourceRewriter {
    fn visit_mut_call_expr(&mut self, call: &mut CallExpr) {
        call.visit_mut_children_with(self);
        if matches!(call.callee, Callee::Import(_))
            && let Some(first) = call.args.first_mut()
            && let Expr::Lit(Lit::Str(source)) = &mut *first.expr
        {
            set_str_value(source, self.rewrite(&str_value(source)));
        }
    }

    fn visit_mut_new_expr(&mut self, new_expr: &mut NewExpr) {
        new_expr.visit_mut_children_with(self);
        let Expr::Ident(callee) = &*new_expr.callee else {
            return;
        };
        if callee.sym != *"Worker" && callee.sym != *"SharedWorker" {
            return;
        }
        let Some(args) = new_expr.args.as_mut() else {
            return;
        };
        let Some(first) = args.first_mut() else {
            return;
        };
        let Expr::Lit(Lit::Str(source)) = &*first.expr else {
            return;
        };
        first.expr = Box::new(new_url_expr(&self.rewrite(&str_value(source))));
    }
}

fn new_url_expr(source: &str) -> Expr {
    Expr::New(NewExpr {
        span: DUMMY_SP,
        ctxt: SyntaxContext::empty(),
        callee: Box::new(Expr::Ident(Ident::new_no_ctxt("URL".into(), DUMMY_SP))),
        args: Some(vec![
            ExprOrSpread {
                spread: None,
                expr: Box::new(Expr::Lit(Lit::Str(Str {
                    span: DUMMY_SP,
                    value: source.into(),
                    raw: None,
                }))),
            },
            ExprOrSpread {
                spread: None,
                expr: Box::new(import_meta_url_expr()),
            },
        ]),
        type_args: None,
    })
}

fn import_meta_url_expr() -> Expr {
    Expr::Member(MemberExpr {
        span: DUMMY_SP,
        obj: Box::new(Expr::MetaProp(MetaPropExpr {
            span: DUMMY_SP,
            kind: MetaPropKind::ImportMeta,
        })),
        prop: MemberProp::Ident(IdentName::new("url".into(), DUMMY_SP)),
    })
}

fn is_identifier_like(name: &str) -> bool {
    let mut chars = name.chars();
    let Some(first) = chars.next() else {
        return false;
    };
    if !(first == '_' || first == '$' || first.is_ascii_alphabetic()) {
        return false;
    }
    chars.all(|ch| ch == '_' || ch == '$' || ch.is_ascii_alphanumeric())
}

fn target_file_for_request(target_dir: &str, target_path: &str) -> Result<String> {
    let normalized = normalize_module_path(target_path)?;
    let with_ext = if normalized.ends_with(".js") {
        normalized
    } else {
        format!("{normalized}.js")
    };
    Ok(join_module_path(&[target_dir, &with_ext]))
}

fn normalize_optional_relative_dir(value: &str) -> Result<String> {
    if value.is_empty() {
        return Ok(String::new());
    }
    normalize_module_path(value)
}

fn remaining_item_after_selection(
    item: &ModuleItem,
    binding_assignment: &BTreeMap<String, usize>,
    selected_by_module: &mut [Vec<ModuleItem>],
) -> Result<Vec<ModuleItem>> {
    match item {
        ModuleItem::Stmt(Stmt::Decl(Decl::Var(var))) => {
            split_var_decl(var, false, binding_assignment, selected_by_module)
        }
        ModuleItem::ModuleDecl(ModuleDecl::ExportDecl(export_decl)) => match &export_decl.decl {
            Decl::Var(var) => split_var_decl(var, true, binding_assignment, selected_by_module),
            decl => {
                let names = declaration_names(decl);
                if let Some(module_index) = assigned_module_for_names(&names, binding_assignment) {
                    selected_by_module[module_index]
                        .push(ModuleItem::Stmt(Stmt::Decl(decl.clone())));
                    Ok(Vec::new())
                } else {
                    Ok(vec![item.clone()])
                }
            }
        },
        ModuleItem::Stmt(Stmt::Decl(decl)) => {
            let names = declaration_names(decl);
            if let Some(module_index) = assigned_module_for_names(&names, binding_assignment) {
                selected_by_module[module_index].push(item.clone());
                Ok(Vec::new())
            } else {
                Ok(vec![item.clone()])
            }
        }
        _ => Ok(vec![item.clone()]),
    }
}

fn split_var_decl(
    var: &VarDecl,
    was_exported: bool,
    binding_assignment: &BTreeMap<String, usize>,
    selected_by_module: &mut [Vec<ModuleItem>],
) -> Result<Vec<ModuleItem>> {
    let mut residual_decls = Vec::new();
    for declarator in &var.decls {
        let names = binding_names(&declarator.name);
        if let Some(module_index) = assigned_module_for_names(&names, binding_assignment) {
            let selected_var = VarDecl {
                span: var.span,
                ctxt: var.ctxt,
                kind: var.kind,
                declare: var.declare,
                decls: vec![declarator.clone()],
            };
            selected_by_module[module_index].push(ModuleItem::Stmt(Stmt::Decl(Decl::Var(
                Box::new(selected_var),
            ))));
        } else {
            residual_decls.push(declarator.clone());
        }
    }
    if residual_decls.is_empty() {
        return Ok(Vec::new());
    }
    let residual_var = VarDecl {
        span: var.span,
        ctxt: var.ctxt,
        kind: var.kind,
        declare: var.declare,
        decls: residual_decls,
    };
    if was_exported {
        Ok(vec![ModuleItem::ModuleDecl(ModuleDecl::ExportDecl(
            ExportDecl {
                span: DUMMY_SP,
                decl: Decl::Var(Box::new(residual_var)),
            },
        ))])
    } else {
        Ok(vec![ModuleItem::Stmt(Stmt::Decl(Decl::Var(Box::new(
            residual_var,
        ))))])
    }
}

fn assigned_module_for_names(
    names: &[String],
    binding_assignment: &BTreeMap<String, usize>,
) -> Option<usize> {
    names
        .iter()
        .filter_map(|name| binding_assignment.get(name).copied())
        .next()
}

/// Names occupying the file-scope binding namespace of `body`.
///
/// Used to disambiguate consumer-side `import { exportedName as localName }`
/// emissions whose `localName` would collide with another binding in the
/// same scope (e.g. a surviving import or top-level declaration that
/// already uses the scrambled name). `export { name }` re-exports without
/// `from` are references, not bindings, so they aren't tracked here; the
/// IdentifierRenamer pass that follows the disambiguation rewrites their
/// `orig` ident along with every other body reference.
fn collect_occupied_local_names(body: &[ModuleItem]) -> BTreeSet<String> {
    let mut occupied = BTreeSet::new();
    for item in body {
        match item {
            ModuleItem::ModuleDecl(ModuleDecl::Import(import)) => {
                for specifier in &import.specifiers {
                    match specifier {
                        ImportSpecifier::Named(named) => {
                            occupied.insert(named.local.sym.to_string());
                        }
                        ImportSpecifier::Default(default) => {
                            occupied.insert(default.local.sym.to_string());
                        }
                        ImportSpecifier::Namespace(namespace) => {
                            occupied.insert(namespace.local.sym.to_string());
                        }
                    }
                }
            }
            ModuleItem::ModuleDecl(ModuleDecl::ExportDecl(export_decl)) => {
                for name in declaration_names(&export_decl.decl) {
                    occupied.insert(name);
                }
            }
            ModuleItem::ModuleDecl(ModuleDecl::ExportDefaultDecl(default_decl)) => {
                if let DefaultDecl::Class(class) = &default_decl.decl
                    && let Some(ident) = &class.ident
                {
                    occupied.insert(ident.sym.to_string());
                }
                if let DefaultDecl::Fn(function) = &default_decl.decl
                    && let Some(ident) = &function.ident
                {
                    occupied.insert(ident.sym.to_string());
                }
            }
            ModuleItem::Stmt(Stmt::Decl(decl)) => {
                for name in declaration_names(decl) {
                    occupied.insert(name);
                }
            }
            _ => {}
        }
    }
    occupied
}

/// Map plan-side `local -> exported` to `actual_local -> exported`,
/// minting a fresh `<local>$N` whenever the requested local would collide
/// with `occupied`. Records original-to-fresh entries in `renames` so the
/// caller can rewrite consumer-body references after emission.
fn disambiguate_import_locals(
    bindings: &BTreeMap<String, String>,
    occupied: &mut BTreeSet<String>,
    renames: &mut BTreeMap<String, String>,
) -> BTreeMap<String, String> {
    bindings
        .iter()
        .map(|(local, exported)| {
            let actual = if occupied.contains(local) {
                let fresh = mint_fresh_local_name(local, occupied);
                renames.insert(local.clone(), fresh.clone());
                fresh
            } else {
                local.clone()
            };
            occupied.insert(actual.clone());
            (actual, exported.clone())
        })
        .collect()
}

/// Pre-fill `exported` on `export { local }` re-export specifiers whose
/// `local` is about to be renamed, so the public export name survives.
fn preserve_export_specifier_names(item: &mut ModuleItem, renames: &BTreeMap<String, String>) {
    let ModuleItem::ModuleDecl(ModuleDecl::ExportNamed(named)) = item else {
        return;
    };
    for specifier in &mut named.specifiers {
        let ExportSpecifier::Named(spec) = specifier else {
            continue;
        };
        if spec.exported.is_some() {
            continue;
        }
        let ModuleExportName::Ident(orig) = &spec.orig else {
            continue;
        };
        if !renames.contains_key(&orig.sym.to_string()) {
            continue;
        }
        spec.exported = Some(spec.orig.clone());
    }
}

fn mint_fresh_local_name(base: &str, occupied: &BTreeSet<String>) -> String {
    let mut suffix = 1usize;
    loop {
        let candidate = format!("{base}${suffix}");
        if !occupied.contains(&candidate) {
            return candidate;
        }
        suffix += 1;
    }
}

/// Look up an `ImportSpecifier`-bound member's source-chunk import
/// statement and resolve it to `(imported_name, imported_from)` where
/// `imported_from` is the output-tree-rooted absolute path of the
/// import source (suitable for storing on `BindingKind::Imported`).
/// Per-destination relative paths are computed at emit time via
/// `relative_source(dest_target_file, imported_from)`.
fn resolve_imported_binding(
    source_import_cache: &mut ArtifactSourceImportResolutionCache<'_>,
    runtime_import_facts: &RuntimeImportFacts,
    source_chunk_id: &str,
    source_runtime_file: &str,
    source_local: &str,
) -> Result<(String, String)> {
    let Some(info) = runtime_import_facts.imports.get(source_local) else {
        bail!("no import specifier found for `{source_local}` in source chunk");
    };
    let RuntimeImportKind::Named { imported } = &info.kind else {
        bail!("no named import specifier found for `{source_local}` in source chunk");
    };
    let imported_from = if let Some((_, _, path)) =
        source_import_cache.resolve(&info.src, source_chunk_id, source_runtime_file)?
    {
        path
    } else {
        // Source path doesn't reference a known chunk (e.g. a
        // synthetic e2e snapshot file with no entry in the artifact).
        // Resolve relative to the source chunk's directory in the
        // output tree (chunk_id includes the directory prefix; the
        // runtime file is chunk-relative).
        let chunk_runtime_abs = join_module_path(&[
            &module_path_dirname(source_chunk_id),
            &module_path_dirname(source_runtime_file),
        ]);
        join_module_path(&[&chunk_runtime_abs, &info.src])
    };
    Ok((imported.clone(), imported_from))
}

/// Build re-imports for source-chunk ImportSpecifier-bound locals that
/// `body` (the moved code for this destination module) references but
/// no enclosing import or local decl provides. Each emitted import
/// uses a destination-relative path resolved through the artifact's
/// source-chunk index, so it stays correct after the rewriter (which
/// skips materialized files).
fn source_chunk_imports_for_moved_body(
    source_import_cache: &mut ArtifactSourceImportResolutionCache<'_>,
    source_chunk_id: &str,
    source_runtime_file: &str,
    dest_target_file: &str,
    needed: BTreeMap<String, &RuntimeImportInfo>,
) -> Result<Vec<ModuleItem>> {
    let mut result = Vec::new();
    let dest_dir = join_module_path(&[source_chunk_id, &module_path_dirname(dest_target_file)]);
    for (local, info) in needed {
        let rewritten_source = if let Some((target_chunk_id, target_entry_file, _path)) =
            source_import_cache.resolve(&info.src, source_chunk_id, source_runtime_file)?
        {
            let target_path = join_module_path(&[&target_chunk_id, &target_entry_file]);
            let mut rel = relative_module_path(&dest_dir, &target_path);
            if !rel.starts_with('.') {
                rel = format!("./{rel}");
            }
            rel
        } else {
            let depth = std::path::Path::new(dest_target_file)
                .parent()
                .map(|parent| parent.iter().count())
                .unwrap_or(0);
            format!("{}{}", "../".repeat(depth), info.src)
        };
        result.push(build_runtime_reimport(&local, info, &rewritten_source));
    }
    Ok(result)
}

#[derive(Debug)]
struct RuntimeImportInfo {
    kind: RuntimeImportKind,
    src: String,
}

#[derive(Debug)]
enum RuntimeImportKind {
    Named { imported: String },
    Default,
    Namespace,
}

fn build_runtime_reimport(local: &str, info: &RuntimeImportInfo, src: &str) -> ModuleItem {
    let specifier = match &info.kind {
        RuntimeImportKind::Named { imported } => ImportSpecifier::Named(ImportNamedSpecifier {
            span: DUMMY_SP,
            local: Ident::new_no_ctxt(local.into(), DUMMY_SP),
            imported: if imported == local {
                None
            } else {
                Some(ModuleExportName::Ident(Ident::new_no_ctxt(
                    imported.clone().into(),
                    DUMMY_SP,
                )))
            },
            is_type_only: false,
        }),
        RuntimeImportKind::Default => ImportSpecifier::Default(ImportDefaultSpecifier {
            span: DUMMY_SP,
            local: Ident::new_no_ctxt(local.into(), DUMMY_SP),
        }),
        RuntimeImportKind::Namespace => ImportSpecifier::Namespace(ImportStarAsSpecifier {
            span: DUMMY_SP,
            local: Ident::new_no_ctxt(local.into(), DUMMY_SP),
        }),
    };
    ModuleItem::ModuleDecl(ModuleDecl::Import(ImportDecl {
        span: DUMMY_SP,
        specifiers: vec![specifier],
        src: Box::new(Str {
            span: DUMMY_SP,
            value: src.into(),
            raw: None,
        }),
        type_only: false,
        with: None,
        phase: ImportPhase::Evaluation,
    }))
}

/// Emit `import { <imported> as <local> } from "<src>"` (or just
/// `import { <local> } from "<src>"` when local == imported).
fn imported_binding_import_decl(local: &str, imported: &str, src: &str) -> ModuleItem {
    ModuleItem::ModuleDecl(ModuleDecl::Import(ImportDecl {
        span: DUMMY_SP,
        specifiers: vec![ImportSpecifier::Named(ImportNamedSpecifier {
            span: DUMMY_SP,
            local: Ident::new_no_ctxt(local.into(), DUMMY_SP),
            imported: if local == imported {
                None
            } else {
                Some(ModuleExportName::Ident(Ident::new_no_ctxt(
                    imported.into(),
                    DUMMY_SP,
                )))
            },
            is_type_only: false,
        })],
        src: Box::new(Str {
            span: DUMMY_SP,
            value: src.into(),
            raw: None,
        }),
        type_only: false,
        with: None,
        phase: ImportPhase::Evaluation,
    }))
}

fn import_decl_for_plan(
    entry_file: &str,
    target_file: &str,
    bindings: &BTreeMap<String, String>,
) -> ModuleItem {
    let source = relative_source(entry_file, target_file);
    ModuleItem::ModuleDecl(ModuleDecl::Import(ImportDecl {
        span: DUMMY_SP,
        specifiers: bindings
            .iter()
            .map(|(local, exported)| {
                ImportSpecifier::Named(ImportNamedSpecifier {
                    span: DUMMY_SP,
                    local: Ident::new_no_ctxt(local.clone().into(), DUMMY_SP),
                    imported: if local == exported {
                        None
                    } else {
                        Some(ModuleExportName::Ident(Ident::new_no_ctxt(
                            exported.clone().into(),
                            DUMMY_SP,
                        )))
                    },
                    is_type_only: false,
                })
            })
            .collect(),
        src: Box::new(Str {
            span: DUMMY_SP,
            value: source.into(),
            raw: None,
        }),
        type_only: false,
        with: None,
        phase: ImportPhase::Evaluation,
    }))
}

fn relative_source(from_file: &str, target_file: &str) -> String {
    let from_dir = std::path::Path::new(from_file)
        .parent()
        .and_then(|parent| parent.to_str())
        .unwrap_or("")
        .replace('\\', "/");
    let mut rel = relative_module_path(&from_dir, target_file);
    if !rel.starts_with('.') {
        rel = format!("./{rel}");
    }
    rel
}

fn export_named_for_bindings(bindings: &BTreeMap<String, String>) -> ModuleItem {
    ModuleItem::ModuleDecl(ModuleDecl::ExportNamed(NamedExport {
        span: DUMMY_SP,
        specifiers: bindings
            .iter()
            .map(|(local, exported)| {
                ExportSpecifier::Named(ExportNamedSpecifier {
                    span: DUMMY_SP,
                    orig: ModuleExportName::Ident(Ident::new_no_ctxt(
                        local.clone().into(),
                        DUMMY_SP,
                    )),
                    exported: if local == exported {
                        None
                    } else {
                        Some(ModuleExportName::Ident(Ident::new_no_ctxt(
                            exported.clone().into(),
                            DUMMY_SP,
                        )))
                    },
                    is_type_only: false,
                })
            })
            .collect(),
        src: None,
        type_only: false,
        with: None,
    }))
}

fn entry_exports_for_moved_bindings(
    declarations: &[TopLevelDecl],
    binding_assignment: &BTreeMap<String, usize>,
) -> Vec<ModuleItem> {
    let mut exports = BTreeMap::<String, String>::new();
    for decl in declarations.iter().filter(|decl| decl.exported) {
        for name in &decl.names {
            if binding_assignment.contains_key(name) {
                exports.insert(name.clone(), name.clone());
            }
        }
    }
    if exports.is_empty() {
        Vec::new()
    } else {
        vec![export_named_for_bindings(&exports)]
    }
}

fn prune_artifact_to_chunk_ids(artifact: &mut JsPipelineArtifact, selected: &[String]) {
    let selected = selected.iter().cloned().collect::<BTreeSet<_>>();
    artifact
        .chunks
        .retain(|chunk_id, _| selected.contains(chunk_id));
    artifact
        .chunk_order
        .retain(|chunk_id| selected.contains(chunk_id));
    artifact
        .chunk_manifests
        .retain(|chunk_id, _| selected.contains(chunk_id));
    if let Some(root_manifest) = &mut artifact.root_manifest {
        root_manifest
            .chunks
            .retain(|chunk| selected.contains(&chunk.chunk_id));
        root_manifest.counts.chunks = root_manifest.chunks.len();
    }
}

fn update_root_manifest(
    artifact: &mut JsPipelineArtifact,
    reports: &[LogicalChunkReport],
    applied: &[SelectedModuleLowering],
) {
    if artifact.root_manifest.is_none() {
        artifact.root_manifest = Some(ArtifactManifest {
            counts: ArtifactCounts {
                chunks: artifact.list_chunk_ids().len(),
                kept_top_level_declaration_owners: 0,
                top_level_side_effects: 0,
                export_aliases: 0,
                unresolved_exports: 0,
                selected_module_lowerings: None,
            },
            chunks: artifact
                .list_chunk_ids()
                .into_iter()
                .map(|chunk_id| ::artifact::ArtifactChunkRecord {
                    source_path: artifact
                        .chunk_source_path(&chunk_id)
                        .unwrap_or_else(|| format!("{chunk_id}.js")),
                    chunk_id,
                })
                .collect(),
            logical_modules: None,
            selected_module_lowerings: None,
            scrambled_identifier_frequencies: None,
            output_metrics: None,
        });
    }
    let Some(root_manifest) = &mut artifact.root_manifest else {
        return;
    };
    root_manifest.counts.selected_module_lowerings = Some(applied.len());
    root_manifest.logical_modules = Some(RootLogicalModulesSummary {
        module_count: reports.iter().map(|r| r.counts.final_modules).sum(),
    });
    root_manifest.selected_module_lowerings = Some(applied.to_vec());
}

fn write_chunk_report_json<T: Serialize>(
    report_out_dir: &Path,
    chunk_id: &str,
    filename: &str,
    value: &T,
) -> Result<()> {
    let path = report_out_dir
        .join(chunk_id.split('/').collect::<PathBuf>())
        .join(filename);
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    let body = if filename == "owner_graph.json" {
        // This side output is large enough on real app chunks that pretty
        // printing meaningfully affects local and remote test artifact size.
        // Keep small human-first reports pretty; keep the graph jq-first.
        serde_json::to_string(value)?
    } else {
        serde_json::to_string_pretty(value)?
    };
    fs::write(path, body + "\n")?;
    Ok(())
}

fn prepare_output_dir(out_dir: &Path, force: bool) -> Result<()> {
    if out_dir.exists() {
        if !out_dir.is_dir() {
            bail!(
                "Output path exists and is not a directory: {}",
                out_dir.display()
            );
        }
        if fs::read_dir(out_dir)?.next().is_some() && !force {
            bail!(
                "Output directory is not empty: {}. Pass --force to replace it.",
                out_dir.display()
            );
        }
        if force {
            fs::remove_dir_all(out_dir)?;
        }
    }
    fs::create_dir_all(out_dir)?;
    Ok(())
}
