//! Spec-derived request + plan structures plus the helpers that
//! convert spec entries into `LogicalRequest`s. Mini-factor plan
//! synthesis lives on `ChunkPlanBuilder::synthesize_mini_factors`.

use super::*;

#[derive(Debug, Clone)]
pub(super) struct LogicalRequest {
    pub(super) id: String,
    pub(super) target_path: String,
    pub(super) residual: bool,
    pub(super) members: Vec<MemberRequest>,
    /// Verbatim source of each anonymous-statement member the spec
    /// asked to co-move into this module. Resolved later (after AST
    /// analysis) into [`ModulePlan::anonymous_statement_ordinals`].
    pub(super) anonymous_match_sources: Vec<String>,
    /// Module-level human-readable comment from the spec. Emitted
    /// at the top of the generated module file, before any imports.
    /// See [`spec::LogicalModule::comment`].
    pub(super) comment: Option<String>,
}

#[derive(Debug, Clone)]
pub(super) struct MemberRequest {
    pub(super) binding: String,
    pub(super) export_name: String,
    /// When `true`, the member's source is an import specifier in the
    /// source chunk (not a top-level decl). The materializer looks up
    /// the import statement by `binding` in the chunk body and rewrites
    /// it to a re-import in the destination module.
    pub(super) is_import_specifier: bool,
    /// Spec-level purity annotation. `Pure` asserts that calls to the
    /// bound function have no observable side effects — the validator
    /// trusts the annotation and drops S edges for `<binding>(...)`
    /// call sites. `Default` means "not annotated, fall back to
    /// inferred classification". An author-trust contract; see
    /// AGENTS.md "Declared purity" and docs/design.md A9.
    pub(super) purity: MemberPurity,
    /// Spec-level local-effect annotation. `TypescriptDecorateHelper`
    /// asserts that recognized calls to the bound helper mutate only
    /// their target class/prototype, so the analyzer can model a local
    /// effect edge instead of a global side-effect-order edge.
    pub(super) effect: MemberEffect,
    /// Property names on the bound value whose member calls
    /// (`<binding>.<prop>(args)` / `<binding>?.<prop>(args)`) the author
    /// asserts have no observable side effects beyond evaluating their
    /// arguments. Same author-trust contract as `purity: pure` — see
    /// AGENTS.md "Declared purity". Empty when the spec doesn't carry a
    /// `pure_members` entry for this member.
    pub(super) pure_members: Vec<String>,
    /// Per-member human-readable comment from the spec. Emitted as a
    /// `// ...` block above the binding's owner statement in the
    /// generated module body. See [`spec::Member::comment`].
    pub(super) comment: Option<String>,
}

impl MemberRequest {
    /// Extend `hints` with this member's spec-level trust assertions
    /// (purity, pure_members, effect). Spec annotations carried on any
    /// member form (logical-module member, chunk_renames member)
    /// propagate the same way — they are semantic trust assertions,
    /// not ownership claims; binding patches routed through
    /// chunk_renames still do not force factorizer grouping.
    pub(super) fn collect_hints(&self, hints: &mut AnalysisHints) {
        if self.purity == MemberPurity::Pure {
            hints.declared_pure.insert(self.binding.clone());
        }
        if self.purity == MemberPurity::PureNew {
            hints.declared_pure_new.insert(self.binding.clone());
        }
        if !self.pure_members.is_empty() {
            hints
                .declared_pure_members
                .entry(self.binding.clone())
                .or_default()
                .extend(self.pure_members.iter().cloned());
        }
        if let Some(effect) = known_effect_from_member_effect(self.effect) {
            hints.known_effects.insert(self.binding.clone(), effect);
        }
    }
}

#[derive(Debug, Clone)]
pub(super) struct ModulePlan {
    pub(super) id: String,
    pub(super) target_file: String,
    /// Logical module path the spec asked for (e.g. `"ai/mcp/foo"`).
    /// Distinct from `target_file`, which is the chunk-relative
    /// emitted file path (e.g. `"modules/foo.js"`).
    pub(super) target_path: String,
    pub(super) explicit: bool,
    /// Local-name → public-export-name for every owned binding this
    /// plan claims (i.e. members whose `selector.binding.kind` is
    /// _not_ `ImportSpecifier`). ImportSpecifier-bound members live
    /// in `ChunkFactorization.bindings` as `BindingKind::Imported` and their
    /// emit is driven from there. Iteration order is undefined;
    /// emit / report sites sort by local name before consuming so
    /// the emitted source and JSON shapes stay deterministic.
    pub(super) bindings: HashMap<String, String>,
    /// Source-chunk statement ordinals of anonymous-statement members
    /// claimed by this module. These owners have empty
    /// `declared_bindings`, so they can't be addressed by name —
    /// the spec resolves them by AST shape (see
    /// [`spec::LogicalModule::anonymous_statements`]). The
    /// materializer routes each such statement into this module's
    /// body in source order, alongside the named members.
    pub(super) anonymous_statement_ordinals: Vec<usize>,
    /// Module-level human-readable comment from the spec, if any.
    /// Emitted at the top of the generated module file, before
    /// imports. See [`spec::LogicalModule::comment`].
    pub(super) comment: Option<String>,
    /// Local-name → per-member comment text from the spec, for the
    /// bindings this plan claims. Emitted as a `// ...` block above
    /// the binding's owner statement in the generated module body.
    /// See [`spec::Member::comment`].
    pub(super) binding_comments: BTreeMap<String, String>,
}

pub(super) fn logical_requests_for_chunk(
    chunk_logical_modules: Option<&BTreeMap<String, LogicalModule>>,
    chunk_unassigned_mode: &UnassignedMode,
    chunk_renames_present: bool,
    chunk_id: &str,
    target_dir: &str,
) -> Result<Vec<LogicalRequest>> {
    let mut requests = Vec::new();
    let catchall_target = chunk_unassigned_mode
        .catchall_file_target()
        .map(str::to_string);
    let mut explicit_module_at_catchall = false;
    if let Some(by_target_path) = chunk_logical_modules {
        for (target_path, module) in by_target_path {
            let id = format!("{chunk_id}::{target_path}");
            let members = build_members(&module.members);
            reject_duplicate_export_names("logical_module", &id, &members)?;
            reject_duplicate_member_bindings("logical_module", &id, &members)?;
            let anonymous_match_sources = module
                .anonymous_statements
                .iter()
                .map(|stmt| stmt.match_source.clone())
                .collect();
            if catchall_target.as_deref() == Some(target_path.as_str()) {
                explicit_module_at_catchall = true;
            }
            requests.push(LogicalRequest {
                id,
                target_path: target_path.clone(),
                residual: false,
                members,
                anonymous_match_sources,
                comment: module.comment.clone(),
            });
        }
    }
    // Synthesize a memberless catchall-file request when the chunk's
    // `unassigned_mode` is `CatchallFile` and no explicit logical
    // module already claims the catchall target. When an explicit
    // module *is* at the catchall target, the residual sweep in
    // `materialize_logical_chunk` will append unclaimed bindings to
    // that explicit plan instead.
    if let Some(target_path) = catchall_target
        && !explicit_module_at_catchall
    {
        requests.push(LogicalRequest {
            id: format!("{chunk_id}::residual"),
            target_path,
            residual: true,
            members: Vec::new(),
            anonymous_match_sources: Vec::new(),
            comment: None,
        });
    }
    // Fallback: when the spec is silent about this chunk (no
    // `logical_modules`, default `InlineInEntry` mode, no
    // `chunk_renames`), inject a memberless residual so the
    // materializer has at least one module to point unowned decls
    // at. Skipped when the spec has any `chunk_renames` for the
    // chunk — that signals the spec wants bindings to stay in
    // `ResidualEntry`-land (no `Logical(R)` module, no separate
    // residual file emitted), with renames applied in-place by the
    // lowerer. Skipped when `MiniFactors` is active — the
    // synthesizer takes care of placing unclaimed code into
    // mini-factor modules.
    if requests.is_empty()
        && !chunk_renames_present
        && !matches!(chunk_unassigned_mode, UnassignedMode::MiniFactors)
    {
        requests.push(LogicalRequest {
            id: format!("{chunk_id}::residual"),
            target_path: join_module_path(&[target_dir, "unhandled"]),
            residual: true,
            members: Vec::new(),
            anonymous_match_sources: Vec::new(),
            comment: None,
        });
    }
    Ok(requests)
}

pub(super) fn build_members(members: &[spec::Member]) -> Vec<MemberRequest> {
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
                effect: m.effect,
                pure_members: m.pure_members.clone(),
                comment: m.comment.clone(),
            }
        })
        .collect()
}

pub(super) fn known_effect_from_member_effect(effect: MemberEffect) -> Option<KnownEffect> {
    match effect {
        MemberEffect::Default => None,
        MemberEffect::TypescriptDecorateHelper => Some(KnownEffect::TypescriptDecorateHelper),
    }
}
