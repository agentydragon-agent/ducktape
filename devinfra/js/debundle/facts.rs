use std::collections::{BTreeMap, BTreeSet};

use binding_targets::{
    TargetAccessRecorder, binding_names, record_assign_target, record_pat_write,
    record_update_target, strip_parens,
};
use serde::{Deserialize, Serialize};
use swc_common::{Span, Spanned};
use swc_ecma_ast::*;
use swc_ecma_visit::{Visit, VisitWith};

use crate::purity::{
    ChunkCodeGraph, Purity, PurityReason, PurityRule, RedundantPureMemberHint, RedundantPurityHint,
    WHITELIST_RECEIVERS, class_has_static_observable, classify_expr_purity,
    classify_var_decl_purity, detect_redundant_pure_member_hints, detect_redundant_purity_hints,
};
use crate::{SourceLocation, StatementOrdinal};

#[derive(Debug, Clone)]
pub struct StatementFacts {
    pub ordinal: StatementOrdinal,
    pub source_location: Option<SourceLocation>,
    pub declared: BTreeSet<Id>,
    pub eager_reads: BTreeSet<Id>,
    pub eager_rebinds: BTreeSet<Id>,
    /// Reads happening only inside lazy syntactic positions (function
    /// bodies, instance class-field initializers, getters/setters,
    /// constructor bodies). May overlap with `eager_reads` if the
    /// same name appears in both eager and lazy positions of the
    /// statement.
    pub lazy_reads: BTreeSet<Id>,
    /// Rebinding writes happening only inside lazy syntactic
    /// positions. Member writes (`obj.x = ...`) are intentionally
    /// excluded: mutating an imported object is legal, but rebinding
    /// the imported binding cell is not.
    pub lazy_rebinds: BTreeSet<Id>,
    /// Subset of `lazy_reads` whose read sites sit in a function's
    /// **first-order** body (depth 1 from this statement). Used by
    /// at-init call promotion: a synchronous call to the function
    /// only runs its immediate body, so reads inside nested
    /// function/arrow definitions don't promote to the caller.
    pub first_order_lazy_reads: BTreeSet<Id>,
    /// Subset of `lazy_rebinds` whose write sites sit in a function's
    /// first-order body. See `first_order_lazy_reads`.
    pub first_order_lazy_rebinds: BTreeSet<Id>,
    /// Target-local mutations produced by recognized trusted helper
    /// calls. Each binding is the class/prototype owner that must
    /// co-locate with the mutating statement.
    pub local_effects: BTreeSet<Id>,
    /// Bare-identifier callees of `CallExpr` nodes seen at-init —
    /// i.e. outside any function/arrow/method body. Used by the
    /// owner-graph build to drive at-init call promotion: a call from
    /// statement S to chunk-declared function `f` is treated as
    /// transitively reading everything `f`'s body lazily reads. See
    /// DESIGN.md "At-init call promotion". Indirect calls
    /// (`const g = f; g()`), method calls (`obj.method()`), and
    /// computed callees are skipped — the callee must be a direct
    /// `Ident`.
    pub at_init_calls: BTreeSet<Id>,
    /// Same as `at_init_calls` but for calls inside lazy positions.
    /// Used by the owner-graph build to reconstruct the chunk call
    /// graph so that promotion can transitively follow call chains
    /// (e.g. `function f() { g(); } f();` at top level promotes
    /// through `g`'s body too).
    pub body_calls: BTreeSet<Id>,
    /// Subset of `body_calls` whose call sites sit in a function's
    /// **first-order** body. The promotion call graph uses this so
    /// that calls lexically nested inside a closure of the body
    /// don't appear as direct callees of the outer function — they
    /// don't fire when the outer function is invoked synchronously.
    pub first_order_body_calls: BTreeSet<Id>,
    /// Per-statement (writes, reads) summary used by the
    /// dataflow-aware S-chain emission in `graph.rs`. Tracks the
    /// outer-observable cells the statement touches at-init:
    /// binding cells (declared / rebound / read) and static-key
    /// `globalThis.<prop>` cells. See `dataflow_audit.md` for the
    /// soundness precondition; `effects.dataflow_summarizable=false`
    /// means the statement contains a shape we can't statically
    /// summarize (dynamic `globalThis[<expr>]`, `with`, direct
    /// `eval`, `Function(...)` constructor, etc.) and downstream
    /// passes must treat it as touching every cell.
    pub effects: StatementEffectSummary,
    pub purity: Purity,
    pub kind: StatementKind,
}

/// One outer-observable storage location a statement can read or
/// write. `EffectCell::Binding(name)` covers identifier reads
/// (`Foo` or `Foo.bar` triggers a read of `Foo`) and rebind writes;
/// `EffectCell::GlobalProp(key)` covers static-key writes/reads on
/// `globalThis` (`globalThis.tag = ...` is `GlobalProp("tag")`).
/// Dynamic-keyed accesses (`globalThis[expr]`) are deliberately not
/// representable here — statements containing them are marked
/// non-summarizable.
#[derive(Debug, Clone, Eq, PartialEq, Ord, PartialOrd)]
pub enum EffectCell {
    Binding(Id),
    GlobalProp(String),
}

#[derive(Debug, Clone, Default)]
pub struct StatementEffectSummary {
    pub writes: BTreeSet<EffectCell>,
    pub reads: BTreeSet<EffectCell>,
    pub dataflow_summarizable: bool,
}

#[derive(Debug, Clone, Copy, Eq, PartialEq)]
pub enum KnownEffect {
    TypescriptDecorateHelper,
}

#[derive(Debug, Clone, Copy, Default, Eq, PartialEq)]
pub enum LocalEffectPolicy {
    #[default]
    KnownEffectsOnly,
    VendorPrune,
}

#[derive(Debug, Clone, Default)]
pub struct AnalysisHints {
    pub declared_pure: BTreeSet<String>,
    pub declared_pure_new: BTreeSet<String>,
    /// Author-declared pure member properties — keyed by binding name,
    /// value is the set of property names whose `<binding>.<prop>(args)`
    /// calls the spec author asserts are pure. The classifier consults
    /// this to admit `<recv>.<prop>(args)` as pure when `recv` is the
    /// keyed binding and `<prop>` is in the value set.
    /// See AGENTS.md "Declared purity".
    pub declared_pure_members: BTreeMap<String, BTreeSet<String>>,
    pub known_effects: BTreeMap<String, KnownEffect>,
    pub local_effect_policy: LocalEffectPolicy,
}

impl AnalysisHints {
    pub fn from_declared_pure(declared_pure: &BTreeSet<String>) -> Self {
        Self {
            declared_pure: declared_pure.clone(),
            declared_pure_new: BTreeSet::new(),
            declared_pure_members: BTreeMap::new(),
            known_effects: BTreeMap::new(),
            local_effect_policy: LocalEffectPolicy::KnownEffectsOnly,
        }
    }
}

#[derive(Debug, Clone)]
pub struct ChunkFactAnalysis {
    pub facts: Vec<StatementFacts>,
    pub top_level_await: Option<StatementOrdinal>,
    /// Author-declared `purity: pure` spec hints the analyzer
    /// determines would be inferred automatically by recursive
    /// purity — e.g. the callee's body classifies `Pure` even
    /// without the override, or the binding admits as `PlainData`
    /// such that the callsite hint is a no-op. Surfaced so the spec
    /// author can prune the hint and shrink the trust surface.
    pub redundant_purity_hints: Vec<RedundantPurityHint>,
    /// Author-declared `pure_members: [<prop>, …]` entries the
    /// analyzer would classify pure without the hint — currently
    /// limited to `(WHITELIST_RECEIVERS, PURE_STATIC_CALLS-prop)`
    /// pairs (e.g. `pure_members: [isArray]` on a binding named
    /// `Array`). Surfaced for the same trust-surface-shrinking
    /// reason as `redundant_purity_hints`.
    pub redundant_pure_member_hints: Vec<RedundantPureMemberHint>,
}

#[derive(Debug, Clone, Copy, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum StatementKind {
    /// `var X = ...`, `let X = ...`, `const X = ...`. RHS reads at-init.
    VarDecl,
    /// `function X() { ... }`. Hoisted; no at-init reads from body.
    FnDecl,
    /// `class X { ... }`. Extends, decorators, computed keys, and
    /// static blocks read at-init.
    ClassDecl,
    /// `export { ... }`, `export X`, etc. Lazy reads (re-exports).
    Export,
    /// `import { ... } from ...`. Linked, no at-init body code.
    Import,
    /// Bare expression / control-flow / etc. that doesn't declare a
    /// top-level binding.
    SideEffect,
}

/// Walk the chunk's module body and produce one `StatementFacts`
/// entry per top-level statement, in source order.
///
/// Multi-declarator `var/let/const` statements are split into
/// per-declarator entries before analysis, so each row declares
/// a single name and owner-graph destination attribution
/// returns an unambiguous owner. Without the split, a chunk like
/// `const A = 1, B = readsX;` with `{A → mod_a, B → mod_b}`
/// would attribute `B`'s read of `X` to `mod_a` (the first
/// declared name's owner), inventing or hiding cycles. The
/// emitter splits the same comma-lists separately at lower-time
/// (`split_var_decl` in `lowering/util.rs`); this pre-split
/// just teaches the analyzer the same view.
/// Locate the first top-level `await` expression in `module`'s
/// body, if any. Returns the source-order ordinal of the offending
/// statement (in the post-comma-list-split view that
/// `analyze_chunk` uses, so reports align with statement indices
/// in `reports/tree/<chunk_id>/owner_graph.json`).
///
/// "Top-level" excludes function/method/arrow/getter/setter
/// bodies and class instance-field initializers — those are lazy
/// scopes that may legitimately contain `await` without making
/// the module a top-level-await module.
pub fn find_top_level_await(module: &Module) -> Option<StatementOrdinal> {
    let body = top_level_item_views(&module.body);
    for (ordinal, item) in body.iter().enumerate() {
        let mut finder = TopLevelAwaitFinder::default();
        item.as_module_item().visit_with(&mut finder);
        if finder.found {
            return Some(StatementOrdinal(ordinal));
        }
    }
    None
}

#[derive(Default)]
struct TopLevelAwaitFinder {
    found: bool,
}

impl Visit for TopLevelAwaitFinder {
    fn visit_await_expr(&mut self, _node: &AwaitExpr) {
        self.found = true;
    }

    // Lazy boundaries — `await` inside any of these is the body's
    // own concern (and only legal if the body is itself `async`).
    fn visit_function(&mut self, _node: &Function) {}
    fn visit_arrow_expr(&mut self, _node: &ArrowExpr) {}
    fn visit_method_prop(&mut self, _node: &MethodProp) {}
    fn visit_getter_prop(&mut self, _node: &GetterProp) {}
    fn visit_setter_prop(&mut self, _node: &SetterProp) {}

    fn visit_class_member(&mut self, member: &ClassMember) {
        visit_eager_member_parts(self, member);
    }
}

pub fn analyze_chunk<F>(
    module: &Module,
    hints: &AnalysisHints,
    source_path: Option<&str>,
    mut line_range_for_span: F,
) -> ChunkFactAnalysis
where
    F: FnMut(Span) -> Option<(usize, usize)>,
{
    let body = top_level_item_views(&module.body);
    let shadowed = compute_shadowed_globals(&body);
    let graph = ChunkCodeGraph::build_full(
        &body,
        &shadowed,
        &hints.declared_pure,
        &hints.declared_pure_new,
        &hints.declared_pure_members,
    );
    let local_effect_context = LocalEffectContext::for_body(&body, hints.local_effect_policy);
    let redundant_purity_hints =
        detect_redundant_purity_hints(&body, &shadowed, &hints.declared_pure);
    let redundant_pure_member_hints =
        detect_redundant_pure_member_hints(&hints.declared_pure_members);
    let mut top_level_await = None;
    let facts = body
        .iter()
        .enumerate()
        .map(|(ordinal, item)| {
            let item = item.as_module_item();
            if top_level_await.is_none() {
                let mut finder = TopLevelAwaitFinder::default();
                item.visit_with(&mut finder);
                if finder.found {
                    top_level_await = Some(StatementOrdinal(ordinal));
                }
            }
            let mut fact = analyze_item(
                StatementOrdinal(ordinal),
                item,
                &shadowed,
                hints,
                &graph,
                &local_effect_context,
            );
            fact.source_location = source_path.and_then(|source_path| {
                line_range_for_span(item.span()).map(|(start_line, end_line)| SourceLocation {
                    source_path: source_path.to_string(),
                    start_line,
                    end_line,
                })
            });
            // Resolve any reason spans on `fact.purity` to
            // SourceLocations using the same per-chunk line index.
            // Done after fact construction because the classifier
            // doesn't have access to the line resolver.
            if let Some(source_path) = source_path
                && let Purity::NotPure { reasons } = &mut fact.purity
            {
                for reason in reasons.iter_mut() {
                    reason.source_location =
                        line_range_for_span(reason.span).map(|(start_line, end_line)| {
                            SourceLocation {
                                source_path: source_path.to_string(),
                                start_line,
                                end_line,
                            }
                        });
                }
            }
            fact
        })
        .collect();
    ChunkFactAnalysis {
        facts,
        top_level_await,
        redundant_purity_hints,
        redundant_pure_member_hints,
    }
}

pub(crate) enum TopLevelItemView<'a> {
    Borrowed(&'a ModuleItem),
    Owned(ModuleItem),
}

impl TopLevelItemView<'_> {
    pub(crate) fn as_module_item(&self) -> &ModuleItem {
        match self {
            Self::Borrowed(item) => item,
            Self::Owned(item) => item,
        }
    }
}

/// View the top-level body as analysis statements. Multi-declarator
/// top-level `var/let/const` statements are split into N
/// single-declarator statements preserving source order; unchanged
/// statements stay borrowed so the analyzer does not clone the whole
/// app chunk just to get per-declarator ownership.
pub(crate) fn top_level_item_views(body: &[ModuleItem]) -> Vec<TopLevelItemView<'_>> {
    let mut out = Vec::with_capacity(body.len());
    for item in body {
        match item {
            ModuleItem::Stmt(Stmt::Decl(Decl::Var(var))) if var.decls.len() > 1 => {
                for decl in &var.decls {
                    let single = VarDecl {
                        span: decl.span,
                        ctxt: var.ctxt,
                        kind: var.kind,
                        declare: var.declare,
                        decls: vec![decl.clone()],
                    };
                    out.push(TopLevelItemView::Owned(ModuleItem::Stmt(Stmt::Decl(
                        Decl::Var(Box::new(single)),
                    ))));
                }
            }
            ModuleItem::ModuleDecl(ModuleDecl::ExportDecl(export_decl)) => {
                match &export_decl.decl {
                    Decl::Var(var) if var.decls.len() > 1 => {
                        for decl in &var.decls {
                            let single = VarDecl {
                                span: decl.span,
                                ctxt: var.ctxt,
                                kind: var.kind,
                                declare: var.declare,
                                decls: vec![decl.clone()],
                            };
                            out.push(TopLevelItemView::Owned(ModuleItem::ModuleDecl(
                                ModuleDecl::ExportDecl(ExportDecl {
                                    span: decl.span,
                                    decl: Decl::Var(Box::new(single)),
                                }),
                            )));
                        }
                    }
                    _ => out.push(TopLevelItemView::Borrowed(item)),
                }
            }
            _ => out.push(TopLevelItemView::Borrowed(item)),
        }
    }
    out
}

/// Walk `body` and collect the subset of `WHITELIST_RECEIVERS`
/// that are declared at the chunk's top-level scope (`var/let/const`,
/// `function`, `class`, exported decls) or bound by an import
/// specifier (default / namespace / named). The classifier consults
/// this set to skip the whitelist for any receiver the chunk
/// shadows — `const Math = …` and
/// `import { Math } from "./userland"` both make `Math.PI` an
/// Unknown read, not the global constant. See DESIGN.md A8.
pub(crate) fn compute_shadowed_globals(body: &[TopLevelItemView<'_>]) -> BTreeSet<&'static str> {
    let mut shadowed = BTreeSet::new();
    let try_shadow = |name: &str, into: &mut BTreeSet<&'static str>| {
        if let Some(global) = WHITELIST_RECEIVERS.iter().copied().find(|r| *r == name) {
            into.insert(global);
        }
    };
    for item in body {
        let item = item.as_module_item();
        for id in collect_declared_names(item) {
            try_shadow(id.0.as_ref(), &mut shadowed);
        }
        if let ModuleItem::ModuleDecl(ModuleDecl::Import(import)) = item {
            for spec in &import.specifiers {
                let local = match spec {
                    ImportSpecifier::Named(named) => named.local.sym.as_ref(),
                    ImportSpecifier::Default(default) => default.local.sym.as_ref(),
                    ImportSpecifier::Namespace(namespace) => namespace.local.sym.as_ref(),
                };
                try_shadow(local, &mut shadowed);
            }
        }
    }
    shadowed
}

fn analyze_item(
    ordinal: StatementOrdinal,
    item: &ModuleItem,
    shadowed: &BTreeSet<&'static str>,
    hints: &AnalysisHints,
    graph: &ChunkCodeGraph,
    local_effect_context: &LocalEffectContext,
) -> StatementFacts {
    let kind = classify_item(item);
    let declared = collect_declared_names(item);
    let mut collector = StatementFactsCollector::new();
    item.visit_with(&mut collector);
    let local_effects = collect_local_effects(
        item,
        &hints.known_effects,
        hints.local_effect_policy,
        local_effect_context,
    );
    let purity = item_purity(
        item,
        kind,
        shadowed,
        hints,
        graph,
        !local_effects.is_empty(),
    );
    let mut effects_writes = BTreeSet::<EffectCell>::new();
    for name in declared.iter().chain(collector.at_init_writes.iter()) {
        effects_writes.insert(EffectCell::Binding(name.clone()));
    }
    for key in &collector.global_writes {
        effects_writes.insert(EffectCell::GlobalProp(key.clone()));
    }
    let mut effects_reads = BTreeSet::<EffectCell>::new();
    for name in &collector.at_init_reads {
        effects_reads.insert(EffectCell::Binding(name.clone()));
    }
    for key in &collector.global_reads {
        effects_reads.insert(EffectCell::GlobalProp(key.clone()));
    }
    let effects = StatementEffectSummary {
        writes: effects_writes,
        reads: effects_reads,
        dataflow_summarizable: collector.dataflow_summarizable,
    };
    StatementFacts {
        ordinal,
        source_location: None,
        declared,
        eager_reads: collector.at_init_reads,
        eager_rebinds: collector.at_init_writes,
        lazy_reads: collector.lazy_reads,
        lazy_rebinds: collector.lazy_writes,
        first_order_lazy_reads: collector.first_order_lazy_reads,
        first_order_lazy_rebinds: collector.first_order_lazy_writes,
        local_effects,
        at_init_calls: collector.at_init_calls,
        body_calls: collector.lazy_calls,
        first_order_body_calls: collector.first_order_lazy_calls,
        effects,
        purity,
        kind,
    }
}

fn item_purity(
    item: &ModuleItem,
    kind: StatementKind,
    shadowed: &BTreeSet<&'static str>,
    hints: &AnalysisHints,
    graph: &ChunkCodeGraph,
    has_local_effect: bool,
) -> Purity {
    match kind {
        StatementKind::Import | StatementKind::Export | StatementKind::FnDecl => Purity::Pure,
        StatementKind::VarDecl if has_local_effect => Purity::Pure,
        StatementKind::VarDecl => var_decl_of_item(item)
            .map(|var| classify_var_decl_purity(var, shadowed, &hints.declared_pure, graph))
            .unwrap_or(Purity::Pure),
        StatementKind::ClassDecl => match class_of_item(item) {
            Some(c) if class_has_static_observable(c, shadowed, &hints.declared_pure, graph) => {
                Purity::NotPure {
                    reasons: vec![PurityReason {
                        rule: PurityRule::ClassStaticObservable,
                        span: c.span,
                        source_location: None,
                        detail: None,
                    }],
                }
            }
            _ => Purity::Pure,
        },
        StatementKind::SideEffect if has_local_effect => Purity::Pure,
        StatementKind::SideEffect => match item {
            ModuleItem::Stmt(Stmt::Expr(expr)) => {
                classify_expr_purity(&expr.expr, shadowed, &hints.declared_pure, graph)
            }
            // Bare blocks, control flow, loops, etc. — soundness-first.
            _ => Purity::NotPure {
                reasons: vec![PurityReason {
                    rule: PurityRule::BareControlFlow,
                    span: item.span(),
                    source_location: None,
                    detail: None,
                }],
            },
        },
    }
}

#[derive(Debug, Default)]
struct LocalEffectContext {
    vendor_prune_declared_bindings: BTreeSet<Id>,
    vendor_prune_commonjs_module_bindings: BTreeSet<Id>,
    vendor_prune_intrinsic_local_effect_callees: BTreeSet<Id>,
}

impl LocalEffectContext {
    fn for_body(body: &[TopLevelItemView<'_>], local_effect_policy: LocalEffectPolicy) -> Self {
        if local_effect_policy != LocalEffectPolicy::VendorPrune {
            return Self::default();
        }
        let mut context = Self::default();
        for item in body {
            context
                .vendor_prune_declared_bindings
                .extend(collect_declared_names(item.as_module_item()));
            context
                .vendor_prune_commonjs_module_bindings
                .extend(vendor_prune_commonjs_module_bindings(item.as_module_item()));
            context.vendor_prune_intrinsic_local_effect_callees.extend(
                vendor_prune_intrinsic_local_effect_aliases(item.as_module_item()),
            );
        }
        for item in body {
            context.vendor_prune_intrinsic_local_effect_callees.extend(
                vendor_prune_target_first_local_effect_wrappers(item.as_module_item(), &context),
            );
        }
        context
    }
}

fn collect_local_effects(
    item: &ModuleItem,
    known_effects: &BTreeMap<String, KnownEffect>,
    local_effect_policy: LocalEffectPolicy,
    local_effect_context: &LocalEffectContext,
) -> BTreeSet<Id> {
    let mut out = BTreeSet::new();
    if let Some(target) = recognized_local_effect_target(item, known_effects) {
        out.insert(target);
    }
    if local_effect_policy == LocalEffectPolicy::VendorPrune {
        out.extend(vendor_prune_local_effect_targets(
            item,
            local_effect_context,
        ));
    }
    out
}

fn recognized_local_effect_target(
    item: &ModuleItem,
    known_effects: &BTreeMap<String, KnownEffect>,
) -> Option<Id> {
    let ModuleItem::Stmt(Stmt::Expr(expr_stmt)) = item else {
        return None;
    };
    let Expr::Call(call) = strip_parens(&expr_stmt.expr) else {
        return None;
    };
    let callee = call_callee_ident(call)?;
    if known_effects.get(callee.sym.as_ref()) != Some(&KnownEffect::TypescriptDecorateHelper) {
        return None;
    }
    typescript_decorate_helper_target(call)
}

fn call_callee_ident(call: &CallExpr) -> Option<&Ident> {
    let Callee::Expr(callee) = &call.callee else {
        return None;
    };
    match strip_parens(callee) {
        Expr::Ident(ident) => Some(ident),
        _ => None,
    }
}

fn typescript_decorate_helper_target(call: &CallExpr) -> Option<Id> {
    if call.args.iter().any(|arg| arg.spread.is_some()) {
        return None;
    }
    match call.args.len() {
        2 => {
            if !decorator_array_is_static_reference_list(&call.args[0].expr) {
                return None;
            }
            class_or_prototype_target_binding(&call.args[1].expr)
        }
        4 => {
            if !decorator_array_is_static_reference_list(&call.args[0].expr)
                || !decorate_property_key_is_static(&call.args[2].expr)
                || !decorate_flags_are_static(&call.args[3].expr)
            {
                return None;
            }
            class_or_prototype_target_binding(&call.args[1].expr)
        }
        _ => None,
    }
}

fn vendor_prune_intrinsic_local_effect_aliases(item: &ModuleItem) -> BTreeSet<Id> {
    let Some(var) = var_decl_of_item(item) else {
        return BTreeSet::new();
    };
    var.decls
        .iter()
        .filter_map(|decl| {
            let Pat::Ident(local) = &decl.name else {
                return None;
            };
            let init = decl.init.as_deref()?;
            if vendor_prune_intrinsic_local_effect_member(init) {
                Some(local.to_id())
            } else {
                None
            }
        })
        .collect()
}

fn vendor_prune_intrinsic_local_effect_member(expr: &Expr) -> bool {
    let Expr::Member(member) = strip_parens(expr) else {
        return false;
    };
    let Expr::Ident(object) = strip_parens(&member.obj) else {
        return false;
    };
    object.sym.as_ref() == "Object"
        && static_member_name(&member.prop)
            .as_deref()
            .is_some_and(vendor_prune_object_local_effect_method)
}

fn vendor_prune_commonjs_module_bindings(item: &ModuleItem) -> BTreeSet<Id> {
    let Some(var) = var_decl_of_item(item) else {
        return BTreeSet::new();
    };
    var.decls
        .iter()
        .filter_map(|decl| {
            let Pat::Ident(local) = &decl.name else {
                return None;
            };
            let init = decl.init.as_deref()?;
            if vendor_prune_commonjs_module_init(init) {
                Some(local.to_id())
            } else {
                None
            }
        })
        .collect()
}

fn vendor_prune_commonjs_module_init(expr: &Expr) -> bool {
    let Expr::Object(obj) = strip_parens(expr) else {
        return false;
    };
    obj.props.iter().any(|prop| {
        let PropOrSpread::Prop(prop) = prop else {
            return false;
        };
        let Prop::KeyValue(kv) = &**prop else {
            return false;
        };
        static_prop_name(&kv.key).as_deref() == Some("exports")
            && matches!(strip_parens(&kv.value), Expr::Object(exports) if exports.props.is_empty())
    })
}

fn vendor_prune_target_first_local_effect_wrappers(
    item: &ModuleItem,
    local_effect_context: &LocalEffectContext,
) -> BTreeSet<Id> {
    match item {
        ModuleItem::Stmt(Stmt::Decl(Decl::Fn(function)))
        | ModuleItem::ModuleDecl(ModuleDecl::ExportDecl(ExportDecl {
            decl: Decl::Fn(function),
            ..
        })) if vendor_prune_target_first_wrapper_function(
            &function.function,
            local_effect_context,
        ) =>
        {
            BTreeSet::from([function.ident.to_id()])
        }
        _ => {
            let Some(var) = var_decl_of_item(item) else {
                return BTreeSet::new();
            };
            var.decls
                .iter()
                .filter_map(|decl| {
                    let Pat::Ident(local) = &decl.name else {
                        return None;
                    };
                    let init = decl.init.as_deref()?;
                    if vendor_prune_target_first_wrapper_expr(init, local_effect_context) {
                        Some(local.to_id())
                    } else {
                        None
                    }
                })
                .collect()
        }
    }
}

fn vendor_prune_target_first_wrapper_expr(
    expr: &Expr,
    local_effect_context: &LocalEffectContext,
) -> bool {
    match strip_parens(expr) {
        Expr::Fn(function) => {
            vendor_prune_target_first_wrapper_function(&function.function, local_effect_context)
        }
        Expr::Arrow(arrow) => {
            let Some(param) = arrow.params.first() else {
                return false;
            };
            let Pat::Ident(param) = param else {
                return false;
            };
            match &*arrow.body {
                BlockStmtOrExpr::BlockStmt(block) => vendor_prune_target_first_wrapper_block(
                    block,
                    &param.to_id(),
                    local_effect_context,
                ),
                BlockStmtOrExpr::Expr(expr) => {
                    let mut saw_effect = false;
                    vendor_prune_target_first_wrapper_effect_expr(
                        expr,
                        &param.to_id(),
                        local_effect_context,
                        &mut saw_effect,
                    ) && saw_effect
                }
            }
        }
        _ => false,
    }
}

fn vendor_prune_target_first_wrapper_function(
    function: &Function,
    local_effect_context: &LocalEffectContext,
) -> bool {
    let Some(param) = function.params.first() else {
        return false;
    };
    let Pat::Ident(param) = &param.pat else {
        return false;
    };
    let Some(body) = function.body.as_ref() else {
        return false;
    };
    vendor_prune_target_first_wrapper_block(body, &param.to_id(), local_effect_context)
}

fn vendor_prune_target_first_wrapper_block(
    block: &BlockStmt,
    target_param: &Id,
    local_effect_context: &LocalEffectContext,
) -> bool {
    let mut saw_effect = false;
    for stmt in &block.stmts {
        let ok = match stmt {
            Stmt::Decl(Decl::Var(var)) => var.decls.iter().all(vendor_prune_callback_local_var),
            Stmt::Expr(expr) => vendor_prune_target_first_wrapper_effect_expr(
                &expr.expr,
                target_param,
                local_effect_context,
                &mut saw_effect,
            ),
            Stmt::Return(ret) => ret.arg.as_ref().is_none_or(|arg| {
                vendor_prune_target_first_wrapper_effect_expr(
                    arg,
                    target_param,
                    local_effect_context,
                    &mut saw_effect,
                )
            }),
            _ => false,
        };
        if !ok {
            return false;
        }
    }
    saw_effect
}

fn vendor_prune_target_first_wrapper_effect_expr(
    expr: &Expr,
    target_param: &Id,
    local_effect_context: &LocalEffectContext,
    saw_effect: &mut bool,
) -> bool {
    match strip_parens(expr) {
        Expr::Assign(_) | Expr::Update(_) => {
            let targets = vendor_prune_expr_local_effect_targets(expr, local_effect_context);
            if !targets.is_empty() && targets.iter().all(|target| target == target_param) {
                *saw_effect = true;
                true
            } else {
                false
            }
        }
        Expr::Call(call) => {
            if vendor_prune_direct_call_local_effect_target(call, local_effect_context).as_ref()
                == Some(target_param)
            {
                *saw_effect = true;
                true
            } else {
                false
            }
        }
        Expr::Seq(seq) => seq.exprs.iter().all(|expr| {
            vendor_prune_target_first_wrapper_effect_expr(
                expr,
                target_param,
                local_effect_context,
                saw_effect,
            )
        }),
        Expr::Bin(bin) if matches!(bin.op, BinaryOp::LogicalAnd | BinaryOp::LogicalOr) => {
            vendor_prune_target_first_wrapper_branch(
                &bin.left,
                target_param,
                local_effect_context,
                saw_effect,
            ) && vendor_prune_target_first_wrapper_branch(
                &bin.right,
                target_param,
                local_effect_context,
                saw_effect,
            )
        }
        Expr::Cond(cond) if namespace_iife_local_init_is_pure(&cond.test) => {
            vendor_prune_target_first_wrapper_branch(
                &cond.cons,
                target_param,
                local_effect_context,
                saw_effect,
            ) && vendor_prune_target_first_wrapper_branch(
                &cond.alt,
                target_param,
                local_effect_context,
                saw_effect,
            )
        }
        expr => namespace_iife_local_init_is_pure(expr),
    }
}

fn vendor_prune_target_first_wrapper_branch(
    expr: &Expr,
    target_param: &Id,
    local_effect_context: &LocalEffectContext,
    saw_effect: &mut bool,
) -> bool {
    if namespace_iife_local_init_is_pure(expr) {
        true
    } else {
        vendor_prune_target_first_wrapper_effect_expr(
            expr,
            target_param,
            local_effect_context,
            saw_effect,
        )
    }
}

fn vendor_prune_object_local_effect_method(method: &str) -> bool {
    matches!(
        method,
        "assign"
            | "defineProperties"
            | "defineProperty"
            | "freeze"
            | "preventExtensions"
            | "seal"
            | "setPrototypeOf"
    )
}

fn vendor_prune_local_effect_targets(
    item: &ModuleItem,
    local_effect_context: &LocalEffectContext,
) -> BTreeSet<Id> {
    if let ModuleItem::Stmt(Stmt::Expr(expr_stmt)) = item {
        return vendor_prune_expr_local_effect_targets(&expr_stmt.expr, local_effect_context);
    }
    let Some(var) = var_decl_of_item(item) else {
        return BTreeSet::new();
    };
    var.decls
        .iter()
        .filter_map(|decl| decl.init.as_deref())
        .flat_map(|init| vendor_prune_expr_local_effect_targets(init, local_effect_context))
        .collect()
}

fn vendor_prune_expr_local_effect_targets(
    expr: &Expr,
    local_effect_context: &LocalEffectContext,
) -> BTreeSet<Id> {
    match strip_parens(expr) {
        Expr::Assign(assign) => {
            let mut recorder =
                LocalEffectRecorder::new(&local_effect_context.vendor_prune_declared_bindings);
            record_assign_target(&assign.left, &mut recorder);
            recorder.local_effects
        }
        Expr::Update(update) => {
            let mut recorder =
                LocalEffectRecorder::new(&local_effect_context.vendor_prune_declared_bindings);
            record_update_target(&update.arg, &mut recorder);
            recorder.local_effects
        }
        Expr::Call(call) => vendor_prune_call_local_effect_target(call, local_effect_context)
            .into_iter()
            .collect(),
        Expr::Seq(seq) => seq
            .exprs
            .iter()
            .flat_map(|expr| vendor_prune_expr_local_effect_targets(expr, local_effect_context))
            .collect(),
        _ => BTreeSet::new(),
    }
}

struct LocalEffectRecorder<'a> {
    local_bindings: &'a BTreeSet<Id>,
    local_effects: BTreeSet<Id>,
}

impl<'a> LocalEffectRecorder<'a> {
    fn new(local_bindings: &'a BTreeSet<Id>) -> Self {
        Self {
            local_bindings,
            local_effects: BTreeSet::new(),
        }
    }
}

impl TargetAccessRecorder for LocalEffectRecorder<'_> {
    fn record_binding_write(&mut self, id: &Id) {
        if self.local_bindings.contains(id) {
            self.local_effects.insert(id.clone());
        }
    }

    fn record_member_write(&mut self, id: &Id) {
        self.local_effects.insert(id.clone());
    }
}

fn vendor_prune_call_local_effect_target(
    call: &CallExpr,
    local_effect_context: &LocalEffectContext,
) -> Option<Id> {
    if let Some(target) = local_namespace_iife_target(call) {
        return Some(target);
    }
    if let Some(target) = local_commonjs_module_iife_target(call, local_effect_context) {
        return Some(target);
    }
    if let Some(target) = vendor_prune_for_each_local_effect_target(call, local_effect_context) {
        return Some(target);
    }
    vendor_prune_direct_call_local_effect_target(call, local_effect_context)
}

fn vendor_prune_direct_call_local_effect_target(
    call: &CallExpr,
    local_effect_context: &LocalEffectContext,
) -> Option<Id> {
    let Callee::Expr(callee) = &call.callee else {
        return None;
    };
    if let Expr::Ident(callee) = strip_parens(callee)
        && local_effect_context
            .vendor_prune_intrinsic_local_effect_callees
            .contains(&callee.to_id())
    {
        let first_arg = call.args.first()?;
        return local_member_owner(&first_arg.expr);
    }
    let Expr::Member(member) = strip_parens(callee) else {
        return None;
    };
    let Expr::Ident(object) = strip_parens(&member.obj) else {
        return None;
    };
    if object.sym.as_ref() != "Object" {
        return None;
    }
    let method = static_member_name(&member.prop)?;
    if !vendor_prune_object_local_effect_method(method.as_str()) {
        return None;
    }
    let first_arg = call.args.first()?;
    local_member_owner(&first_arg.expr)
}

fn vendor_prune_for_each_local_effect_target(
    call: &CallExpr,
    local_effect_context: &LocalEffectContext,
) -> Option<Id> {
    if call.args.len() != 1 || call.args[0].spread.is_some() {
        return None;
    }
    let Callee::Expr(callee) = &call.callee else {
        return None;
    };
    let Expr::Member(member) = strip_parens(callee) else {
        return None;
    };
    if static_member_name(&member.prop).as_deref() != Some("forEach") {
        return None;
    }
    if !vendor_prune_static_object_iteration(&member.obj) {
        return None;
    }
    single_local_effect_target(vendor_prune_for_each_callback_targets(
        &call.args[0].expr,
        local_effect_context,
    )?)
}

fn vendor_prune_static_object_iteration(expr: &Expr) -> bool {
    let Expr::Call(call) = strip_parens(expr) else {
        return false;
    };
    if call
        .args
        .iter()
        .any(|arg| arg.spread.is_some() || !namespace_iife_local_init_is_pure(&arg.expr))
    {
        return false;
    }
    let Callee::Expr(callee) = &call.callee else {
        return false;
    };
    let Expr::Member(member) = strip_parens(callee) else {
        return false;
    };
    let Expr::Ident(object) = strip_parens(&member.obj) else {
        return false;
    };
    object.sym.as_ref() == "Object"
        && matches!(
            static_member_name(&member.prop).as_deref(),
            Some("entries" | "keys" | "values")
        )
}

fn vendor_prune_for_each_callback_targets(
    expr: &Expr,
    local_effect_context: &LocalEffectContext,
) -> Option<BTreeSet<Id>> {
    match strip_parens(expr) {
        Expr::Fn(function) => vendor_prune_for_each_callback_block_targets(
            function.function.body.as_ref()?,
            local_effect_context,
        ),
        Expr::Arrow(arrow) => match &*arrow.body {
            BlockStmtOrExpr::BlockStmt(block) => {
                vendor_prune_for_each_callback_block_targets(block, local_effect_context)
            }
            BlockStmtOrExpr::Expr(expr) => {
                vendor_prune_for_each_callback_expr_targets(expr, local_effect_context)
            }
        },
        _ => None,
    }
}

fn vendor_prune_for_each_callback_block_targets(
    block: &BlockStmt,
    local_effect_context: &LocalEffectContext,
) -> Option<BTreeSet<Id>> {
    let mut targets = BTreeSet::new();
    for stmt in &block.stmts {
        match stmt {
            Stmt::Decl(Decl::Fn(_)) => {}
            Stmt::Decl(Decl::Var(var)) if var.decls.iter().all(vendor_prune_callback_local_var) => {
            }
            Stmt::Expr(expr) => {
                targets.extend(vendor_prune_for_each_callback_expr_targets(
                    &expr.expr,
                    local_effect_context,
                )?);
            }
            Stmt::Return(ret) => {
                if let Some(arg) = &ret.arg {
                    targets.extend(vendor_prune_for_each_callback_expr_targets(
                        arg,
                        local_effect_context,
                    )?);
                }
            }
            _ => return None,
        }
    }
    Some(targets)
}

fn vendor_prune_callback_local_var(decl: &VarDeclarator) -> bool {
    matches!(decl.name, Pat::Ident(_))
        && decl
            .init
            .as_deref()
            .is_none_or(namespace_iife_local_init_is_pure)
}

fn vendor_prune_for_each_callback_expr_targets(
    expr: &Expr,
    local_effect_context: &LocalEffectContext,
) -> Option<BTreeSet<Id>> {
    match strip_parens(expr) {
        Expr::Assign(_) | Expr::Update(_) => {
            let targets = vendor_prune_expr_local_effect_targets(expr, local_effect_context);
            if targets.is_empty() {
                None
            } else {
                Some(targets)
            }
        }
        Expr::Call(call) => vendor_prune_call_local_effect_target(call, local_effect_context)
            .map(|target| BTreeSet::from([target])),
        Expr::Seq(seq) => {
            let mut targets = BTreeSet::new();
            for expr in &seq.exprs {
                targets.extend(vendor_prune_for_each_callback_expr_targets(
                    expr,
                    local_effect_context,
                )?);
            }
            Some(targets)
        }
        Expr::Bin(bin) if matches!(bin.op, BinaryOp::LogicalAnd | BinaryOp::LogicalOr) => {
            let mut targets =
                vendor_prune_callback_branch_targets(&bin.left, local_effect_context)?;
            targets.extend(vendor_prune_callback_branch_targets(
                &bin.right,
                local_effect_context,
            )?);
            Some(targets)
        }
        Expr::Cond(cond) if namespace_iife_local_init_is_pure(&cond.test) => {
            let mut targets =
                vendor_prune_callback_branch_targets(&cond.cons, local_effect_context)?;
            targets.extend(vendor_prune_callback_branch_targets(
                &cond.alt,
                local_effect_context,
            )?);
            Some(targets)
        }
        expr if namespace_iife_local_init_is_pure(expr) => Some(BTreeSet::new()),
        _ => None,
    }
}

fn vendor_prune_callback_branch_targets(
    expr: &Expr,
    local_effect_context: &LocalEffectContext,
) -> Option<BTreeSet<Id>> {
    if namespace_iife_local_init_is_pure(expr) {
        Some(BTreeSet::new())
    } else {
        vendor_prune_for_each_callback_expr_targets(expr, local_effect_context)
    }
}

fn single_local_effect_target(targets: BTreeSet<Id>) -> Option<Id> {
    let mut iter = targets.into_iter();
    let target = iter.next()?;
    if iter.next().is_none() {
        Some(target)
    } else {
        None
    }
}

pub fn local_namespace_iife_target(call: &CallExpr) -> Option<Id> {
    if call.args.len() != 1 || call.args[0].spread.is_some() {
        return None;
    }
    let target = local_namespace_iife_arg_target(&call.args[0].expr)?;
    let Callee::Expr(callee) = &call.callee else {
        return None;
    };
    let Expr::Fn(function) = strip_parens(callee) else {
        return None;
    };
    if function.function.params.len() != 1 {
        return None;
    }
    let Pat::Ident(param) = &function.function.params[0].pat else {
        return None;
    };
    let body = function.function.body.as_ref()?;
    if namespace_iife_body_mutates_only_param(body, param.id.sym.as_ref()) {
        Some(target)
    } else {
        None
    }
}

fn local_namespace_iife_arg_target(expr: &Expr) -> Option<Id> {
    match strip_parens(expr) {
        Expr::Ident(ident) => Some(ident.to_id()),
        Expr::Assign(assign) if assign.op == AssignOp::Assign => {
            let AssignTarget::Simple(SimpleAssignTarget::Ident(target)) = &assign.left else {
                return None;
            };
            if matches!(strip_parens(&assign.right), Expr::Object(obj) if obj.props.is_empty()) {
                Some(target.to_id())
            } else {
                None
            }
        }
        Expr::Bin(bin) if bin.op == BinaryOp::LogicalOr => {
            let Expr::Ident(target) = strip_parens(&bin.left) else {
                return None;
            };
            if is_namespace_iife_arg_fallback_for(&bin.right, &target.to_id()) {
                Some(target.to_id())
            } else {
                None
            }
        }
        _ => None,
    }
}

fn is_namespace_iife_arg_fallback_for(expr: &Expr, target: &Id) -> bool {
    match strip_parens(expr) {
        Expr::Object(obj) => obj.props.is_empty(),
        Expr::Assign(assign) if assign.op == AssignOp::Assign => {
            matches!(
                &assign.left,
                AssignTarget::Simple(SimpleAssignTarget::Ident(ident)) if ident.to_id() == *target
            ) && matches!(strip_parens(&assign.right), Expr::Object(obj) if obj.props.is_empty())
        }
        Expr::Bin(bin) if bin.op == BinaryOp::LogicalOr => {
            matches!(strip_parens(&bin.left), Expr::Ident(ident) if ident.to_id() == *target)
                && is_namespace_iife_arg_fallback_for(&bin.right, target)
        }
        _ => false,
    }
}

fn local_commonjs_module_iife_target(
    call: &CallExpr,
    local_effect_context: &LocalEffectContext,
) -> Option<Id> {
    if call.args.len() != 1 || call.args[0].spread.is_some() {
        return None;
    }
    let target = local_namespace_iife_arg_target(&call.args[0].expr)?;
    if !local_effect_context
        .vendor_prune_commonjs_module_bindings
        .contains(&target)
    {
        return None;
    }
    let Callee::Expr(callee) = &call.callee else {
        return None;
    };
    let Expr::Fn(function) = strip_parens(callee) else {
        return None;
    };
    if function.function.params.len() != 1 {
        return None;
    }
    let Pat::Ident(param) = &function.function.params[0].pat else {
        return None;
    };
    let body = function.function.body.as_ref()?;
    if commonjs_iife_body_mutates_only_module_param(body, param.id.sym.as_ref()) {
        Some(target)
    } else {
        None
    }
}

fn commonjs_iife_body_mutates_only_module_param(block: &BlockStmt, param: &str) -> bool {
    let local_bindings = commonjs_iife_local_bindings(block);
    let mut saw_write = false;
    for stmt in &block.stmts {
        let ok = match stmt {
            Stmt::Decl(Decl::Fn(_)) => true,
            Stmt::Decl(Decl::Var(var)) => var.decls.iter().all(|decl| {
                matches!(&decl.name, Pat::Ident(_))
                    && decl
                        .init
                        .as_deref()
                        .is_none_or(namespace_iife_local_init_is_pure)
            }),
            Stmt::Expr(expr) => commonjs_iife_param_effect_expr(
                strip_parens(&expr.expr),
                param,
                &local_bindings,
                &mut saw_write,
            ),
            _ => false,
        };
        if !ok {
            return false;
        }
    }
    saw_write
}

fn commonjs_iife_local_bindings(block: &BlockStmt) -> BTreeSet<String> {
    let mut out = BTreeSet::new();
    for stmt in &block.stmts {
        match stmt {
            Stmt::Decl(Decl::Fn(function)) => {
                out.insert(function.ident.sym.to_string());
            }
            Stmt::Decl(Decl::Var(var)) => {
                out.extend(
                    var.decls
                        .iter()
                        .flat_map(|decl| binding_names(&decl.name))
                        .map(|id| id.0.to_string()),
                );
            }
            _ => {}
        }
    }
    out
}

fn commonjs_iife_param_effect_expr(
    expr: &Expr,
    param: &str,
    local_bindings: &BTreeSet<String>,
    saw_write: &mut bool,
) -> bool {
    match expr {
        Expr::Paren(paren) => {
            commonjs_iife_param_effect_expr(&paren.expr, param, local_bindings, saw_write)
        }
        Expr::Seq(seq) => seq
            .exprs
            .iter()
            .all(|expr| commonjs_iife_param_effect_expr(expr, param, local_bindings, saw_write)),
        Expr::Assign(assign) if assign.op == AssignOp::Assign => {
            let AssignTarget::Simple(SimpleAssignTarget::Member(member)) = &assign.left else {
                return false;
            };
            let Some(root) = local_member_owner(&member.obj) else {
                return false;
            };
            if static_member_name(&member.prop).as_deref() == Some("__proto__") {
                return false;
            }
            let root_name = root.0.as_ref();
            if root_name == param {
                *saw_write = true;
            } else if !local_bindings.contains(root_name) {
                return false;
            }
            namespace_iife_local_init_is_pure(&assign.right)
        }
        Expr::Call(call) => match commonjs_nested_iife_mutates_param(call, param) {
            Some(true) => {
                *saw_write = true;
                true
            }
            Some(false) => true,
            None => false,
        },
        Expr::Cond(cond) if commonjs_truthy_exports_test(&cond.test, param) => {
            commonjs_iife_param_effect_expr(&cond.cons, param, local_bindings, saw_write)
        }
        expr => namespace_iife_local_init_is_pure(expr),
    }
}

fn commonjs_nested_iife_mutates_param(call: &CallExpr, param: &str) -> Option<bool> {
    if !call.args.is_empty() {
        return None;
    }
    let Callee::Expr(callee) = &call.callee else {
        return None;
    };
    let Expr::Fn(function) = strip_parens(callee) else {
        return None;
    };
    if !function.function.params.is_empty() {
        return None;
    }
    Some(commonjs_iife_body_mutates_only_module_param(
        function.function.body.as_ref()?,
        param,
    ))
}

fn commonjs_truthy_exports_test(expr: &Expr, param: &str) -> bool {
    let Expr::Member(member) = strip_parens(expr) else {
        return false;
    };
    matches!(strip_parens(&member.obj), Expr::Ident(ident) if ident.sym.as_ref() == param)
        && static_member_name(&member.prop).as_deref() == Some("exports")
}

fn namespace_iife_body_mutates_only_param(block: &BlockStmt, param: &str) -> bool {
    let mut saw_write = false;
    for stmt in &block.stmts {
        let ok = match stmt {
            Stmt::Decl(Decl::Fn(_)) => true,
            Stmt::Decl(Decl::Var(var)) => var.decls.iter().all(|decl| {
                matches!(&decl.name, Pat::Ident(_))
                    && decl
                        .init
                        .as_deref()
                        .is_none_or(namespace_iife_local_init_is_pure)
            }),
            Stmt::Expr(expr) => {
                namespace_iife_param_write_expr(strip_parens(&expr.expr), param, &mut saw_write)
            }
            _ => false,
        };
        if !ok {
            return false;
        }
    }
    saw_write
}

fn namespace_iife_local_init_is_pure(expr: &Expr) -> bool {
    match strip_parens(expr) {
        Expr::Lit(_)
        | Expr::Ident(_)
        | Expr::This(_)
        | Expr::Fn(_)
        | Expr::Arrow(_)
        | Expr::Class(_)
        | Expr::Tpl(_)
        | Expr::PrivateName(_) => true,
        Expr::Unary(u) => {
            matches!(u.op, UnaryOp::Void | UnaryOp::TypeOf)
                || namespace_iife_local_init_is_pure(&u.arg)
        }
        Expr::Array(arr) => arr
            .elems
            .iter()
            .flatten()
            .all(|elem| elem.spread.is_none() && namespace_iife_local_init_is_pure(&elem.expr)),
        Expr::Object(obj) => obj.props.iter().all(|prop| match prop {
            PropOrSpread::Spread(_) => false,
            PropOrSpread::Prop(prop) => namespace_iife_prop_is_pure(prop),
        }),
        Expr::Member(member) => namespace_iife_local_init_is_pure(&member.obj),
        Expr::Cond(cond) => {
            namespace_iife_local_init_is_pure(&cond.test)
                && namespace_iife_local_init_is_pure(&cond.cons)
                && namespace_iife_local_init_is_pure(&cond.alt)
        }
        Expr::Bin(bin) => {
            namespace_iife_local_init_is_pure(&bin.left)
                && namespace_iife_local_init_is_pure(&bin.right)
        }
        Expr::Seq(seq) => seq
            .exprs
            .iter()
            .all(|expr| namespace_iife_local_init_is_pure(expr)),
        _ => false,
    }
}

fn namespace_iife_prop_is_pure(prop: &Prop) -> bool {
    match prop {
        Prop::Shorthand(_) => true,
        Prop::KeyValue(kv) => namespace_iife_local_init_is_pure(&kv.value),
        Prop::Method(_) | Prop::Getter(_) | Prop::Setter(_) => true,
        Prop::Assign(assign) => namespace_iife_local_init_is_pure(&assign.value),
    }
}

fn namespace_iife_param_write_expr(expr: &Expr, param: &str, saw_write: &mut bool) -> bool {
    match expr {
        Expr::Paren(paren) => namespace_iife_param_write_expr(&paren.expr, param, saw_write),
        Expr::Seq(seq) => seq
            .exprs
            .iter()
            .all(|expr| namespace_iife_param_write_expr(expr, param, saw_write)),
        Expr::Assign(assign) if assign.op == AssignOp::Assign => {
            let AssignTarget::Simple(SimpleAssignTarget::Member(member)) = &assign.left else {
                return false;
            };
            if !matches!(strip_parens(&member.obj), Expr::Ident(ident) if ident.sym.as_ref() == param)
            {
                return false;
            }
            if static_member_name(&member.prop).as_deref() == Some("__proto__") {
                return false;
            }
            *saw_write = true;
            true
        }
        _ => false,
    }
}

fn local_member_owner(expr: &Expr) -> Option<Id> {
    match strip_parens(expr) {
        Expr::Ident(ident) => Some(ident.to_id()),
        Expr::Member(member) => local_member_owner(&member.obj),
        _ => None,
    }
}

fn static_member_name(prop: &MemberProp) -> Option<String> {
    match prop {
        MemberProp::Ident(ident) => Some(ident.sym.to_string()),
        MemberProp::PrivateName(name) => Some(name.name.to_string()),
        MemberProp::Computed(computed) => match strip_parens(&computed.expr) {
            Expr::Lit(Lit::Str(value)) => Some(value.value.to_string_lossy().into_owned()),
            _ => None,
        },
    }
}

fn static_prop_name(prop: &PropName) -> Option<String> {
    match prop {
        PropName::Ident(ident) => Some(ident.sym.to_string()),
        PropName::Str(value) => Some(value.value.to_string_lossy().into_owned()),
        PropName::Num(value) => Some(value.value.to_string()),
        PropName::BigInt(value) => Some(value.value.to_string()),
        PropName::Computed(computed) => match strip_parens(&computed.expr) {
            Expr::Lit(Lit::Str(value)) => Some(value.value.to_string_lossy().into_owned()),
            _ => None,
        },
    }
}

fn decorator_array_is_static_reference_list(expr: &Expr) -> bool {
    let Expr::Array(array) = strip_parens(expr) else {
        return false;
    };
    array.elems.iter().all(|elem| {
        let Some(elem) = elem else {
            return false;
        };
        elem.spread.is_none() && static_reference_expr(&elem.expr)
    })
}

fn static_reference_expr(expr: &Expr) -> bool {
    match strip_parens(expr) {
        Expr::Ident(_) => true,
        Expr::Member(member) => {
            matches!(&member.prop, MemberProp::Ident(_))
                && static_reference_expr(member.obj.as_ref())
        }
        _ => false,
    }
}

fn class_or_prototype_target_binding(expr: &Expr) -> Option<Id> {
    match strip_parens(expr) {
        Expr::Ident(ident) => Some(ident.to_id()),
        Expr::Member(member) => {
            let MemberProp::Ident(prop) = &member.prop else {
                return None;
            };
            if prop.sym.as_ref() != "prototype" {
                return None;
            }
            match strip_parens(member.obj.as_ref()) {
                Expr::Ident(ident) => Some(ident.to_id()),
                _ => None,
            }
        }
        _ => None,
    }
}

fn decorate_property_key_is_static(expr: &Expr) -> bool {
    matches!(
        strip_parens(expr),
        Expr::Lit(Lit::Str(_)) | Expr::Lit(Lit::Num(_))
    )
}

fn decorate_flags_are_static(expr: &Expr) -> bool {
    matches!(strip_parens(expr), Expr::Lit(Lit::Num(_)))
}

fn var_decl_of_item(item: &ModuleItem) -> Option<&VarDecl> {
    match item {
        ModuleItem::Stmt(Stmt::Decl(Decl::Var(var))) => Some(var),
        ModuleItem::ModuleDecl(ModuleDecl::ExportDecl(decl)) => match &decl.decl {
            Decl::Var(var) => Some(var),
            _ => None,
        },
        _ => None,
    }
}

fn class_of_item(item: &ModuleItem) -> Option<&Class> {
    match item {
        ModuleItem::Stmt(Stmt::Decl(Decl::Class(cls))) => Some(&cls.class),
        ModuleItem::ModuleDecl(ModuleDecl::ExportDecl(decl)) => match &decl.decl {
            Decl::Class(cls) => Some(&cls.class),
            _ => None,
        },
        ModuleItem::ModuleDecl(ModuleDecl::ExportDefaultDecl(decl)) => match &decl.decl {
            DefaultDecl::Class(cls) => Some(&cls.class),
            _ => None,
        },
        _ => None,
    }
}

fn classify_item(item: &ModuleItem) -> StatementKind {
    match item {
        ModuleItem::ModuleDecl(ModuleDecl::Import(_)) => StatementKind::Import,
        ModuleItem::ModuleDecl(ModuleDecl::ExportDecl(decl)) => match &decl.decl {
            Decl::Var(_) => StatementKind::VarDecl,
            Decl::Fn(_) => StatementKind::FnDecl,
            Decl::Class(_) => StatementKind::ClassDecl,
            _ => StatementKind::Export,
        },
        ModuleItem::ModuleDecl(_) => StatementKind::Export,
        ModuleItem::Stmt(Stmt::Decl(Decl::Var(_))) => StatementKind::VarDecl,
        ModuleItem::Stmt(Stmt::Decl(Decl::Fn(_))) => StatementKind::FnDecl,
        ModuleItem::Stmt(Stmt::Decl(Decl::Class(_))) => StatementKind::ClassDecl,
        _ => StatementKind::SideEffect,
    }
}

fn collect_declared_names(item: &ModuleItem) -> BTreeSet<Id> {
    match item {
        ModuleItem::Stmt(Stmt::Decl(decl)) => declaration_names(decl),
        ModuleItem::ModuleDecl(ModuleDecl::ExportDecl(decl)) => declaration_names(&decl.decl),
        ModuleItem::ModuleDecl(ModuleDecl::ExportDefaultDecl(decl)) => match &decl.decl {
            DefaultDecl::Fn(fn_expr) => fn_expr
                .ident
                .as_ref()
                .map(|id| BTreeSet::from([id.to_id()]))
                .unwrap_or_default(),
            DefaultDecl::Class(class_expr) => class_expr
                .ident
                .as_ref()
                .map(|id| BTreeSet::from([id.to_id()]))
                .unwrap_or_default(),
            _ => BTreeSet::new(),
        },
        _ => BTreeSet::new(),
    }
}

fn declaration_names(decl: &Decl) -> BTreeSet<Id> {
    match decl {
        Decl::Var(var) => var
            .decls
            .iter()
            .flat_map(|declarator| binding_names(&declarator.name))
            .collect(),
        Decl::Fn(fn_decl) => BTreeSet::from([fn_decl.ident.to_id()]),
        Decl::Class(class_decl) => BTreeSet::from([class_decl.ident.to_id()]),
        _ => BTreeSet::new(),
    }
}

/// Shared trait for visitors that track lazy nesting depth and the
/// per-body "past first await" boundary.
///
/// Depth semantics:
/// - `0` — eager (outside any function body).
/// - `1` — first-order lazy (inside the immediate body of a function).
/// - `≥2` — nested lazy (inside a function nested in another function body).
///
/// `past_await` is a per-body flag: while visiting an async function /
/// arrow / method body, it flips `true` once an `AwaitExpr` has been
/// seen, and resets back to `false` when control exits that body.
/// Code past the first await runs in a microtask after the at-init
/// caller has finished, so it doesn't behave as "synchronously fires
/// when the function is invoked" — at-init call promotion treats it
/// like a nested closure.
///
/// At-init call promotion only inherits reads/rebinds/calls from the
/// **first-order, pre-await** part of a callee's body
/// (`lazy_depth == 1 && !past_await`), because a synchronous invocation
/// of the callee runs only that portion of the body. Statements
/// lexically inside nested function/arrow definitions or past an
/// `await` in an async body are not executed until something else
/// (the nested closure being called, or the microtask scheduler)
/// fires them. The general `lazy_*` sets stay coarse (any depth ≥1,
/// regardless of `past_await`) because, from the chunk's top-level
/// POV, any rebind inside any function body remains "lazy".
trait LazyBoundary: Visit {
    fn lazy_depth_mut(&mut self) -> &mut u32;
    fn past_await_mut(&mut self) -> &mut bool;

    fn descend_lazy<F: FnOnce(&mut Self)>(&mut self, f: F) {
        // Each body has its own `past_await` scope: a nested function
        // starts pre-await regardless of the enclosing body's state.
        let saved_past_await = std::mem::replace(self.past_await_mut(), false);
        *self.lazy_depth_mut() += 1;
        f(self);
        *self.lazy_depth_mut() -= 1;
        *self.past_await_mut() = saved_past_await;
    }
}

/// Single-pass collector producing every per-statement fact set the
/// analyzer needs. Walks the statement's AST exactly once and buckets
/// reads, rebind writes, calls, and effect-summary cells by the
/// syntactic context the cursor is in (`lazy_depth`, `past_await`).
/// Replaces the earlier five-pass design — one per fact set — which
/// each re-implemented the same `LazyBoundary` boilerplate and walked
/// the same AST.
///
/// Bucketing rules:
///
/// - `lazy_depth == 0` (eager, top of the statement): reads land in
///   `at_init_reads`, rebind writes in `at_init_writes`, direct
///   `f(...)` callees in `at_init_calls`; static-key
///   `globalThis.<prop>` accesses contribute to
///   `global_writes`/`global_reads`; bail-out shapes flip
///   `dataflow_summarizable` to `false`.
/// - `lazy_depth >= 1` (inside a function/arrow/method/getter/setter
///   body, constructor body, or instance class-field initializer):
///   reads/writes/calls land in `lazy_*`. The subset whose call sites
///   sit at `lazy_depth == 1 && !past_await` also lands in
///   `first_order_lazy_*` — used by at-init call promotion, which
///   only inherits effects from a callee's immediate pre-await body.
/// - Bail-out shapes nested inside lazy scopes are deliberately not
///   recorded: at-init call promotion handles transitive effects via
///   the call graph, not via per-statement syntactic checks.
#[derive(Default)]
struct StatementFactsCollector {
    at_init_reads: BTreeSet<Id>,
    lazy_reads: BTreeSet<Id>,
    first_order_lazy_reads: BTreeSet<Id>,
    at_init_writes: BTreeSet<Id>,
    lazy_writes: BTreeSet<Id>,
    first_order_lazy_writes: BTreeSet<Id>,
    at_init_calls: BTreeSet<Id>,
    lazy_calls: BTreeSet<Id>,
    first_order_lazy_calls: BTreeSet<Id>,
    global_writes: BTreeSet<String>,
    global_reads: BTreeSet<String>,
    dataflow_summarizable: bool,
    lazy_depth: u32,
    past_await: bool,
}

impl StatementFactsCollector {
    fn new() -> Self {
        Self {
            dataflow_summarizable: true,
            ..Self::default()
        }
    }

    fn record_read(&mut self, id: &Id) {
        if self.lazy_depth == 0 {
            self.at_init_reads.insert(id.clone());
            return;
        }
        self.lazy_reads.insert(id.clone());
        if self.lazy_depth == 1 && !self.past_await {
            self.first_order_lazy_reads.insert(id.clone());
        }
    }

    fn record_write(&mut self, id: &Id) {
        if self.lazy_depth == 0 {
            self.at_init_writes.insert(id.clone());
            return;
        }
        self.lazy_writes.insert(id.clone());
        if self.lazy_depth == 1 && !self.past_await {
            self.first_order_lazy_writes.insert(id.clone());
        }
    }

    fn record_call(&mut self, id: &Id) {
        if self.lazy_depth == 0 {
            self.at_init_calls.insert(id.clone());
            return;
        }
        self.lazy_calls.insert(id.clone());
        if self.lazy_depth == 1 && !self.past_await {
            self.first_order_lazy_calls.insert(id.clone());
        }
    }

    fn bail_summarizable(&mut self) {
        self.dataflow_summarizable = false;
    }

    fn record_global_prop(&mut self, member: &MemberExpr, is_write: bool) {
        if !is_global_this_expr(&member.obj) {
            return;
        }
        let key = match &member.prop {
            MemberProp::Ident(ident) => Some(ident.sym.to_string()),
            MemberProp::Computed(ComputedPropName { expr, .. }) => match strip_parens(expr) {
                Expr::Lit(Lit::Str(s)) => Some(s.value.to_string_lossy().into_owned()),
                _ => {
                    self.bail_summarizable();
                    return;
                }
            },
            MemberProp::PrivateName(_) => None,
        };
        if let Some(key) = key {
            if is_write {
                self.global_writes.insert(key);
            } else {
                self.global_reads.insert(key);
            }
        }
    }
}

impl LazyBoundary for StatementFactsCollector {
    fn lazy_depth_mut(&mut self) -> &mut u32 {
        &mut self.lazy_depth
    }
    fn past_await_mut(&mut self) -> &mut bool {
        &mut self.past_await
    }
}

impl TargetAccessRecorder for StatementFactsCollector {
    fn record_binding_write(&mut self, id: &Id) {
        self.record_write(id);
    }
}

impl Visit for StatementFactsCollector {
    fn visit_ident(&mut self, node: &Ident) {
        self.record_read(&node.to_id());
    }

    fn visit_binding_ident(&mut self, _node: &BindingIdent) {}
    fn visit_import_decl(&mut self, _node: &ImportDecl) {}

    // Export specifiers (`export { X }`, `export * from ...`) don't
    // fire at-init reads: ESM resolves the binding when a consumer's
    // `import` references it. But the materializer's routing layer
    // treats a re-exported binding's destination as a lazy
    // dependency: if the binding moves to a different module, the
    // emitter inserts `import { X } from <new home>` at the top of
    // this chunk's entry to keep the export surface intact. The
    // realizability primitive's I-graph cycle check needs to see
    // that materializer-induced lazy import edge, so record each
    // `orig` Ident as a LAZY read (placed directly into `lazy_reads`,
    // bypassing `record_read`'s lazy-depth bucketing — these reads
    // are semantically deferred regardless of where the export
    // specifier sits syntactically). Not added to
    // `first_order_lazy_reads`: re-exports aren't reachable through
    // at-init call promotion, so excluding them from that subset
    // prevents the promotion pass from inventing spurious eager
    // edges for re-exported bindings.
    //
    // `export { X } from "./foo"` (with `src.is_some()`) is a
    // different shape: the binding lives in `./foo`, not in this
    // chunk; the `import`-side dep is captured by the import-decl
    // path, not via specifier reads here.
    fn visit_named_export(&mut self, node: &NamedExport) {
        if node.src.is_some() {
            return;
        }
        for specifier in &node.specifiers {
            let ExportSpecifier::Named(named) = specifier else {
                continue;
            };
            if let ModuleExportName::Ident(ident) = &named.orig {
                self.lazy_reads.insert(ident.to_id());
            }
        }
    }
    fn visit_export_all(&mut self, _node: &ExportAll) {}

    fn visit_await_expr(&mut self, node: &AwaitExpr) {
        // The awaited operand runs to completion (synchronously)
        // before the engine suspends; visit its children first and
        // flip `past_await` only after, so the pre-await reads/writes
        // still count as first-order.
        node.visit_children_with(self);
        self.past_await = true;
    }

    fn visit_assign_expr(&mut self, node: &AssignExpr) {
        record_assign_target(&node.left, self);
        if self.lazy_depth == 0
            && let AssignTarget::Simple(SimpleAssignTarget::Member(member)) = &node.left
        {
            self.record_global_prop(member, /*is_write=*/ true);
        }
        node.left.visit_with(self);
        node.right.visit_with(self);
    }

    fn visit_update_expr(&mut self, node: &UpdateExpr) {
        record_update_target(&node.arg, self);
        node.arg.visit_with(self);
    }

    fn visit_for_in_stmt(&mut self, node: &ForInStmt) {
        if let ForHead::Pat(pattern) = &node.left {
            record_pat_write(pattern, self);
        }
        node.left.visit_with(self);
        node.right.visit_with(self);
        node.body.visit_with(self);
    }

    fn visit_for_of_stmt(&mut self, node: &ForOfStmt) {
        if let ForHead::Pat(pattern) = &node.left {
            record_pat_write(pattern, self);
        }
        node.left.visit_with(self);
        node.right.visit_with(self);
        node.body.visit_with(self);
    }

    fn visit_call_expr(&mut self, node: &CallExpr) {
        if let Some(callee) = call_callee_ident(node) {
            self.record_call(&callee.to_id());
        }
        if self.lazy_depth == 0 {
            if let Callee::Expr(expr) = &node.callee
                && let Expr::Ident(ident) = strip_parens(expr)
            {
                match ident.sym.as_ref() {
                    "eval" | "Function" => self.bail_summarizable(),
                    _ => {}
                }
            }
            if let Callee::Expr(expr) = &node.callee
                && let Expr::Member(member) = strip_parens(expr)
                && let MemberProp::Ident(prop) = &member.prop
                && prop.sym.as_ref() == "defineProperty"
                && matches!(
                    strip_parens(&member.obj),
                    Expr::Ident(i) if matches!(i.sym.as_ref(), "Object" | "Reflect")
                )
                && node
                    .args
                    .first()
                    .is_some_and(|a| is_global_this_expr(&a.expr))
            {
                self.bail_summarizable();
            }
        }
        node.visit_children_with(self);
    }

    fn visit_new_expr(&mut self, node: &NewExpr) {
        if self.lazy_depth == 0
            && let Expr::Ident(ident) = strip_parens(&node.callee)
        {
            match ident.sym.as_ref() {
                "Function" => self.bail_summarizable(),
                "Proxy" => {
                    let proxies_global = node
                        .args
                        .as_ref()
                        .and_then(|args| args.first())
                        .is_some_and(|a| is_global_this_expr(&a.expr));
                    if proxies_global {
                        self.bail_summarizable();
                    }
                }
                _ => {}
            }
        }
        node.visit_children_with(self);
    }

    fn visit_member_expr(&mut self, node: &MemberExpr) {
        if self.lazy_depth == 0 {
            self.record_global_prop(node, /*is_write=*/ false);
        }
        node.visit_children_with(self);
    }

    fn visit_with_stmt(&mut self, node: &WithStmt) {
        if self.lazy_depth == 0 {
            self.bail_summarizable();
        }
        node.visit_children_with(self);
    }

    fn visit_function(&mut self, node: &Function) {
        lazy_visit_function(self, node);
    }
    fn visit_arrow_expr(&mut self, node: &ArrowExpr) {
        lazy_visit_arrow_expr(self, node);
    }
    fn visit_method_prop(&mut self, node: &MethodProp) {
        lazy_visit_method_prop(self, node);
    }
    fn visit_getter_prop(&mut self, node: &GetterProp) {
        lazy_visit_getter_prop(self, node);
    }
    fn visit_setter_prop(&mut self, node: &SetterProp) {
        lazy_visit_setter_prop(self, node);
    }
    fn visit_class(&mut self, node: &Class) {
        lazy_visit_class(self, node);
    }
    fn visit_class_member(&mut self, member: &ClassMember) {
        lazy_visit_class_member(self, member);
    }
}

fn is_global_this_expr(expr: &Expr) -> bool {
    matches!(strip_parens(expr), Expr::Ident(i) if i.sym.as_ref() == "globalThis")
}

fn lazy_visit_function<V: LazyBoundary>(v: &mut V, node: &Function) {
    v.descend_lazy(|s| node.visit_children_with(s));
}

fn lazy_visit_arrow_expr<V: LazyBoundary>(v: &mut V, node: &ArrowExpr) {
    v.descend_lazy(|s| node.visit_children_with(s));
}

fn lazy_visit_method_prop<V: LazyBoundary>(v: &mut V, node: &MethodProp) {
    node.key.visit_with(v);
    // `node.function.visit_with` dispatches to `visit_function`, which
    // already calls `descend_lazy` via `lazy_visit_function`. No outer
    // descend here — the method body must land at lazy_depth 1, the
    // same as a bare `function f() { ... }`.
    node.function.visit_with(v);
}

fn lazy_visit_getter_prop<V: LazyBoundary>(v: &mut V, node: &GetterProp) {
    node.key.visit_with(v);
    v.descend_lazy(|s| {
        if let Some(body) = &node.body {
            body.visit_with(s);
        }
    });
}

fn lazy_visit_setter_prop<V: LazyBoundary>(v: &mut V, node: &SetterProp) {
    node.key.visit_with(v);
    node.param.visit_with(v);
    v.descend_lazy(|s| {
        if let Some(body) = &node.body {
            body.visit_with(s);
        }
    });
}

fn lazy_visit_class<V: LazyBoundary>(v: &mut V, node: &Class) {
    visit_class_decl(v, node, |v, m| v.visit_class_member(m));
}

fn lazy_visit_class_member<V: LazyBoundary>(v: &mut V, member: &ClassMember) {
    visit_eager_member_parts(v, member);
    match member {
        // `method.function.visit_with` dispatches to `visit_function`,
        // which already calls `descend_lazy` via `lazy_visit_function`.
        // No outer descend here — a method body must land at
        // lazy_depth 1, the same as a bare `function f() { ... }`,
        // so rebinds in the immediate body show up in
        // `first_order_lazy_rebinds` and the owner-graph emits the
        // constraining `LazyRebind` edge that catches cross-module
        // writes to imported bindings (ESM rejects at runtime).
        ClassMember::Method(method) => {
            method.function.visit_with(v);
        }
        ClassMember::PrivateMethod(method) => {
            method.function.visit_with(v);
        }
        ClassMember::Constructor(ctor) => {
            v.descend_lazy(|s| ctor.visit_children_with(s));
        }
        ClassMember::ClassProp(prop) if !prop.is_static => {
            if let Some(value) = &prop.value {
                v.descend_lazy(|s| value.visit_with(s));
            }
        }
        ClassMember::PrivateProp(prop) if !prop.is_static => {
            if let Some(value) = &prop.value {
                v.descend_lazy(|s| value.visit_with(s));
            }
        }
        ClassMember::AutoAccessor(accessor) if !accessor.is_static => {
            if let Some(value) = &accessor.value {
                v.descend_lazy(|s| value.visit_with(s));
            }
        }
        _ => {}
    }
}

fn visit_computed_prop_name<V: Visit>(v: &mut V, name: &PropName) {
    if let PropName::Computed(computed) = name {
        computed.expr.visit_with(v);
    }
}

fn visit_class_decl<V: Visit>(
    v: &mut V,
    node: &Class,
    mut visit_member: impl FnMut(&mut V, &ClassMember),
) {
    for decorator in &node.decorators {
        decorator.visit_with(v);
    }
    if let Some(super_class) = &node.super_class {
        super_class.visit_with(v);
    }
    for member in &node.body {
        visit_member(v, member);
    }
}

fn visit_eager_member_parts<V: Visit>(v: &mut V, member: &ClassMember) {
    match member {
        ClassMember::Method(method) => {
            visit_computed_prop_name(v, &method.key);
        }
        ClassMember::PrivateMethod(_) | ClassMember::Constructor(_) => {}
        ClassMember::ClassProp(prop) => {
            visit_computed_prop_name(v, &prop.key);
            if prop.is_static {
                if let Some(value) = &prop.value {
                    value.visit_with(v);
                }
            }
        }
        ClassMember::PrivateProp(prop) => {
            if prop.is_static {
                if let Some(value) = &prop.value {
                    value.visit_with(v);
                }
            }
        }
        ClassMember::StaticBlock(block) => {
            block.visit_with(v);
        }
        ClassMember::TsIndexSignature(_) | ClassMember::Empty(_) => {}
        ClassMember::AutoAccessor(accessor) => {
            if let Key::Public(name) = &accessor.key {
                visit_computed_prop_name(v, name);
            }
            if accessor.is_static {
                if let Some(value) = &accessor.value {
                    value.visit_with(v);
                }
            }
        }
    }
}
