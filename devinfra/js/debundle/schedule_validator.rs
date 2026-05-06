//! Static schedule validation for `materialize_logical_modules`.
//!
//! Background: see <DESIGN.md>. This module is the validator core
//! of the principled debundler design. It treats debundling as an
//! owner-graph quotient and scheduling problem:
//!
//! 1. For each top-level statement in the source chunk, compute the
//!    bindings it declares, the bindings it reads at-init, the
//!    bindings it reads lazily (inside function/method bodies, etc.),
//!    whether it has an observable side effect, and its source
//!    ordinal.
//! 2. Build a fine-grained owner graph over those statements.
//!    Owner edges record "this owner reads that binding" and
//!    side-effect source-order constraints before module grouping.
//! 3. Map each owner to its destination module (logical module or
//!    residual entry) using the spec's binding assignment.
//! 4. Quotient the owner graph by destination to derive the
//!    module-level imports graph `I` plus side-effect graph `S`.
//!    Each quotient `I` edge corresponds to an emitted `import`
//!    directive — `I` is exactly the graph the ESM linker walks
//!    for evaluation order.
//! 5. Validate: every `I ∪ S` SCC must be realizable. Lazy-only
//!    SCCs are allowed; SCCs with an at-init read or side-effect
//!    ordering edge are unrealizable. `materialize_logical_modules`
//!    aborts when this validator reports such cycles.
//!
//! The output is a JSON report listing the cycles + their evidence
//! (which `(statement, binding)` pairs form each cycle). The report
//! is written next to the existing manifests as
//! `<chunk_id>/schedule.json`.

#[path = "schedule_validator/report_schema.rs"]
pub mod report_schema;

pub use report_schema::*;

use std::collections::{BTreeMap, BTreeSet, HashMap, HashSet, VecDeque};

use petgraph::algo::{greedy_feedback_arc_set, tarjan_scc, toposort};
use petgraph::graph::DiGraph;
use petgraph::graphmap::DiGraphMap;
use petgraph::visit::EdgeRef;
use serde::{Deserialize, Serialize};
use swc_common::{Span, Spanned};
use swc_ecma_ast::*;
use swc_ecma_visit::{Visit, VisitWith};

/// Index into the materializer's `module_plans` list, identifying a
/// logical module produced by the spec.
#[derive(Debug, Clone, Copy, Eq, PartialEq, Ord, PartialOrd, Hash)]
pub struct LogicalModuleIndex(pub usize);

/// Identity of a module the schedule validator reasons about. The
/// residual entry is a first-class variant rather than a sentinel
/// index, so callers can't accidentally treat it as a normal logical
/// module.
#[derive(Debug, Clone, Copy, Eq, PartialEq, Ord, PartialOrd, Hash)]
pub enum ModuleId {
    Logical(LogicalModuleIndex),
    ResidualEntry,
}

/// Position of a top-level statement in a chunk's source body.
#[derive(Debug, Clone, Copy, Eq, PartialEq, Ord, PartialOrd, Hash, Serialize, Deserialize)]
#[serde(transparent)]
pub struct StatementOrdinal(pub usize);

/// Local name of a binding in a chunk's top-level scope. Stays a
/// plain `String` (the actual JavaScript identifier text); the alias
/// is documentation. See DESIGN.md "Identifiers and types".
pub type BindingName = String;

/// How a top-level binding in the chunk relates to the split. See
/// DESIGN.md "Two binding kinds".
#[derive(Debug, Clone)]
pub enum BindingKind {
    /// Declared by a top-level `var/let/const/function/class` in this
    /// chunk; the spec assigns it to a logical module (or the
    /// residual entry).
    Owned { owner: ModuleId },
    /// Introduced by an `import { imported_name as <local> } from
    /// "<source>"` in the chunk's top-level body. The value lives in
    /// another chunk; logical modules can re-export it under their
    /// own public name. Multiple modules may re-export the same
    /// imported binding (under different public names).
    Imported {
        /// The original imported name from the source chunk (e.g. "j"
        /// for `import { j as a } from "..."`).
        imported_name: BindingName,
        /// Output-tree-rooted absolute path of the import source
        /// (e.g. `"static/vendor.js"`). Already resolved against the
        /// chunk's directory + the artifact's source-chunk index;
        /// emit-time path resolution is just `relative(dest_dir,
        /// imported_from)`.
        imported_from: String,
        /// `module → public export name` for each logical module that
        /// re-exports this binding. Empty when no logical module
        /// re-exports it (read-only references stay implicit and are
        /// resolved by `source_chunk_imports_for_moved_body`).
        re_exported_by: BTreeMap<ModuleId, BindingName>,
    },
}

/// A logical module produced by the spec for the current chunk.
/// Projection of `ModulePlan` carrying the fields downstream emit
/// helpers consume (`cross_module_imports_for_body`,
/// `source_chunk_imports_for_moved_body`, etc.).
#[derive(Debug, Clone)]
pub struct LogicalModule {
    pub id: String,
    /// Chunk-relative path the module emits to (e.g. `"runtime/foo.js"`).
    pub target_file: String,
    /// True for the generated residual catch-all module. Peelability
    /// diagnostics use this to identify the remaining unpeeled owner
    /// set.
    pub residual: bool,
    /// Local-name → exported-name map for the bindings this module
    /// owns. Empty when the module re-exports only imported
    /// bindings.
    pub rename_map: BTreeMap<BindingName, BindingName>,
}

/// Single per-chunk schedule. Carries everything downstream code
/// needs to validate cycles and emit modules in an order that
/// respects `I ∪ S`.
#[derive(Debug, Clone)]
pub struct Schedule {
    pub chunk_id: String,
    pub facts: Vec<StatementFacts>,
    pub bindings: BTreeMap<BindingName, BindingKind>,
    pub logical_modules: Vec<LogicalModule>,
    pub chunk_renames: BTreeMap<BindingName, BindingName>,
    pub owner_graph: OwnerGraph,
    pub dep_graph: ModuleDepGraph,
    owner_report_ids_by_binding: BTreeMap<BindingName, Vec<String>>,
    /// Topological linearization of `I ∪ S`, dependency-first
    /// (the module at index 0 must evaluate before any other; the
    /// last module — typically the residual entry — evaluates
    /// last). Empty when `dep_graph` has cycles (validation will
    /// reject the spec). Used by the emitter to author each
    /// module's `import` directive list in an order that steers
    /// ECMA-262's linker DFS toward an `I ∪ S`-respecting
    /// evaluation order; see DESIGN.md "Lemma 2".
    pub linker_order: Vec<ModuleId>,
}

impl Schedule {
    /// Build a schedule from chunk facts + the binding catalogue +
    /// spec-derived logical modules. `bindings` should already have
    /// every `Owned` binding the spec assigned and every `Imported`
    /// binding the spec re-exports.
    pub fn build(
        chunk_id: String,
        facts: Vec<StatementFacts>,
        bindings: BTreeMap<BindingName, BindingKind>,
        logical_modules: Vec<LogicalModule>,
        chunk_renames: BTreeMap<BindingName, BindingName>,
    ) -> Self {
        let ownership = owned_view(&bindings);
        let owner_graph = build_owner_graph(&facts, &ownership);
        let owner_report_ids_by_binding = Self::build_owner_report_ids_by_binding(&owner_graph);
        let dep_graph = quotient_owner_graph(&owner_graph);
        let linker_order = compute_linker_order(&dep_graph, &logical_modules);
        Self {
            chunk_id,
            facts,
            bindings,
            logical_modules,
            chunk_renames,
            owner_graph,
            dep_graph,
            owner_report_ids_by_binding,
            linker_order,
        }
    }

    /// Position of `id` in `linker_order`, if present. Used by the
    /// emitter to sort each module's `import` directives so that
    /// ECMA-262's depth-first link traversal evaluates dependencies
    /// before dependents.
    pub fn linker_position(&self, id: ModuleId) -> Option<usize> {
        self.linker_order.iter().position(|&m| m == id)
    }

    /// Render `id` to a human-readable label (used in cycle reports).
    pub fn module_name(&self, id: ModuleId) -> String {
        match id {
            ModuleId::ResidualEntry => "<residual_entry>".to_string(),
            ModuleId::Logical(LogicalModuleIndex(idx)) => self
                .logical_modules
                .get(idx)
                .map(|m| m.id.clone())
                .unwrap_or_else(|| format!("<module#{idx}>")),
        }
    }

    /// Which logical module owns a binding (by local name), if any.
    /// Returns `None` for names that aren't `Owned` in this schedule
    /// (e.g. globals, imported bindings, names not in the spec).
    pub fn owner_of(&self, name: &str) -> Option<ModuleId> {
        self.bindings.get(name).and_then(|kind| match kind {
            BindingKind::Owned { owner } => Some(*owner),
            BindingKind::Imported { .. } => None,
        })
    }

    /// Lookup a logical module by index.
    pub fn logical_module(&self, idx: LogicalModuleIndex) -> Option<&LogicalModule> {
        self.logical_modules.get(idx.0)
    }

    pub fn owner_report_ids_for_bindings<'a>(
        &self,
        names: impl IntoIterator<Item = &'a str>,
    ) -> Vec<String> {
        names
            .into_iter()
            .filter_map(|name| self.owner_report_ids_by_binding.get(name))
            .flat_map(|ids| ids.iter().cloned())
            .collect::<BTreeSet<_>>()
            .into_iter()
            .collect()
    }

    fn build_owner_report_ids_by_binding(
        owner_graph: &OwnerGraph,
    ) -> BTreeMap<BindingName, Vec<String>> {
        let mut by_binding = BTreeMap::<BindingName, BTreeSet<String>>::new();
        for node in owner_graph.nodes.values() {
            let report_id = owner_key(node.id);
            for binding in &node.declared {
                by_binding
                    .entry(binding.clone())
                    .or_default()
                    .insert(report_id.clone());
            }
        }
        by_binding
            .into_iter()
            .map(|(binding, ids)| (binding, ids.into_iter().collect()))
            .collect()
    }

    /// Run SCC analysis over the dep graph. Spec authors consume the
    /// resulting report to fix any cycles.
    pub fn validate(&self) -> ScheduleReport {
        let mut report = validate_schedule(&self.dep_graph, &|id| self.module_name(id));
        report.linker_order = self
            .linker_order
            .iter()
            .map(|id| self.module_name(*id))
            .collect();
        report
    }

    /// High-fidelity node-link view of the fine owner graph plus
    /// its current module quotient. Written as
    /// `<chunk_id>/owner_graph.json` for downstream peel tooling.
    pub fn owner_graph_report(&self) -> OwnerGraphReport {
        build_owner_graph_report(self)
    }
}

#[derive(Debug, Clone)]
pub struct StatementFacts {
    pub ordinal: StatementOrdinal,
    pub source_location: Option<SourceLocation>,
    pub declared: BTreeSet<BindingName>,
    pub reads_at_init: BTreeSet<BindingName>,
    /// Reads happening only inside lazy syntactic positions (function
    /// bodies, instance class-field initializers, getters/setters,
    /// constructor bodies). May overlap with `reads_at_init` if the
    /// same name appears in both eager and lazy positions of the
    /// statement.
    pub reads_lazy: BTreeSet<BindingName>,
    pub has_side_effect: bool,
    pub kind: StatementKind,
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
/// (`split_var_decl` in `logical_modules.rs`); this pre-split
/// just teaches the analyzer the same view.
/// Locate the first top-level `await` expression in `module`'s
/// body, if any. Returns the source-order ordinal of the offending
/// statement (in the post-comma-list-split view that
/// `analyze_chunk_facts` uses, so reports align with statement
/// indices in `<chunk_id>/schedule.json`).
///
/// "Top-level" excludes function/method/arrow/getter/setter
/// bodies and class instance-field initializers — those are lazy
/// scopes that may legitimately contain `await` without making
/// the module a top-level-await module.
pub fn find_top_level_await(module: &Module) -> Option<StatementOrdinal> {
    let body = split_comma_list_var_decls(&module.body);
    for (ordinal, item) in body.iter().enumerate() {
        let mut finder = TopLevelAwaitFinder::default();
        item.visit_with(&mut finder);
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

    // Class-member handling mirrors `AtInitReadCollector::visit_class_member`:
    //   - computed property keys are eager (evaluated at class-decl
    //     time) regardless of `is_static`;
    //   - `is_static` field initializers + static blocks are eager;
    //   - instance field initializers are evaluated per-`new`, so
    //     they're lazy from the class-decl's POV;
    //   - method bodies are functions and the `visit_function`
    //     override above keeps them lazy.
    fn visit_class_member(&mut self, member: &ClassMember) {
        match member {
            ClassMember::Method(method) => {
                self.visit_prop_name(&method.key);
            }
            ClassMember::PrivateMethod(_) => {}
            ClassMember::Constructor(_) => {}
            ClassMember::ClassProp(prop) => {
                self.visit_prop_name(&prop.key);
                if prop.is_static
                    && let Some(value) = &prop.value
                {
                    value.visit_with(self);
                }
            }
            ClassMember::PrivateProp(prop) => {
                if prop.is_static
                    && let Some(value) = &prop.value
                {
                    value.visit_with(self);
                }
            }
            ClassMember::StaticBlock(block) => {
                block.visit_with(self);
            }
            ClassMember::TsIndexSignature(_) | ClassMember::Empty(_) => {}
            ClassMember::AutoAccessor(accessor) => {
                if let Key::Public(name) = &accessor.key {
                    self.visit_prop_name(name);
                }
                if accessor.is_static
                    && let Some(value) = &accessor.value
                {
                    value.visit_with(self);
                }
            }
        }
    }

    fn visit_prop_name(&mut self, name: &PropName) {
        if let PropName::Computed(computed) = name {
            computed.expr.visit_with(self);
        }
    }
}

pub fn analyze_chunk_facts(
    module: &Module,
    declared_pure: &BTreeSet<String>,
) -> Vec<StatementFacts> {
    analyze_chunk_facts_with_source_locations(module, declared_pure, None, |_| None)
}

pub fn analyze_chunk_facts_with_source_locations<F>(
    module: &Module,
    declared_pure: &BTreeSet<String>,
    source_path: Option<&str>,
    mut line_range_for_span: F,
) -> Vec<StatementFacts>
where
    F: FnMut(Span) -> Option<(usize, usize)>,
{
    let body = split_comma_list_var_decls(&module.body);
    let shadowed = compute_shadowed_globals(&body);
    let graph = ChunkCodeGraph::build(&body, &shadowed, declared_pure);
    body.iter()
        .enumerate()
        .map(|(ordinal, item)| {
            let mut fact = analyze_item(
                StatementOrdinal(ordinal),
                item,
                &shadowed,
                declared_pure,
                &graph,
            );
            fact.source_location = source_path.and_then(|source_path| {
                line_range_for_span(item.span()).map(|(start_line, end_line)| SourceLocation {
                    source_path: source_path.to_string(),
                    start_line,
                    end_line,
                })
            });
            fact
        })
        .collect()
}

/// Chunk-wide code graph: indexes top-level bindings and answers
/// queries the classifier needs that go beyond per-expression
/// inspection. Currently exposes function-body purity for
/// chunk-local Ident callees (used by `classify_call_purity` to
/// short-circuit `Pure` callees). Designed to grow into a fuller
/// binding-shape model — import provenance, var-init purity,
/// class shape, etc. — as further analyses land. New binding
/// kinds add new `ChunkBinding` variants and matching query
/// methods; the iteration in `ChunkCodeGraph::build` extends to
/// them naturally.
#[derive(Debug, Default, Clone)]
pub struct ChunkCodeGraph {
    bindings: BTreeMap<String, ChunkBinding>,
}

#[derive(Debug, Clone)]
enum ChunkBinding {
    /// Chunk-top function declaration or `const f = function/arrow`.
    /// `purity` is the worst purity reachable from the body, computed
    /// by fixed-point iteration over all chunk-top functions.
    Function { purity: Purity },
}

impl ChunkCodeGraph {
    /// Build the graph for `body`. Two phases:
    ///
    /// 1. **Call-graph construction.** For each chunk-top function,
    ///    walk its body and collect the set of other chunk-top
    ///    functions it calls (Ident-callee form only). Edges:
    ///    caller → callee.
    /// 2. **SCC-bottom-up classification.** Decompose the call
    ///    graph into strongly-connected components via
    ///    `petgraph::algo::tarjan_scc` (returns SCCs in reverse
    ///    topological order — sinks first). Process each SCC in
    ///    order, so by the time we classify a caller, every
    ///    callee outside the caller's own SCC is already
    ///    finalized. Within an SCC (the only place mutual
    ///    recursion shows up), iterate via a worklist: re-classify
    ///    a function only when one of its same-SCC callees has
    ///    changed. Each function in an SCC is reclassified at
    ///    most twice (`Pure → Unknown` or `Pure → Impure`, both
    ///    terminal), so per-SCC work is `O(scc_size · body_size)`,
    ///    and total work is `O(N · body_size)` for the whole
    ///    chunk regardless of recursion depth.
    fn build(
        body: &[ModuleItem],
        shadowed: &BTreeSet<&'static str>,
        declared_pure: &BTreeSet<String>,
    ) -> Self {
        let functions = collect_chunk_functions(body);
        let name_to_idx: BTreeMap<&str, usize> = functions
            .iter()
            .enumerate()
            .map(|(i, f)| (f.name.as_str(), i))
            .collect();

        // Phase 1: call edges.
        let mut call_graph: DiGraphMap<usize, ()> = DiGraphMap::new();
        let mut callees_of: Vec<BTreeSet<usize>> = vec![BTreeSet::new(); functions.len()];
        for (i, function) in functions.iter().enumerate() {
            call_graph.add_node(i);
            let mut collector = CallCollector {
                callees: BTreeSet::new(),
                name_to_idx: &name_to_idx,
            };
            function.visit_body_with(&mut collector);
            for &callee in &collector.callees {
                call_graph.add_edge(i, callee, ());
            }
            callees_of[i] = collector.callees;
        }

        // Phase 2: optimistic init + SCC-bottom-up classification.
        let mut graph = ChunkCodeGraph {
            bindings: functions
                .iter()
                .map(|f| {
                    (
                        f.name.clone(),
                        ChunkBinding::Function {
                            purity: Purity::Pure,
                        },
                    )
                })
                .collect(),
        };
        // tarjan_scc emits SCCs in reverse topological order: leaves
        // (sinks — functions that don't call any chunk-top
        // function) come first, callers come later.
        for scc in tarjan_scc(&call_graph) {
            graph.classify_scc(&scc, &functions, &callees_of, shadowed, declared_pure);
        }
        graph
    }

    /// Re-classify every function in `scc` until no purity changes.
    /// Worklist-driven: only re-process a function when one of its
    /// same-SCC callees has changed (cross-SCC callees are already
    /// finalized by bottom-up SCC ordering).
    fn classify_scc(
        &mut self,
        scc: &[usize],
        functions: &[ChunkFunction<'_>],
        callees_of: &[BTreeSet<usize>],
        shadowed: &BTreeSet<&'static str>,
        declared_pure: &BTreeSet<String>,
    ) {
        let scc_set: BTreeSet<usize> = scc.iter().copied().collect();
        // Reverse adjacency restricted to this SCC: callee → callers.
        let mut callers_in_scc: BTreeMap<usize, Vec<usize>> = BTreeMap::new();
        for &i in scc {
            for &callee in &callees_of[i] {
                if scc_set.contains(&callee) {
                    callers_in_scc.entry(callee).or_default().push(i);
                }
            }
        }
        let mut pending: BTreeSet<usize> = scc_set;
        while let Some(&i) = pending.iter().next() {
            pending.remove(&i);
            let new_purity = classify_function_body(&functions[i], shadowed, declared_pure, self);
            let name = &functions[i].name;
            let old = self.function_purity(name).expect("seeded by build");
            let combined = old.worst(new_purity);
            if combined != old {
                self.bindings
                    .insert(name.clone(), ChunkBinding::Function { purity: combined });
                if let Some(callers) = callers_in_scc.get(&i) {
                    pending.extend(callers.iter().copied());
                }
            }
        }
    }

    /// Purity of the chunk-local function bound to `name`, if any.
    /// Returns `None` for non-function bindings (imports, vars,
    /// classes) and for names not bound at chunk top.
    fn function_purity(&self, name: &str) -> Option<Purity> {
        match self.bindings.get(name)? {
            ChunkBinding::Function { purity } => Some(*purity),
        }
    }
}

/// Visitor that collects the indices of other chunk-top functions
/// called by a function body (Ident-callee form only). Skips
/// nested function/arrow/method bodies (those are separate lazy
/// scopes — their callees go to their own graph entries).
struct CallCollector<'a> {
    callees: BTreeSet<usize>,
    name_to_idx: &'a BTreeMap<&'a str, usize>,
}

impl Visit for CallCollector<'_> {
    fn visit_function(&mut self, _: &Function) {}
    fn visit_arrow_expr(&mut self, _: &ArrowExpr) {}
    fn visit_method_prop(&mut self, _: &MethodProp) {}
    fn visit_getter_prop(&mut self, _: &GetterProp) {}
    fn visit_setter_prop(&mut self, _: &SetterProp) {}

    fn visit_call_expr(&mut self, call: &CallExpr) {
        if let Callee::Expr(callee) = &call.callee
            && let Expr::Ident(id) = callee.as_ref()
            && let Some(&idx) = self.name_to_idx.get(id.sym.as_ref())
        {
            self.callees.insert(idx);
        }
        // Recurse to find nested calls in args / receiver.
        call.visit_children_with(self);
    }
}

#[derive(Debug, Clone)]
struct ChunkFunction<'a> {
    name: String,
    /// Block-bodied function/arrow.
    block_body: Option<&'a BlockStmt>,
    /// Concise-arrow expression body (`(x) => expr`).
    expr_body: Option<&'a Expr>,
}

impl ChunkFunction<'_> {
    /// Drive a `Visit` visitor over this function's body. Block
    /// bodies recurse via `visit_with`; concise-arrow expression
    /// bodies fire `visit_expr` directly so the visitor's
    /// `visit_call_expr` / `visit_expr` overrides catch the body.
    fn visit_body_with<V: Visit + ?Sized>(&self, visitor: &mut V) {
        if let Some(block) = self.block_body {
            block.visit_with(visitor);
        }
        if let Some(expr) = self.expr_body {
            expr.visit_with(visitor);
        }
    }
}

fn collect_chunk_functions(body: &[ModuleItem]) -> Vec<ChunkFunction<'_>> {
    let mut out = Vec::new();
    for item in body {
        match item {
            ModuleItem::Stmt(Stmt::Decl(Decl::Fn(fn_decl))) => push_fn_decl(fn_decl, &mut out),
            ModuleItem::Stmt(Stmt::Decl(Decl::Var(var))) => push_var_functions(var, &mut out),
            ModuleItem::ModuleDecl(ModuleDecl::ExportDecl(export)) => match &export.decl {
                Decl::Fn(fn_decl) => push_fn_decl(fn_decl, &mut out),
                Decl::Var(var) => push_var_functions(var, &mut out),
                _ => {}
            },
            _ => {}
        }
    }
    out
}

fn push_fn_decl<'a>(fn_decl: &'a FnDecl, out: &mut Vec<ChunkFunction<'a>>) {
    out.push(ChunkFunction {
        name: fn_decl.ident.sym.to_string(),
        block_body: fn_decl.function.body.as_ref(),
        expr_body: None,
    });
}

fn push_var_functions<'a>(var: &'a VarDecl, out: &mut Vec<ChunkFunction<'a>>) {
    // `let` / `var` bindings are reassignable: caching their
    // body's purity and short-circuiting `f(...)` to that purity
    // is unsound if a later `f = …` reassigns them to something
    // impure. Only `const`-bound function/arrow initializers are
    // tracked; reassignment of a `const` is a syntax error.
    if var.kind != VarDeclKind::Const {
        return;
    }
    for decl in &var.decls {
        let Pat::Ident(binding) = &decl.name else {
            continue;
        };
        let Some(init) = decl.init.as_deref() else {
            continue;
        };
        let name = binding.id.sym.to_string();
        match init {
            Expr::Fn(fn_expr) => {
                out.push(ChunkFunction {
                    name,
                    block_body: fn_expr.function.body.as_ref(),
                    expr_body: None,
                });
            }
            Expr::Arrow(arrow) => match arrow.body.as_ref() {
                BlockStmtOrExpr::BlockStmt(block) => {
                    out.push(ChunkFunction {
                        name,
                        block_body: Some(block),
                        expr_body: None,
                    });
                }
                BlockStmtOrExpr::Expr(expr) => {
                    out.push(ChunkFunction {
                        name,
                        block_body: None,
                        expr_body: Some(expr.as_ref()),
                    });
                }
            },
            _ => {}
        }
    }
}

fn classify_function_body(
    function: &ChunkFunction<'_>,
    shadowed: &BTreeSet<&'static str>,
    declared_pure: &BTreeSet<String>,
    graph: &ChunkCodeGraph,
) -> Purity {
    let mut collector = BodyPurityCollector {
        purity: Purity::Pure,
        shadowed,
        declared_pure,
        graph,
    };
    function.visit_body_with(&mut collector);
    collector.purity
}

/// Visitor that walks a function body and accumulates the worst
/// purity of every top-level expression encountered. Skips nested
/// function/arrow/method/getter/setter bodies (those are separate
/// lazy scopes — their purity, if needed, comes from their own
/// graph entry or from the caller's `Unknown` fallback).
struct BodyPurityCollector<'a> {
    purity: Purity,
    shadowed: &'a BTreeSet<&'static str>,
    declared_pure: &'a BTreeSet<String>,
    graph: &'a ChunkCodeGraph,
}

impl Visit for BodyPurityCollector<'_> {
    fn visit_function(&mut self, _: &Function) {}
    fn visit_arrow_expr(&mut self, _: &ArrowExpr) {}
    fn visit_method_prop(&mut self, _: &MethodProp) {}
    fn visit_getter_prop(&mut self, _: &GetterProp) {}
    fn visit_setter_prop(&mut self, _: &SetterProp) {}

    fn visit_expr(&mut self, expr: &Expr) {
        // Classify the entire expression in one shot —
        // `classify_expr_purity` already recurses through
        // nested subexpressions and returns the worst.
        let p = classify_expr_purity(expr, self.shadowed, self.declared_pure, self.graph);
        self.purity = self.purity.worst(p);
    }

    // Statement-level effects that don't surface as an Impure /
    // Unknown sub-expression. `throw e` alters control flow
    // observably even when `e` is a Pure literal; `debugger`
    // pauses execution observably to a host attached to the
    // process. Both make the enclosing function not Pure.
    fn visit_throw_stmt(&mut self, node: &ThrowStmt) {
        self.purity = self.purity.worst(Purity::Impure);
        // Still recurse so the thrown expression contributes its
        // own purity (e.g. `throw io()` should also see the call).
        node.arg.visit_with(self);
    }

    fn visit_debugger_stmt(&mut self, _node: &DebuggerStmt) {
        self.purity = self.purity.worst(Purity::Impure);
    }
}

/// Replace every multi-declarator top-level `var/let/const`
/// (including the form nested in an `export` decl) with N
/// single-declarator statements preserving source order. Other
/// statement kinds pass through unchanged.
fn split_comma_list_var_decls(body: &[ModuleItem]) -> Vec<ModuleItem> {
    let mut out = Vec::with_capacity(body.len());
    for item in body {
        match item {
            ModuleItem::Stmt(Stmt::Decl(Decl::Var(var))) if var.decls.len() > 1 => {
                for decl in &var.decls {
                    let single = VarDecl {
                        span: var.span,
                        ctxt: var.ctxt,
                        kind: var.kind,
                        declare: var.declare,
                        decls: vec![decl.clone()],
                    };
                    out.push(ModuleItem::Stmt(Stmt::Decl(Decl::Var(Box::new(single)))));
                }
            }
            ModuleItem::ModuleDecl(ModuleDecl::ExportDecl(export_decl)) => {
                match &export_decl.decl {
                    Decl::Var(var) if var.decls.len() > 1 => {
                        for decl in &var.decls {
                            let single = VarDecl {
                                span: var.span,
                                ctxt: var.ctxt,
                                kind: var.kind,
                                declare: var.declare,
                                decls: vec![decl.clone()],
                            };
                            out.push(ModuleItem::ModuleDecl(ModuleDecl::ExportDecl(ExportDecl {
                                span: export_decl.span,
                                decl: Decl::Var(Box::new(single)),
                            })));
                        }
                    }
                    _ => out.push(item.clone()),
                }
            }
            _ => out.push(item.clone()),
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
fn compute_shadowed_globals(body: &[ModuleItem]) -> BTreeSet<&'static str> {
    let mut shadowed = BTreeSet::new();
    let try_shadow = |name: &str, into: &mut BTreeSet<&'static str>| {
        if let Some(global) = WHITELIST_RECEIVERS.iter().copied().find(|r| *r == name) {
            into.insert(global);
        }
    };
    for item in body {
        for name in collect_declared_names(item) {
            try_shadow(name.as_str(), &mut shadowed);
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
    declared_pure: &BTreeSet<String>,
    graph: &ChunkCodeGraph,
) -> StatementFacts {
    let kind = classify_item(item);
    let declared = collect_declared_names(item);
    let mut at_init = AtInitReadCollector::default();
    item.visit_with(&mut at_init);
    let mut lazy = LazyReadCollector::default();
    item.visit_with(&mut lazy);
    let has_side_effect = item_has_side_effect(item, kind, shadowed, declared_pure, graph);
    StatementFacts {
        ordinal,
        source_location: None,
        declared,
        reads_at_init: at_init.names,
        reads_lazy: lazy.names,
        has_side_effect,
        kind,
    }
}

/// Three-state expression-level purity (DESIGN.md "Module dep
/// graphs"). `Pure` is statically provably free of observable
/// side effects; `Impure` is provably side-effecting (assignment,
/// update, await, yield); `Unknown` covers the long tail (calls,
/// `new`, member access — could be a getter — etc.) and is
/// treated as `Impure` by `has_side_effect` for soundness.
#[derive(Debug, Clone, Copy, Eq, PartialEq)]
enum Purity {
    Pure,
    Impure,
    Unknown,
}

impl Purity {
    /// Combine two purity assessments — the worst (most
    /// side-effecting) wins. `Impure` dominates `Unknown`
    /// dominates `Pure`.
    fn worst(self, other: Self) -> Self {
        match (self, other) {
            (Purity::Impure, _) | (_, Purity::Impure) => Purity::Impure,
            (Purity::Unknown, _) | (_, Purity::Unknown) => Purity::Unknown,
            _ => Purity::Pure,
        }
    }
}

/// Static-property reads on these globals are Pure (no
/// observable side effect, no getter to fire). Indexed as
/// `(receiver_ident, property_name)`.
const PURE_STATIC_PROPS: &[(&str, &str)] = &[
    ("Math", "PI"),
    ("Math", "E"),
    ("Math", "LN2"),
    ("Math", "LN10"),
    ("Math", "LOG2E"),
    ("Math", "LOG10E"),
    ("Math", "SQRT2"),
    ("Math", "SQRT1_2"),
    ("Number", "EPSILON"),
    ("Number", "MAX_SAFE_INTEGER"),
    ("Number", "MIN_SAFE_INTEGER"),
    ("Number", "MAX_VALUE"),
    ("Number", "MIN_VALUE"),
    ("Number", "POSITIVE_INFINITY"),
    ("Number", "NEGATIVE_INFINITY"),
    ("Number", "NaN"),
    ("Symbol", "iterator"),
    ("Symbol", "asyncIterator"),
    ("Symbol", "toStringTag"),
    ("Symbol", "toPrimitive"),
    ("Symbol", "hasInstance"),
    ("Symbol", "species"),
    ("Symbol", "isConcatSpreadable"),
    ("Symbol", "match"),
    ("Symbol", "replace"),
    ("Symbol", "search"),
    ("Symbol", "split"),
];

/// Static methods that are Pure regardless of argument values.
/// Everything in this table must satisfy: per ECMA-262, the call
/// fires no user-defined code on any argument type — no `ToNumber`
/// / `ToString` / `ToPrimitive` / `ToPropertyKey` coercion, no
/// iterator protocol, no proxy trap, no own-property `[[Get]]`,
/// no mutation of any reachable object. See DESIGN.md A8 for the
/// admission contract; AGENTS.md "Pure-call whitelist soundness"
/// for the agent-facing rule. New entries land only with a spec
/// citation showing no user-callback path; "common in practice"
/// is not sufficient.
const PURE_STATIC_CALLS: &[(&str, &str)] = &[
    // Type predicate — checks the IsArray internal slot. Spec
    // explicitly says: "does not perform a call to ToObject on its
    // argument".
    ("Array", "isArray"),
    // Number predicates — `Type(arg) is not Number ⇒ false`,
    // otherwise inspect the value. No coercion path.
    ("Number", "isFinite"),
    ("Number", "isInteger"),
    ("Number", "isNaN"),
    ("Number", "isSafeInteger"),
];

/// Pure global callables (no receiver). Same admission contract as
/// `PURE_STATIC_CALLS`: the call must fire no user code on any
/// argument value.
const PURE_GLOBAL_CALLS: &[&str] = &[
    // ToBoolean is type-cased and fires no callbacks (objects are
    // unconditionally `true`; primitives are checked structurally).
    "Boolean",
];

/// Static-property READS on these globals are Pure: the property
/// is an own data property of the receiver per ECMA-262 (no getter
/// fires) and accessing it has no observable side effect.
///
/// **Function-valued.** The resolved value is a callable. CALLING
/// it is NOT pure unless the same `(receiver, name)` pair also
/// appears in `PURE_STATIC_CALLS`. Every entry here MUST have both
/// a positive `static_function_ref_*_alias_is_pure` test AND a
/// negative `static_function_ref_*_call_remains_unknown` test
/// pinning that distinction. See AGENTS.md "Pure-call whitelist
/// soundness".
const PURE_STATIC_FUNCTION_REFS: &[(&str, &str)] = &[
    // All entries below are own data properties of the `Object`
    // built-in per ECMA-262 §20.1.2 — reads fire no getter. The
    // CALL of each is unsafe in distinct ways and intentionally
    // NOT in `PURE_STATIC_CALLS`:
    //   - `Object.defineProperty(t, k, d)` mutates `t`.
    //   - `Object.freeze(o)` mutates `o`'s descriptor table.
    //   - `Object.values(o)` / `Object.keys(o)` invoke
    //     `[[OwnPropertyKeys]]` and (for values) `[[Get]]` per
    //     key — fires user getters and Proxy traps.
    // The bare alias form `const define = Object.defineProperty;`
    // appears in real specs as a renamed shortcut.
    ("Object", "defineProperty"),
    ("Object", "freeze"),
    ("Object", "values"),
    ("Object", "keys"),
];

/// Receiver / global-callable names whose whitelist firing depends
/// on the chunk not having shadowed them at top level.
/// `analyze_chunk_facts` populates the shadowed-globals set, and
/// the classifier suppresses whitelist hits for any name in it —
/// e.g. `const Math = …` makes `Math.PI` fall back to `Unknown`.
const WHITELIST_RECEIVERS: &[&str] = &["Math", "Array", "Symbol", "Number", "Boolean", "Object"];

// TODO: extend the call whitelist with operations that are *Pure
// when their arguments are statically known to be primitives*
// (Number / String / Boolean / null / undefined / BigInt
// literals, or fresh literals built from those). Examples that
// become admissible under that stronger argument analysis:
//
//   - `Math.{abs, floor, ceil, round, trunc, sign, sqrt, cbrt,
//     min, max, pow, exp, log, log2, log10, log1p, sin, cos, tan,
//     asin, acos, atan, atan2, sinh, cosh, tanh, hypot, fround,
//     clz32, imul}` — `ToNumber` on a literal Number does not
//     fire user code.
//   - `JSON.parse(str)` for a `StringLiteral` argument — `ToString`
//     on a string is identity.
//   - `JSON.stringify(prim)` for a primitive literal — no
//     `toJSON` / `Symbol.toPrimitive` / `valueOf` path.
//   - `Number.parseInt(str[, radix])`, `Number.parseFloat(str)`
//     for a `StringLiteral` first arg and (optional) `Number`
//     second.
//   - `String.{fromCharCode, fromCodePoint}(...nums)` for all-
//     `NumberLiteral` args.
//   - `Array.of(...prims)` — `CreateDataPropertyOrThrow` on a
//     fresh array does not fire user code; the open question is
//     just "could a non-primitive arg do anything observable",
//     which a primitive-only gate avoids.
//   - `Object.{keys, values, entries, fromEntries, freeze,
//     getOwnPropertyNames, getOwnPropertyDescriptor, isFrozen,
//     hasOwn, assign}` — these *do* observe user callbacks
//     (getter on `[[Get]]`, ownKeys/getOwnPropertyDescriptor
//     traps on `Proxy`, mutation), so they remain UNSAFE for
//     general args. They become Pure only if the receiver is
//     itself a fresh ordinary-object literal with no accessors —
//     a separate, stricter analysis.
//
// Adding any of these requires (a) a Purity::Primitive variant
// (or a side analysis that classifies an Expr as
// "evaluates-to-primitive"), and (b) an updated admission rule
// here that gates the whitelist on that classification. Soundness
// rule: never relax in a way that admits a path firing user code
// on any argument shape (see AGENTS.md "Pure-call whitelist
// soundness").

fn classify_expr_purity(
    expr: &Expr,
    shadowed: &BTreeSet<&'static str>,
    declared_pure: &BTreeSet<String>,
    graph: &ChunkCodeGraph,
) -> Purity {
    match expr {
        Expr::Lit(_) => Purity::Pure,
        Expr::Ident(_) => Purity::Pure,
        Expr::This(_) | Expr::MetaProp(_) => Purity::Pure,
        Expr::Tpl(tpl) => tpl
            .exprs
            .iter()
            .map(|e| classify_expr_purity(e, shadowed, declared_pure, graph))
            .fold(Purity::Pure, Purity::worst),
        Expr::Fn(_) | Expr::Arrow(_) => Purity::Pure,
        Expr::Class(class_expr) => {
            if class_has_static_observable(&class_expr.class, shadowed, declared_pure, graph) {
                Purity::Impure
            } else {
                Purity::Pure
            }
        }
        Expr::Paren(p) => classify_expr_purity(&p.expr, shadowed, declared_pure, graph),
        Expr::Unary(u) => match u.op {
            UnaryOp::Delete => Purity::Impure,
            // typeof / void / +/-/!/~ on a pure operand are pure
            // (they may coerce, but coercion of an Ident or Lit
            // doesn't run user code).
            _ => classify_expr_purity(&u.arg, shadowed, declared_pure, graph),
        },
        Expr::Bin(b) => classify_expr_purity(&b.left, shadowed, declared_pure, graph).worst(
            classify_expr_purity(&b.right, shadowed, declared_pure, graph),
        ),
        Expr::Cond(c) => classify_expr_purity(&c.test, shadowed, declared_pure, graph)
            .worst(classify_expr_purity(
                &c.cons,
                shadowed,
                declared_pure,
                graph,
            ))
            .worst(classify_expr_purity(&c.alt, shadowed, declared_pure, graph)),
        Expr::Seq(s) => s
            .exprs
            .iter()
            .map(|e| classify_expr_purity(e, shadowed, declared_pure, graph))
            .fold(Purity::Pure, Purity::worst),
        Expr::Array(arr) => {
            let mut acc = Purity::Pure;
            for elem in arr.elems.iter().flatten() {
                if elem.spread.is_some() {
                    // Spread invokes the iterator protocol; could
                    // be impure even on a literal.
                    acc = acc.worst(Purity::Unknown);
                }
                acc = acc.worst(classify_expr_purity(
                    &elem.expr,
                    shadowed,
                    declared_pure,
                    graph,
                ));
            }
            acc
        }
        Expr::Object(obj) => {
            let mut acc = Purity::Pure;
            for prop in &obj.props {
                acc = acc.worst(classify_prop_purity(prop, shadowed, declared_pure, graph));
            }
            acc
        }
        Expr::Member(member) => {
            if let Some((recv, prop)) = static_member_pair(member)
                && !shadowed.contains(recv)
                && (PURE_STATIC_PROPS.contains(&(recv, prop))
                    || PURE_STATIC_FUNCTION_REFS.contains(&(recv, prop)))
            {
                return Purity::Pure;
            }
            // `obj.prop` on an arbitrary object can fire a getter;
            // we can't tell statically.
            Purity::Unknown
        }
        Expr::SuperProp(_) | Expr::OptChain(_) => Purity::Unknown,
        Expr::Call(call) => classify_call_purity(call, shadowed, declared_pure, graph),
        Expr::New(_) | Expr::TaggedTpl(_) => Purity::Unknown,
        Expr::Assign(_) | Expr::Update(_) => Purity::Impure,
        Expr::Await(_) | Expr::Yield(_) => Purity::Impure,
        // Anything we didn't enumerate falls into the Unknown
        // bucket — soundness-first.
        _ => Purity::Unknown,
    }
}

/// `(receiver_ident, prop_name)` for `Receiver.prop` where
/// `Receiver` is a plain `Ident` and `prop` is a static name.
/// Returns `None` for computed access (`obj[k]`), private fields,
/// or non-Ident receivers.
fn static_member_pair(member: &MemberExpr) -> Option<(&'static str, &'static str)> {
    let recv_sym = match member.obj.as_ref() {
        Expr::Ident(ident) => ident.sym.as_ref(),
        _ => return None,
    };
    let prop_sym = match &member.prop {
        MemberProp::Ident(ident) => ident.sym.as_ref(),
        _ => return None,
    };
    let recv = WHITELIST_RECEIVERS
        .iter()
        .copied()
        .find(|r| *r == recv_sym)?;
    // `prop_sym` may be borrowed from the AST; intern via the
    // whitelist tables so we return `&'static str` for downstream
    // `contains` checks.
    let prop = PURE_STATIC_PROPS
        .iter()
        .chain(PURE_STATIC_FUNCTION_REFS.iter())
        .chain(PURE_STATIC_CALLS.iter())
        .find_map(|(r, p)| (*r == recv && *p == prop_sym).then_some(*p))?;
    Some((recv, prop))
}

fn classify_call_purity(
    call: &CallExpr,
    shadowed: &BTreeSet<&'static str>,
    declared_pure: &BTreeSet<String>,
    graph: &ChunkCodeGraph,
) -> Purity {
    let Callee::Expr(callee_expr) = &call.callee else {
        return Purity::Unknown;
    };
    // Author-declared pure binding: a chunk-local function whose
    // spec member carries `purity: "pure"`. The annotation is an
    // explicit override and wins over both the whitelist and the
    // shadowing check (the spec author asserts that THIS bound
    // value is pure regardless of what its body does or whether
    // an import shadows the name). See AGENTS.md "Declared
    // purity".
    if let Expr::Ident(ident) = callee_expr.as_ref()
        && declared_pure.contains(ident.sym.as_ref())
    {
        return all_args_pure(&call.args, shadowed, declared_pure, graph);
    }
    // Chunk-local function declaration: consult the per-chunk
    // function-body purity cache. `Pure` callee + Pure args → Pure;
    // `Impure` callee → Impure (no matter the args); `Unknown`
    // callee inherits.
    if let Expr::Ident(ident) = callee_expr.as_ref()
        && let Some(callee_purity) = graph.function_purity(ident.sym.as_ref())
    {
        return callee_purity.worst(all_args_pure(&call.args, shadowed, declared_pure, graph));
    }
    // `Recv.method(args)` against PURE_STATIC_CALLS.
    if let Expr::Member(member) = callee_expr.as_ref()
        && let Some((recv, prop)) = static_member_pair(member)
        && !shadowed.contains(recv)
        && PURE_STATIC_CALLS.contains(&(recv, prop))
    {
        return all_args_pure(&call.args, shadowed, declared_pure, graph);
    }
    // `globalCallable(args)` against PURE_GLOBAL_CALLS.
    if let Expr::Ident(ident) = callee_expr.as_ref()
        && let Some(name) = PURE_GLOBAL_CALLS
            .iter()
            .copied()
            .find(|n| *n == ident.sym.as_ref())
        && !shadowed.contains(name)
    {
        return all_args_pure(&call.args, shadowed, declared_pure, graph);
    }
    Purity::Unknown
}

fn all_args_pure(
    args: &[ExprOrSpread],
    shadowed: &BTreeSet<&'static str>,
    declared_pure: &BTreeSet<String>,
    graph: &ChunkCodeGraph,
) -> Purity {
    let mut acc = Purity::Pure;
    for arg in args {
        if arg.spread.is_some() {
            // Spread arg's iterator could fire side effects.
            acc = acc.worst(Purity::Unknown);
        }
        acc = acc.worst(classify_expr_purity(
            &arg.expr,
            shadowed,
            declared_pure,
            graph,
        ));
    }
    acc
}

fn classify_prop_purity(
    prop: &PropOrSpread,
    shadowed: &BTreeSet<&'static str>,
    declared_pure: &BTreeSet<String>,
    graph: &ChunkCodeGraph,
) -> Purity {
    match prop {
        PropOrSpread::Spread(spread) => {
            // Spreading an arbitrary expression invokes its
            // iterator (array spread) or property iteration
            // (object spread). Either can fire a getter or a
            // user-defined `[Symbol.iterator]`.
            classify_expr_purity(&spread.expr, shadowed, declared_pure, graph)
                .worst(Purity::Unknown)
        }
        PropOrSpread::Prop(prop) => match prop.as_ref() {
            Prop::Shorthand(_) => Purity::Pure,
            Prop::KeyValue(kv) => {
                classify_propname_purity(&kv.key, shadowed, declared_pure, graph).worst(
                    classify_expr_purity(&kv.value, shadowed, declared_pure, graph),
                )
            }
            Prop::Assign(_) => Purity::Impure,
            // `{ get x() {}, set x(v) {}, m() {} }` — defining a
            // method or accessor is pure; invoking it is not, and
            // we don't invoke it during init.
            Prop::Getter(_) | Prop::Setter(_) | Prop::Method(_) => Purity::Pure,
        },
    }
}

fn classify_propname_purity(
    name: &PropName,
    shadowed: &BTreeSet<&'static str>,
    declared_pure: &BTreeSet<String>,
    graph: &ChunkCodeGraph,
) -> Purity {
    match name {
        PropName::Ident(_) | PropName::Str(_) | PropName::Num(_) | PropName::BigInt(_) => {
            Purity::Pure
        }
        PropName::Computed(c) => classify_expr_purity(&c.expr, shadowed, declared_pure, graph),
    }
}

/// Whether a class declaration runs observable code at class-decl
/// time. Static blocks always run; static fields run their
/// initializer. `extends <expr>` is at-init: the expression itself
/// runs, but `extends` references are tracked as `R`-edges
/// elsewhere — here we only report whether the class itself
/// _additionally_ has observable side-effecting init code.
fn class_has_static_observable(
    class: &Class,
    shadowed: &BTreeSet<&'static str>,
    declared_pure: &BTreeSet<String>,
    graph: &ChunkCodeGraph,
) -> bool {
    class.body.iter().any(|member| match member {
        ClassMember::StaticBlock(_) => true,
        ClassMember::ClassProp(prop) if prop.is_static => prop
            .value
            .as_deref()
            .map(|v| classify_expr_purity(v, shadowed, declared_pure, graph) != Purity::Pure)
            .unwrap_or(false),
        ClassMember::PrivateProp(prop) if prop.is_static => prop
            .value
            .as_deref()
            .map(|v| classify_expr_purity(v, shadowed, declared_pure, graph) != Purity::Pure)
            .unwrap_or(false),
        _ => false,
    })
}

fn item_has_side_effect(
    item: &ModuleItem,
    kind: StatementKind,
    shadowed: &BTreeSet<&'static str>,
    declared_pure: &BTreeSet<String>,
    graph: &ChunkCodeGraph,
) -> bool {
    match kind {
        StatementKind::Import | StatementKind::Export | StatementKind::FnDecl => false,
        StatementKind::VarDecl => var_decl_of_item(item)
            .iter()
            .flat_map(|var| var.decls.iter())
            .any(|d| match d.init.as_deref() {
                Some(init) => {
                    classify_expr_purity(init, shadowed, declared_pure, graph) != Purity::Pure
                }
                None => false,
            }),
        StatementKind::ClassDecl => class_of_item(item)
            .map(|c| class_has_static_observable(c, shadowed, declared_pure, graph))
            .unwrap_or(false),
        StatementKind::SideEffect => match item {
            ModuleItem::Stmt(Stmt::Expr(expr)) => {
                classify_expr_purity(&expr.expr, shadowed, declared_pure, graph) != Purity::Pure
            }
            // Bare blocks, control flow, loops, etc. — soundness-first.
            _ => true,
        },
    }
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

fn collect_declared_names(item: &ModuleItem) -> BTreeSet<String> {
    match item {
        ModuleItem::Stmt(Stmt::Decl(decl)) => declaration_names(decl),
        ModuleItem::ModuleDecl(ModuleDecl::ExportDecl(decl)) => declaration_names(&decl.decl),
        ModuleItem::ModuleDecl(ModuleDecl::ExportDefaultDecl(decl)) => match &decl.decl {
            DefaultDecl::Fn(fn_expr) => fn_expr
                .ident
                .as_ref()
                .map(|id| std::iter::once(id.sym.to_string()).collect())
                .unwrap_or_default(),
            DefaultDecl::Class(class_expr) => class_expr
                .ident
                .as_ref()
                .map(|id| std::iter::once(id.sym.to_string()).collect())
                .unwrap_or_default(),
            _ => BTreeSet::new(),
        },
        _ => BTreeSet::new(),
    }
}

fn declaration_names(decl: &Decl) -> BTreeSet<String> {
    match decl {
        Decl::Var(var) => var
            .decls
            .iter()
            .flat_map(|declarator| binding_names(&declarator.name))
            .collect(),
        Decl::Fn(fn_decl) => std::iter::once(fn_decl.ident.sym.to_string()).collect(),
        Decl::Class(class_decl) => std::iter::once(class_decl.ident.sym.to_string()).collect(),
        _ => BTreeSet::new(),
    }
}

fn binding_names(pattern: &Pat) -> Vec<String> {
    let mut out = Vec::new();
    walk_pattern(pattern, &mut out);
    out
}

fn walk_pattern(pattern: &Pat, out: &mut Vec<String>) {
    match pattern {
        Pat::Ident(id) => out.push(id.id.sym.to_string()),
        Pat::Array(arr) => {
            for element in arr.elems.iter().flatten() {
                walk_pattern(element, out);
            }
        }
        Pat::Object(obj) => {
            for prop in &obj.props {
                match prop {
                    ObjectPatProp::KeyValue(kv) => walk_pattern(&kv.value, out),
                    ObjectPatProp::Assign(assign) => out.push(assign.key.id.sym.to_string()),
                    ObjectPatProp::Rest(rest) => walk_pattern(&rest.arg, out),
                }
            }
        }
        Pat::Rest(rest) => walk_pattern(&rest.arg, out),
        Pat::Assign(assign) => walk_pattern(&assign.left, out),
        _ => {}
    }
}

/// Visitor that collects ident reads happening at-init only. Stops
/// at function bodies, method bodies, instance class-field
/// initializers, getter/setter bodies, and other lazy positions.
#[derive(Default)]
struct AtInitReadCollector {
    names: BTreeSet<String>,
}

impl Visit for AtInitReadCollector {
    fn visit_ident(&mut self, node: &Ident) {
        self.names.insert(node.sym.to_string());
    }

    fn visit_binding_ident(&mut self, _node: &BindingIdent) {}

    fn visit_import_decl(&mut self, _node: &ImportDecl) {}

    // Export specifiers don't fire reads at module-init: ESM treats
    // them as a static export entry, linked lazily when consumers
    // import. Counting them as at-init reads adds spurious `R`
    // edges (and, post-Phase-5 where R ⊆ I, spurious `I` edges).
    // `export var X = ...` / `export class X {}` etc. are still
    // visited via `ExportDecl`; only the bare-specifier forms are
    // suppressed here.
    fn visit_named_export(&mut self, _node: &NamedExport) {}
    fn visit_export_all(&mut self, _node: &ExportAll) {}

    // Function bodies are lazy — references inside don't read at-init.
    fn visit_function(&mut self, _node: &Function) {}
    fn visit_fn_decl(&mut self, _node: &FnDecl) {}
    fn visit_fn_expr(&mut self, _node: &FnExpr) {}
    fn visit_arrow_expr(&mut self, _node: &ArrowExpr) {}
    fn visit_method_prop(&mut self, _node: &MethodProp) {}
    fn visit_getter_prop(&mut self, _node: &GetterProp) {}
    fn visit_setter_prop(&mut self, _node: &SetterProp) {}

    fn visit_class(&mut self, node: &Class) {
        // Decorators on the class are eager.
        for decorator in &node.decorators {
            decorator.visit_with(self);
        }
        // Extends-clause is eager.
        if let Some(super_class) = &node.super_class {
            super_class.visit_with(self);
        }
        for member in &node.body {
            self.visit_class_member(member);
        }
    }

    fn visit_class_member(&mut self, member: &ClassMember) {
        match member {
            ClassMember::Method(method) => {
                // Method's name (computed key) is eager; body is lazy.
                self.visit_prop_name(&method.key);
            }
            ClassMember::PrivateMethod(_) => {}
            ClassMember::Constructor(_) => {}
            ClassMember::ClassProp(prop) => {
                // Computed keys are eager regardless of static-ness.
                self.visit_prop_name(&prop.key);
                if prop.is_static {
                    if let Some(value) = &prop.value {
                        value.visit_with(self);
                    }
                }
                // Instance field initializers are evaluated per-
                // instance — lazy from the class-decl's POV.
            }
            ClassMember::PrivateProp(prop) => {
                if prop.is_static {
                    if let Some(value) = &prop.value {
                        value.visit_with(self);
                    }
                }
            }
            ClassMember::StaticBlock(block) => {
                // Static block runs at class-decl time.
                block.visit_with(self);
            }
            ClassMember::TsIndexSignature(_) | ClassMember::Empty(_) => {}
            ClassMember::AutoAccessor(accessor) => {
                // accessor.key is a `Key` enum (Public/Private); for
                // public computed keys descend into the expression.
                if let Key::Public(name) = &accessor.key {
                    self.visit_prop_name(name);
                }
                if accessor.is_static {
                    if let Some(value) = &accessor.value {
                        value.visit_with(self);
                    }
                }
            }
        }
    }

    fn visit_prop_name(&mut self, name: &PropName) {
        if let PropName::Computed(computed) = name {
            computed.expr.visit_with(self);
        }
    }
}

/// Visitor that collects ident reads happening inside lazy syntactic
/// positions only — function bodies, method bodies, constructor
/// bodies, instance class-field initializers, getter/setter bodies.
/// Inverse boundary semantics from `AtInitReadCollector`.
#[derive(Default)]
struct LazyReadCollector {
    names: BTreeSet<String>,
    in_lazy: bool,
}

impl LazyReadCollector {
    fn descend_lazy<F: FnOnce(&mut Self)>(&mut self, f: F) {
        let prev = std::mem::replace(&mut self.in_lazy, true);
        f(self);
        self.in_lazy = prev;
    }
}

impl Visit for LazyReadCollector {
    fn visit_ident(&mut self, node: &Ident) {
        if self.in_lazy {
            self.names.insert(node.sym.to_string());
        }
    }

    fn visit_binding_ident(&mut self, _node: &BindingIdent) {}

    fn visit_import_decl(&mut self, _node: &ImportDecl) {}

    fn visit_function(&mut self, node: &Function) {
        self.descend_lazy(|s| node.visit_children_with(s));
    }
    fn visit_arrow_expr(&mut self, node: &ArrowExpr) {
        self.descend_lazy(|s| node.visit_children_with(s));
    }
    fn visit_method_prop(&mut self, node: &MethodProp) {
        node.key.visit_with(self);
        self.descend_lazy(|s| node.function.visit_with(s));
    }
    fn visit_getter_prop(&mut self, node: &GetterProp) {
        node.key.visit_with(self);
        self.descend_lazy(|s| {
            if let Some(body) = &node.body {
                body.visit_with(s);
            }
        });
    }
    fn visit_setter_prop(&mut self, node: &SetterProp) {
        node.key.visit_with(self);
        node.param.visit_with(self);
        self.descend_lazy(|s| {
            if let Some(body) = &node.body {
                body.visit_with(s);
            }
        });
    }

    fn visit_class(&mut self, node: &Class) {
        for decorator in &node.decorators {
            decorator.visit_with(self);
        }
        if let Some(super_class) = &node.super_class {
            super_class.visit_with(self);
        }
        for member in &node.body {
            self.visit_class_member(member);
        }
    }

    fn visit_class_member(&mut self, member: &ClassMember) {
        match member {
            ClassMember::Method(method) => {
                self.visit_prop_name(&method.key);
                self.descend_lazy(|s| method.function.visit_with(s));
            }
            ClassMember::PrivateMethod(method) => {
                self.descend_lazy(|s| method.function.visit_with(s));
            }
            ClassMember::Constructor(ctor) => {
                self.descend_lazy(|s| ctor.visit_children_with(s));
            }
            ClassMember::ClassProp(prop) => {
                self.visit_prop_name(&prop.key);
                if prop.is_static {
                    if let Some(value) = &prop.value {
                        value.visit_with(self);
                    }
                } else if let Some(value) = &prop.value {
                    self.descend_lazy(|s| value.visit_with(s));
                }
            }
            ClassMember::PrivateProp(prop) => {
                if prop.is_static {
                    if let Some(value) = &prop.value {
                        value.visit_with(self);
                    }
                } else if let Some(value) = &prop.value {
                    self.descend_lazy(|s| value.visit_with(s));
                }
            }
            ClassMember::StaticBlock(block) => {
                block.visit_with(self);
            }
            ClassMember::TsIndexSignature(_) | ClassMember::Empty(_) => {}
            ClassMember::AutoAccessor(accessor) => {
                if let Key::Public(name) = &accessor.key {
                    self.visit_prop_name(name);
                }
                if accessor.is_static {
                    if let Some(value) = &accessor.value {
                        value.visit_with(self);
                    }
                } else if let Some(value) = &accessor.value {
                    self.descend_lazy(|s| value.visit_with(s));
                }
            }
        }
    }

    fn visit_prop_name(&mut self, name: &PropName) {
        if let PropName::Computed(computed) = name {
            computed.expr.visit_with(self);
        }
    }
}

/// One reason an edge `(from, to)` exists, with the source
/// statement ordinal that produced it. This is the single source of
/// truth for edge semantics:
///
/// - `AtInitRead` constrains ESM evaluation order under TDZ
///   semantics (`R ⊆ I`).
/// - `LazyRead` contributes to the imports graph `I`, but does not
///   constrain realizability inside an SCC because the read fires
///   after module evaluation.
/// - `SideEffectOrder` contributes to `S` and constrains
///   realizability because source-order side effects require a
///   topological order.
#[derive(Debug, Clone)]
pub enum EdgeReason {
    AtInitRead {
        statement_ordinal: StatementOrdinal,
        binding: BindingName,
    },
    LazyRead {
        statement_ordinal: StatementOrdinal,
        binding: BindingName,
    },
    SideEffectOrder {
        statement_ordinal: StatementOrdinal,
    },
}

impl EdgeReason {
    fn side_effect_order(statement_ordinal: StatementOrdinal) -> Self {
        Self::SideEffectOrder { statement_ordinal }
    }

    fn kind(&self) -> EdgeKind {
        match self {
            Self::AtInitRead { .. } => EdgeKind::AtInitRead,
            Self::LazyRead { .. } => EdgeKind::LazyRead,
            Self::SideEffectOrder { .. } => EdgeKind::SideEffectOrder,
        }
    }

    fn statement_ordinal(&self) -> StatementOrdinal {
        match self {
            Self::AtInitRead {
                statement_ordinal, ..
            }
            | Self::LazyRead {
                statement_ordinal, ..
            }
            | Self::SideEffectOrder { statement_ordinal } => *statement_ordinal,
        }
    }

    fn binding(&self) -> Option<&BindingName> {
        match self {
            Self::AtInitRead { binding, .. } | Self::LazyRead { binding, .. } => Some(binding),
            Self::SideEffectOrder { .. } => None,
        }
    }

    fn is_at_init_read(&self) -> bool {
        matches!(self, Self::AtInitRead { .. })
    }

    fn is_lazy_read(&self) -> bool {
        matches!(self, Self::LazyRead { .. })
    }

    fn is_side_effect_order(&self) -> bool {
        matches!(self, Self::SideEffectOrder { .. })
    }

    fn constrains_realizability(&self) -> bool {
        !self.is_lazy_read()
    }
}

#[derive(Debug, Clone, Copy, Eq, PartialEq, Ord, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum EdgeKind {
    AtInitRead,
    LazyRead,
    SideEffectOrder,
}

/// Stable-in-run identity of an owner graph vertex. V1 owner
/// vertices are post-comma-list `StatementFacts` rows, so the id
/// is the row's source-order ordinal.
#[derive(Debug, Clone, Copy, Eq, PartialEq, Ord, PartialOrd, Hash)]
pub struct OwnerId(pub usize);

/// Fine-grained graph before logical modules are formed. Nodes are
/// top-level owners/statements; edges are owner-level reads and
/// source-order side-effect constraints. The module dependency graph
/// is the quotient of this graph by `OwnerNode.destination`.
#[derive(Debug, Clone, Default)]
pub struct OwnerGraph {
    pub nodes: BTreeMap<OwnerId, OwnerNode>,
    pub graph: DiGraphMap<OwnerId, EdgeMetadata>,
}

#[derive(Debug, Clone)]
pub struct OwnerNode {
    pub id: OwnerId,
    pub statement_ordinal: StatementOrdinal,
    pub source_location: Option<SourceLocation>,
    pub declared: BTreeSet<BindingName>,
    pub kind: StatementKind,
    pub has_side_effect: bool,
    pub destination: ModuleId,
}

impl OwnerGraph {
    fn record_reason(&mut self, from: OwnerId, to: OwnerId, reason: EdgeReason) {
        if from == to {
            return;
        }
        if !self.graph.contains_edge(from, to) {
            self.graph.add_edge(from, to, EdgeMetadata::default());
        }
        let weight = self
            .graph
            .edge_weight_mut(from, to)
            .expect("owner edge was just added");
        weight.reasons.push(reason);
    }

    pub fn iter_edges(&self) -> impl Iterator<Item = (OwnerId, OwnerId, &EdgeMetadata)> + '_ {
        self.graph.all_edges()
    }

    pub fn node(&self, id: OwnerId) -> Option<&OwnerNode> {
        self.nodes.get(&id)
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
    pub fn has_at_init_read(&self) -> bool {
        self.reasons.iter().any(EdgeReason::is_at_init_read)
    }

    /// `true` if at least one reason is a side-effect ordering
    /// edge. `S` edges in an SCC make it unrealizable: the
    /// constraint is "predecessor must evaluate before
    /// successor", and a cycle has no topological emit order
    /// satisfying every such edge.
    pub fn has_side_effect_ordering(&self) -> bool {
        self.reasons.iter().any(EdgeReason::is_side_effect_order)
    }

    /// `true` if this edge constrains the realizable evaluation
    /// order — an at-init read (`R`) or a side-effect ordering
    /// (`S`) edge. Lazy-only edges don't, because the reads they
    /// represent fire after every module in the cycle has
    /// finished evaluating.
    pub fn constrains_realizability(&self) -> bool {
        self.has_at_init_read() || self.has_side_effect_ordering()
    }
}

/// Module dep graph built from per-statement facts and a binding →
/// module assignment.
///
/// Backed by `petgraph::DiGraphMap`: one edge per directed
/// `(from, to)` pair, weight = `EdgeMetadata`. Multiple reasons
/// for the same physical edge (e.g. several at-init reads of
/// bindings owned by the same target module) accumulate into the
/// edge's reason list. Cycle detection runs through petgraph's
/// `tarjan_scc`.
#[derive(Debug, Clone, Default)]
pub struct ModuleDepGraph {
    pub graph: DiGraphMap<ModuleId, EdgeMetadata>,
}

impl ModuleDepGraph {
    fn record_reason(&mut self, from: ModuleId, to: ModuleId, reason: EdgeReason) {
        if from == to {
            return;
        }
        if !self.graph.contains_edge(from, to) {
            self.graph.add_edge(from, to, EdgeMetadata::default());
        }
        // Safe: we just ensured the edge exists.
        let weight = self
            .graph
            .edge_weight_mut(from, to)
            .expect("edge was just added");
        weight.reasons.push(reason);
    }

    /// Iterate edges as `(from, to, &EdgeMetadata)`.
    pub fn iter_edges(&self) -> impl Iterator<Item = (ModuleId, ModuleId, &EdgeMetadata)> + '_ {
        self.graph.all_edges()
    }

    /// Edge metadata, if the edge exists.
    pub fn edge(&self, from: ModuleId, to: ModuleId) -> Option<&EdgeMetadata> {
        self.graph.edge_weight(from, to)
    }

    /// `true` if the directed edge `(from, to)` is present and at
    /// least one of its reasons is an at-init read.
    pub fn has_at_init_edge(&self, from: ModuleId, to: ModuleId) -> bool {
        self.graph
            .edge_weight(from, to)
            .is_some_and(EdgeMetadata::has_at_init_read)
    }

    /// `true` if the edge `(from, to)` exists and constrains
    /// realizable evaluation order (at-init read or side-effect
    /// ordering). Used by the realizability gate to decide
    /// whether an `I ∪ S` SCC is unrealizable.
    pub fn has_realizability_constraining_edge(&self, from: ModuleId, to: ModuleId) -> bool {
        self.graph
            .edge_weight(from, to)
            .is_some_and(EdgeMetadata::constrains_realizability)
    }
}

/// Build the fine owner graph. Module-level dependencies are not
/// created here; they are derived later by quotienting owners by
/// destination.
pub fn build_owner_graph(
    facts: &[StatementFacts],
    binding_assignment: &BTreeMap<BindingName, ModuleId>,
) -> OwnerGraph {
    let mut graph = OwnerGraph::default();
    let stmt_owner = |stmt: &StatementFacts| -> ModuleId {
        stmt.declared
            .iter()
            .filter_map(|name| binding_assignment.get(name).copied())
            .next()
            .unwrap_or(ModuleId::ResidualEntry)
    };

    for stmt in facts {
        let id = OwnerId(stmt.ordinal.0);
        graph.nodes.insert(
            id,
            OwnerNode {
                id,
                statement_ordinal: stmt.ordinal,
                source_location: stmt.source_location.clone(),
                declared: stmt.declared.clone(),
                kind: stmt.kind,
                has_side_effect: stmt.has_side_effect,
                destination: stmt_owner(stmt),
            },
        );
        graph.graph.add_node(id);
    }

    let mut binding_owner = BTreeMap::<BindingName, OwnerId>::new();
    for stmt in facts {
        for binding in &stmt.declared {
            binding_owner.insert(binding.clone(), OwnerId(stmt.ordinal.0));
        }
    }

    let record_read = |graph: &mut OwnerGraph, from: OwnerId, reason: EdgeReason| {
        let Some(binding) = reason.binding() else {
            return;
        };
        let Some(&to) = binding_owner.get(binding) else {
            return; // not declared in this chunk (global, ImportSpecifier, never-declared)
        };
        graph.record_reason(from, to, reason);
    };
    for stmt in facts {
        let from = OwnerId(stmt.ordinal.0);
        for binding in &stmt.reads_at_init {
            record_read(
                &mut graph,
                from,
                EdgeReason::AtInitRead {
                    statement_ordinal: stmt.ordinal,
                    binding: binding.clone(),
                },
            );
        }
        for binding in &stmt.reads_lazy {
            record_read(
                &mut graph,
                from,
                EdgeReason::LazyRead {
                    statement_ordinal: stmt.ordinal,
                    binding: binding.clone(),
                },
            );
        }
    }

    // Side-effect ordering edges (`S` per DESIGN.md "Module dep
    // graphs"). At owner level, record the source-order chain over
    // side-effecting owners: every later side-effecting owner
    // depends on the immediately previous side-effecting owner.
    // This is the transitive reduction of the total order. It
    // preserves reachability and SCCs while avoiding an O(n^2)
    // owner-edge explosion in Tana-scale chunks.
    //
    // `has_side_effect` is computed by `classify_expr_purity` so
    // pure literal initializers (`const X = 42`,
    // `const X = { a: 1 }`, function/class declarations without
    // observable static init) don't contribute to S. Without
    // that precision the cross-module S graph would be dense
    // enough to reject realistic specs for trivially pure const
    // sequences.
    //
    let mut previous_side_effect_owner: Option<OwnerId> = None;
    for stmt in facts.iter().filter(|s| s.has_side_effect) {
        let from = OwnerId(stmt.ordinal.0);
        if let Some(to) = previous_side_effect_owner {
            graph.record_reason(from, to, EdgeReason::side_effect_order(stmt.ordinal));
        }
        previous_side_effect_owner = Some(from);
    }

    graph
}

/// Quotient the owner graph by each owner node's destination module.
/// This is the only path that constructs the module dependency graph
/// used by validation and emit.
pub fn quotient_owner_graph(owner_graph: &OwnerGraph) -> ModuleDepGraph {
    let owner_edges = collect_owner_edge_entries(owner_graph);
    quotient_owner_graph_with_destinations(owner_graph, &owner_edges, |_, node| node.destination)
}

fn quotient_owner_graph_with_destinations<F>(
    owner_graph: &OwnerGraph,
    owner_edges: &[OwnerEdgeEntry],
    mut destination_for: F,
) -> ModuleDepGraph
where
    F: FnMut(OwnerId, &OwnerNode) -> ModuleId,
{
    let mut graph = ModuleDepGraph::default();
    let mut seen_side_effect_module_pairs = BTreeSet::<(ModuleId, ModuleId)>::new();
    for edge in owner_edges {
        let Some(from_node) = owner_graph.node(edge.from) else {
            continue;
        };
        let Some(to_node) = owner_graph.node(edge.to) else {
            continue;
        };
        let from = destination_for(edge.from, from_node);
        let to = destination_for(edge.to, to_node);
        if from == to {
            continue;
        }
        if edge.reason.is_side_effect_order() && !seen_side_effect_module_pairs.insert((from, to)) {
            continue;
        }
        graph.record_reason(from, to, edge.reason.clone());
    }
    graph
}

/// Result of validating a module dep graph.
#[derive(Debug, Clone, Serialize)]
pub struct ScheduleReport {
    pub cycles: Vec<CycleReport>,
    /// Topological linearization of `I ∪ S` rooted at the entry,
    /// dependency-first. Empty when the dep graph has cycles
    /// (validation rejects). Captured here so debug tooling can
    /// see the linker's evaluation order without re-running
    /// materialization. See DESIGN.md "Lemma 2".
    pub linker_order: Vec<String>,
}

#[derive(Debug, Clone, Serialize)]
pub struct CycleReport {
    pub modules: Vec<String>,
    pub evidence: Vec<CycleEdge>,
    /// Spec-author-actionable cut: a near-minimum set of
    /// realizability-constraining (`at-init` or `side-effect`)
    /// reasons whose removal would lift the cycle's realizability
    /// violation. Computed by [`compute_realizability_cut`].
    ///
    /// The cut never includes `lazy` reasons — lazy edges don't
    /// constrain ESM evaluation order, so removing one cannot help
    /// fix a cycle. Each entry corresponds to (and shares its
    /// shape with) a row in `evidence`.
    ///
    /// The algorithm is iterative: while the working subgraph
    /// still has an SCC carrying a cross-module
    /// realizability-constraining edge, run petgraph's
    /// `greedy_feedback_arc_set` (Eades-Lin-Smyth, 1993,
    /// `O(V + E)`) on the offending sub-SCC, pick the first FAS
    /// edge with an `R` or `S` reason, append its constraining
    /// reasons to the cut, remove it from the working graph, and
    /// repeat. Sound (every iteration removes one constraining
    /// edge from a problematic SCC) and heuristic-minimum
    /// (petgraph's FAS approximates within a constant factor on
    /// dense instances).
    pub cut: Vec<CycleEdge>,
}

#[derive(Debug, Clone, Serialize)]
pub struct CycleEdge {
    pub from: String,
    pub to: String,
    pub statement_ordinal: StatementOrdinal,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub binding: Option<BindingName>,
    /// Edge kind. Lets
    /// downstream consumers (cycle-evidence visualizers, spec
    /// authors triaging which edges to break) tell at a glance
    /// which reasons are actually realizability-constraining
    /// (`at_init_read` and `side_effect_order`) vs.
    /// inert-but-graph-present (`lazy_read`).
    pub kind: EdgeKind,
}

#[derive(Debug, Clone)]
struct OwnerEdgeEntry {
    id: String,
    from: OwnerId,
    to: OwnerId,
    reason: EdgeReason,
}

#[derive(Debug, Clone, Default)]
struct QuotientEdgeAccumulator {
    kinds: BTreeSet<EdgeKind>,
    owner_edge_ids: Vec<String>,
    constraining_owner_edge_ids: Vec<String>,
    reason_count: usize,
    constrains_realizability: bool,
}

#[derive(Debug, Clone, Copy, Eq, PartialEq, Ord, PartialOrd)]
enum CandidateEdgeDirection {
    FromCandidate,
    ToCandidate,
}

#[derive(Debug, Clone)]
struct CandidateIncidentEdge {
    id: String,
    direction: CandidateEdgeDirection,
    module_idx: usize,
    constraining_owner_edge_ids: Vec<String>,
    constrains_realizability: bool,
}

#[derive(Debug, Clone, Default)]
struct ModulePairTotals {
    reason_count: usize,
    constraining_reason_count: usize,
    module_edge_id: Option<String>,
    constraining_owner_edge_indices: Vec<usize>,
}

#[derive(Debug, Clone)]
struct ModuleAdjEdge {
    pair: (ModuleId, ModuleId),
    target_idx: usize,
}

#[derive(Debug, Clone)]
struct ReverseModuleAdjEdge {
    pair: (ModuleId, ModuleId),
    source_idx: usize,
}

struct PeelabilityContext<'a> {
    owner_edges: &'a [OwnerEdgeEntry],
    owner_edge_by_id: BTreeMap<String, usize>,
    owner_out_edges: BTreeMap<OwnerId, Vec<usize>>,
    owner_in_edges: BTreeMap<OwnerId, Vec<usize>>,
    module_index: BTreeMap<ModuleId, usize>,
    modules: Vec<ModuleId>,
    forward_edges: Vec<Vec<ModuleAdjEdge>>,
    reverse_edges: Vec<Vec<ReverseModuleAdjEdge>>,
    module_pair_totals: BTreeMap<(ModuleId, ModuleId), ModulePairTotals>,
}

#[derive(Debug, Clone, Default)]
struct CandidateGraphAdjustment {
    removed_reason_count: BTreeMap<(ModuleId, ModuleId), usize>,
    removed_constraining_reason_count: BTreeMap<(ModuleId, ModuleId), usize>,
    removed_owner_edge_indices: BTreeSet<usize>,
}

fn build_owner_graph_report(schedule: &Schedule) -> OwnerGraphReport {
    let owner_edges = collect_owner_edge_entries(&schedule.owner_graph);
    let quotient_edges = build_quotient_edge_reports(schedule, &owner_edges);
    let quotient_nodes = build_quotient_node_reports(schedule);
    let quotient_sccs = build_quotient_scc_reports(schedule, &quotient_edges);
    let peelability = build_peelability_report(schedule, &owner_edges, &quotient_edges);
    OwnerGraphReport {
        chunk_id: schedule.chunk_id.clone(),
        nodes: schedule
            .owner_graph
            .nodes
            .values()
            .map(|node| OwnerGraphNodeReport {
                id: owner_key(node.id),
                statement_ordinal: node.statement_ordinal,
                source_location: node.source_location.clone(),
                declared_bindings: binding_reports(schedule, node.declared.iter()),
                statement_kind: node.kind,
                has_side_effect: node.has_side_effect,
                destination: module_report_ref(schedule, node.destination),
            })
            .collect(),
        edges: owner_edges
            .iter()
            .map(|edge| OwnerGraphEdgeReport {
                id: edge.id.clone(),
                source: owner_key(edge.from),
                target: owner_key(edge.to),
                edge_kind: edge.reason.kind(),
                binding: edge.reason.binding().cloned(),
                statement_ordinal: edge.reason.statement_ordinal(),
                source_location: source_location(schedule, edge.reason.statement_ordinal()),
                constrains_realizability: edge.reason.constrains_realizability(),
            })
            .collect(),
        quotient: OwnerGraphQuotientReport {
            nodes: quotient_nodes,
            edges: quotient_edges,
            sccs: quotient_sccs,
        },
        peelability,
    }
}

fn binding_reports<'a, I>(schedule: &Schedule, bindings: I) -> Vec<BindingReport>
where
    I: IntoIterator<Item = &'a BindingName>,
{
    bindings
        .into_iter()
        .map(|binding| BindingReport {
            binding: binding.clone(),
            export_name: export_name_for_binding(schedule, binding),
        })
        .collect()
}

fn export_name_for_binding(schedule: &Schedule, binding: &BindingName) -> BindingName {
    let Some(BindingKind::Owned { owner }) = schedule.bindings.get(binding) else {
        return schedule
            .chunk_renames
            .get(binding)
            .cloned()
            .unwrap_or_else(|| binding.clone());
    };
    match owner {
        ModuleId::Logical(LogicalModuleIndex(idx)) => schedule
            .logical_modules
            .get(*idx)
            .and_then(|module| module.rename_map.get(binding))
            .cloned()
            .unwrap_or_else(|| binding.clone()),
        ModuleId::ResidualEntry => schedule
            .chunk_renames
            .get(binding)
            .cloned()
            .unwrap_or_else(|| binding.clone()),
    }
}

fn collect_owner_edge_entries(owner_graph: &OwnerGraph) -> Vec<OwnerEdgeEntry> {
    let mut entries = Vec::new();
    for (from, to, weight) in owner_graph.iter_edges() {
        for reason in &weight.reasons {
            entries.push((from, to, reason.clone()));
        }
    }
    entries.sort_by(|a, b| {
        (
            a.0.0,
            a.1.0,
            a.2.kind(),
            a.2.statement_ordinal(),
            a.2.binding().map(String::as_str),
        )
            .cmp(&(
                b.0.0,
                b.1.0,
                b.2.kind(),
                b.2.statement_ordinal(),
                b.2.binding().map(String::as_str),
            ))
    });
    entries
        .into_iter()
        .enumerate()
        .map(|(idx, (from, to, reason))| OwnerEdgeEntry {
            id: format!("owner_edge:{idx}"),
            from,
            to,
            reason,
        })
        .collect()
}

fn source_location(
    schedule: &Schedule,
    statement_ordinal: StatementOrdinal,
) -> Option<SourceLocation> {
    schedule
        .facts
        .get(statement_ordinal.0)
        .and_then(|fact| fact.source_location.clone())
}

fn build_quotient_node_reports(schedule: &Schedule) -> Vec<ModuleReportRef> {
    let mut modules = BTreeSet::<ModuleId>::new();
    modules.insert(ModuleId::ResidualEntry);
    for idx in 0..schedule.logical_modules.len() {
        modules.insert(ModuleId::Logical(LogicalModuleIndex(idx)));
    }
    for node in schedule.owner_graph.nodes.values() {
        modules.insert(node.destination);
    }
    for (from, to, _) in schedule.dep_graph.iter_edges() {
        modules.insert(from);
        modules.insert(to);
    }
    modules
        .into_iter()
        .map(|id| module_report_ref(schedule, id))
        .collect()
}

fn build_quotient_edge_reports(
    schedule: &Schedule,
    owner_edges: &[OwnerEdgeEntry],
) -> Vec<QuotientEdgeReport> {
    build_quotient_edge_reports_with_destinations(&schedule.owner_graph, owner_edges, |_, node| {
        node.destination
    })
}

fn build_quotient_edge_reports_with_destinations<F>(
    owner_graph: &OwnerGraph,
    owner_edges: &[OwnerEdgeEntry],
    mut destination_for: F,
) -> Vec<QuotientEdgeReport>
where
    F: FnMut(OwnerId, &OwnerNode) -> ModuleId,
{
    let mut accum = BTreeMap::<(ModuleId, ModuleId), QuotientEdgeAccumulator>::new();
    let mut seen_side_effect_module_pairs = BTreeSet::<(ModuleId, ModuleId)>::new();
    for edge in owner_edges {
        let Some(from_node) = owner_graph.node(edge.from) else {
            continue;
        };
        let Some(to_node) = owner_graph.node(edge.to) else {
            continue;
        };
        let from = destination_for(edge.from, from_node);
        let to = destination_for(edge.to, to_node);
        if from == to {
            continue;
        }
        if edge.reason.is_side_effect_order() && !seen_side_effect_module_pairs.insert((from, to)) {
            continue;
        }
        let entry = accum.entry((from, to)).or_default();
        entry.kinds.insert(edge.reason.kind());
        entry.owner_edge_ids.push(edge.id.clone());
        if edge.reason.constrains_realizability() {
            entry.constraining_owner_edge_ids.push(edge.id.clone());
        }
        entry.reason_count += 1;
        entry.constrains_realizability |= edge.reason.constrains_realizability();
    }
    accum
        .into_iter()
        .enumerate()
        .map(|(idx, ((from, to), entry))| QuotientEdgeReport {
            id: format!("module_edge:{idx}"),
            source: module_key(from),
            target: module_key(to),
            edge_kinds: entry.kinds.into_iter().collect(),
            owner_edge_ids: entry.owner_edge_ids,
            constraining_owner_edge_ids: entry.constraining_owner_edge_ids,
            reason_count: entry.reason_count,
            constrains_realizability: entry.constrains_realizability,
        })
        .collect()
}

fn build_quotient_scc_reports(
    schedule: &Schedule,
    quotient_edges: &[QuotientEdgeReport],
) -> Vec<QuotientSccReport> {
    let mut sccs = Vec::new();
    for scc in tarjan_scc(&schedule.dep_graph.graph) {
        let is_cycle = scc.len() > 1
            || (scc.len() == 1 && schedule.dep_graph.graph.contains_edge(scc[0], scc[0]));
        if !is_cycle {
            continue;
        }
        let in_scc: BTreeSet<String> = scc.iter().copied().map(module_key).collect();
        let mut module_edge_ids = Vec::new();
        let mut constraining_module_edge_ids = Vec::new();
        for edge in quotient_edges {
            if in_scc.contains(&edge.source) && in_scc.contains(&edge.target) {
                module_edge_ids.push(edge.id.clone());
                if edge.constrains_realizability {
                    constraining_module_edge_ids.push(edge.id.clone());
                }
            }
        }
        let mut modules: Vec<String> = in_scc.into_iter().collect();
        modules.sort();
        let mut labels: Vec<String> = modules
            .iter()
            .map(|key| {
                module_id_from_key(key)
                    .map(|id| schedule.module_name(id))
                    .unwrap_or_else(|| key.clone())
            })
            .collect();
        labels.sort();
        module_edge_ids.sort();
        constraining_module_edge_ids.sort();
        sccs.push(QuotientSccReport {
            id: format!("scc:{}", sccs.len()),
            modules,
            labels,
            is_cycle,
            realizable: constraining_module_edge_ids.is_empty(),
            module_edge_ids,
            constraining_module_edge_ids,
        });
    }
    sccs
}

fn build_peelability_report(
    schedule: &Schedule,
    owner_edges: &[OwnerEdgeEntry],
    quotient_edges: &[QuotientEdgeReport],
) -> OwnerGraphPeelabilityReport {
    let residual_destinations: BTreeSet<ModuleId> = schedule
        .owner_graph
        .nodes
        .values()
        .filter_map(|node| {
            is_residual_destination(schedule, node.destination).then_some(node.destination)
        })
        .collect();

    let context = PeelabilityContext::new(schedule, owner_edges, quotient_edges);
    let mut declared_by_owner = BTreeMap::<OwnerId, Vec<BindingName>>::new();
    for node in schedule.owner_graph.nodes.values() {
        if !is_residual_destination(schedule, node.destination) {
            continue;
        }
        let declared = residual_declared_for_owner(schedule, node);
        if declared.is_empty() {
            continue;
        }
        declared_by_owner.insert(node.id, declared);
    }

    let mut singleton_candidates = Vec::<(OwnerId, OwnerGraphPeelCandidateReport)>::new();
    for (&owner_id, declared) in &declared_by_owner {
        singleton_candidates.push((
            owner_id,
            evaluate_residual_peel_candidate(
                schedule,
                &context,
                &[owner_id],
                declared.clone(),
                PeelCandidateKind::SingleOwner,
            ),
        ));
    }

    let pair_owner_sets = residual_pair_candidates_from_singleton_blockers(
        schedule,
        &singleton_candidates,
        &context.owner_edge_by_id,
        owner_edges,
        &declared_by_owner,
    );

    let mut pair_candidates = Vec::new();
    for (left, right) in pair_owner_sets {
        let mut declared = declared_by_owner.get(&left).cloned().unwrap_or_default();
        declared.extend(declared_by_owner.get(&right).into_iter().flatten().cloned());
        declared.sort();
        declared.dedup();

        let candidate = evaluate_residual_peel_candidate(
            schedule,
            &context,
            &[left, right],
            declared,
            PeelCandidateKind::OwnerPair,
        );
        if candidate.status == PeelCandidateStatus::PeelableNow {
            pair_candidates.push(candidate);
        }
    }

    let dependency_closure_candidates = residual_dependency_closure_candidates(
        schedule,
        &context,
        &singleton_candidates,
        &declared_by_owner,
    );

    let mut candidates: Vec<OwnerGraphPeelCandidateReport> = singleton_candidates
        .into_iter()
        .map(|(_, candidate)| candidate)
        .collect();
    candidates.extend(pair_candidates);
    candidates.extend(dependency_closure_candidates);

    let (residual_owner_horizon, minimal_peel_set_ids) =
        build_residual_owner_horizon(schedule, &declared_by_owner, &candidates);
    let minimal_peel_sets = candidates
        .iter()
        .filter(|candidate| minimal_peel_set_ids.contains(&candidate.id))
        .map(|candidate| OwnerGraphPeelSetReport {
            candidate_id: candidate.id.clone(),
            owner_set_kind: candidate.owner_set_kind,
            owner_ids: candidate.owner_ids.clone(),
            members: candidate.members.clone(),
        })
        .collect();

    OwnerGraphPeelabilityReport {
        residual_destinations: residual_destinations
            .into_iter()
            .map(|id| module_report_ref(schedule, id))
            .collect(),
        minimal_peel_sets,
        residual_owner_horizon,
        evaluated_owner_sets: candidates,
    }
}

fn build_residual_owner_horizon(
    schedule: &Schedule,
    declared_by_owner: &BTreeMap<OwnerId, Vec<BindingName>>,
    candidates: &[OwnerGraphPeelCandidateReport],
) -> (Vec<ResidualOwnerPeelHorizonReport>, BTreeSet<String>) {
    let candidate_owner_sets = build_candidate_owner_sets(candidates);
    let mut peelable_candidate_indices_by_owner = BTreeMap::<OwnerId, Vec<usize>>::new();
    let mut singleton_evaluation_by_owner = BTreeMap::<OwnerId, String>::new();
    for (idx, candidate) in candidates.iter().enumerate() {
        if candidate.owner_set_kind == PeelCandidateKind::SingleOwner
            && let Some(owner_id) = candidate_owner_sets[idx].iter().next()
        {
            singleton_evaluation_by_owner.insert(*owner_id, candidate.id.clone());
        }
        if candidate.status != PeelCandidateStatus::PeelableNow {
            continue;
        }
        for owner_id in &candidate_owner_sets[idx] {
            peelable_candidate_indices_by_owner
                .entry(*owner_id)
                .or_default()
                .push(idx);
        }
    }

    let mut rows = Vec::new();
    let mut minimal_peel_set_ids = BTreeSet::new();
    for (owner_id, bindings) in declared_by_owner {
        let owner_key = owner_key(*owner_id);
        let owner_bindings: BTreeSet<&str> = bindings.iter().map(String::as_str).collect();
        let mut containing_indices = peelable_candidate_indices_by_owner
            .get(owner_id)
            .cloned()
            .unwrap_or_default();
        containing_indices.sort_by(|a, b| {
            let a = &candidates[*a];
            let b = &candidates[*b];
            (
                a.owner_ids.len(),
                a.members.len(),
                a.members.as_slice(),
                a.id.as_str(),
            )
                .cmp(&(
                    b.owner_ids.len(),
                    b.members.len(),
                    b.members.as_slice(),
                    b.id.as_str(),
                ))
        });
        let mut minimal_options = Vec::<usize>::new();
        for candidate_idx in containing_indices {
            let candidate_owners = &candidate_owner_sets[candidate_idx];
            let has_smaller_containing_set = minimal_options.iter().any(|other_idx| {
                let other_owners = &candidate_owner_sets[*other_idx];
                other_owners.len() < candidate_owners.len()
                    && other_owners.is_subset(candidate_owners)
            });
            if !has_smaller_containing_set {
                minimal_options.push(candidate_idx);
            }
        }

        let status = if minimal_options
            .iter()
            .any(|candidate_idx| candidates[*candidate_idx].owner_ids.len() == 1)
        {
            ResidualOwnerPeelStatus::Direct
        } else if minimal_options.is_empty() {
            ResidualOwnerPeelStatus::Blocked
        } else {
            ResidualOwnerPeelStatus::WithCompanions
        };

        let mut peel_set_ids = Vec::new();
        let mut companion_options = Vec::new();
        for candidate_idx in minimal_options {
            let candidate = &candidates[candidate_idx];
            minimal_peel_set_ids.insert(candidate.id.clone());
            peel_set_ids.push(candidate.id.clone());
            if candidate.owner_ids.len() == 1 {
                continue;
            }
            companion_options.push(ResidualOwnerCompanionOptionReport {
                peel_set_id: candidate.id.clone(),
                companion_owner_ids: candidate
                    .owner_ids
                    .iter()
                    .filter(|id| *id != &owner_key)
                    .cloned()
                    .collect(),
                companion_members: candidate
                    .members
                    .iter()
                    .filter(|member| !owner_bindings.contains(member.binding.as_str()))
                    .cloned()
                    .collect(),
            });
        }

        let node = schedule
            .owner_graph
            .node(*owner_id)
            .expect("residual owner horizon should reference an existing owner");
        rows.push(ResidualOwnerPeelHorizonReport {
            owner_id: owner_key.clone(),
            statement_ordinal: node.statement_ordinal,
            source_location: node.source_location.clone(),
            statement_kind: node.kind,
            has_side_effect: node.has_side_effect,
            current_destination: module_report_ref(schedule, node.destination),
            members: binding_reports(schedule, bindings.iter()),
            status,
            peel_set_ids,
            companion_options,
            singleton_evaluation_id: singleton_evaluation_by_owner.get(owner_id).cloned(),
        });
    }
    (rows, minimal_peel_set_ids)
}

fn build_candidate_owner_sets(
    candidates: &[OwnerGraphPeelCandidateReport],
) -> Vec<BTreeSet<OwnerId>> {
    candidates
        .iter()
        .map(|candidate| {
            candidate
                .owner_ids
                .iter()
                .filter_map(|id| owner_id_from_key(id))
                .collect()
        })
        .collect()
}

fn residual_declared_for_owner(schedule: &Schedule, node: &OwnerNode) -> Vec<BindingName> {
    node.declared
        .iter()
        .filter(|name| {
            !matches!(
                schedule.bindings.get(*name),
                Some(BindingKind::Imported { .. })
            )
        })
        .cloned()
        .collect()
}

impl<'a> PeelabilityContext<'a> {
    fn new(
        schedule: &Schedule,
        owner_edges: &'a [OwnerEdgeEntry],
        quotient_edges: &[QuotientEdgeReport],
    ) -> Self {
        let mut modules = BTreeSet::<ModuleId>::new();
        modules.insert(ModuleId::ResidualEntry);
        for idx in 0..schedule.logical_modules.len() {
            modules.insert(ModuleId::Logical(LogicalModuleIndex(idx)));
        }
        for node in schedule.owner_graph.nodes.values() {
            modules.insert(node.destination);
        }
        for edge in quotient_edges {
            if let Some(source) = module_id_from_key(&edge.source) {
                modules.insert(source);
            }
            if let Some(target) = module_id_from_key(&edge.target) {
                modules.insert(target);
            }
        }
        let modules: Vec<ModuleId> = modules.into_iter().collect();
        let module_index: BTreeMap<ModuleId, usize> = modules
            .iter()
            .copied()
            .enumerate()
            .map(|(idx, id)| (id, idx))
            .collect();

        let mut owner_edge_by_id = BTreeMap::new();
        let mut owner_out_edges = BTreeMap::<OwnerId, Vec<usize>>::new();
        let mut owner_in_edges = BTreeMap::<OwnerId, Vec<usize>>::new();
        let mut module_pair_totals = BTreeMap::<(ModuleId, ModuleId), ModulePairTotals>::new();
        for (idx, edge) in owner_edges.iter().enumerate() {
            owner_edge_by_id.insert(edge.id.clone(), idx);
            owner_out_edges.entry(edge.from).or_default().push(idx);
            owner_in_edges.entry(edge.to).or_default().push(idx);

            let Some(from_node) = schedule.owner_graph.node(edge.from) else {
                continue;
            };
            let Some(to_node) = schedule.owner_graph.node(edge.to) else {
                continue;
            };
            let from = from_node.destination;
            let to = to_node.destination;
            if from == to {
                continue;
            }
            let totals = module_pair_totals.entry((from, to)).or_default();
            totals.reason_count += 1;
            if edge.reason.constrains_realizability() {
                totals.constraining_reason_count += 1;
                totals.constraining_owner_edge_indices.push(idx);
            }
        }

        for edge in quotient_edges {
            let Some(source) = module_id_from_key(&edge.source) else {
                continue;
            };
            let Some(target) = module_id_from_key(&edge.target) else {
                continue;
            };
            if let Some(totals) = module_pair_totals.get_mut(&(source, target)) {
                totals.module_edge_id = Some(edge.id.clone());
            }
        }

        let mut forward_edges = vec![Vec::new(); modules.len()];
        let mut reverse_edges = vec![Vec::new(); modules.len()];
        for &(source, target) in module_pair_totals.keys() {
            let Some(&source_idx) = module_index.get(&source) else {
                continue;
            };
            let Some(&target_idx) = module_index.get(&target) else {
                continue;
            };
            forward_edges[source_idx].push(ModuleAdjEdge {
                pair: (source, target),
                target_idx,
            });
            reverse_edges[target_idx].push(ReverseModuleAdjEdge {
                pair: (source, target),
                source_idx,
            });
        }

        Self {
            owner_edges,
            owner_edge_by_id,
            owner_out_edges,
            owner_in_edges,
            module_index,
            modules,
            forward_edges,
            reverse_edges,
            module_pair_totals,
        }
    }

    fn module_idx(&self, module: ModuleId) -> Option<usize> {
        self.module_index.get(&module).copied()
    }

    fn current_edge_remains(
        &self,
        pair: (ModuleId, ModuleId),
        adjustment: &CandidateGraphAdjustment,
    ) -> bool {
        let Some(totals) = self.module_pair_totals.get(&pair) else {
            return false;
        };
        let removed = adjustment
            .removed_reason_count
            .get(&pair)
            .copied()
            .unwrap_or(0);
        totals.reason_count > removed
    }

    fn current_edge_constrains(
        &self,
        pair: (ModuleId, ModuleId),
        adjustment: &CandidateGraphAdjustment,
    ) -> bool {
        let Some(totals) = self.module_pair_totals.get(&pair) else {
            return false;
        };
        let removed = adjustment
            .removed_constraining_reason_count
            .get(&pair)
            .copied()
            .unwrap_or(0);
        totals.constraining_reason_count > removed
    }
}

fn residual_pair_candidates_from_singleton_blockers(
    schedule: &Schedule,
    singleton_candidates: &[(OwnerId, OwnerGraphPeelCandidateReport)],
    owner_edge_by_id: &BTreeMap<String, usize>,
    owner_edges: &[OwnerEdgeEntry],
    declared_by_owner: &BTreeMap<OwnerId, Vec<BindingName>>,
) -> BTreeSet<(OwnerId, OwnerId)> {
    let mut pair_owner_sets = BTreeSet::new();
    for (owner_id, candidate) in singleton_candidates {
        if candidate.status != PeelCandidateStatus::BlockedCycle {
            continue;
        }
        for scc in &candidate.cycle_blockers {
            for edge_id in &scc.constraining_owner_edge_ids {
                let Some(edge_idx) = owner_edge_by_id.get(edge_id).copied() else {
                    continue;
                };
                let edge = &owner_edges[edge_idx];
                let other = if edge.from == *owner_id {
                    edge.to
                } else if edge.to == *owner_id {
                    edge.from
                } else {
                    continue;
                };
                if declared_by_owner.contains_key(&other)
                    && owners_share_residual_destination(schedule, *owner_id, other)
                {
                    pair_owner_sets.insert(sorted_owner_pair(*owner_id, other));
                }
            }
        }
    }
    pair_owner_sets
}

fn residual_dependency_closure_candidates(
    schedule: &Schedule,
    context: &PeelabilityContext<'_>,
    singleton_candidates: &[(OwnerId, OwnerGraphPeelCandidateReport)],
    declared_by_owner: &BTreeMap<OwnerId, Vec<BindingName>>,
) -> Vec<OwnerGraphPeelCandidateReport> {
    let mut seen_owner_sets = BTreeSet::<BTreeSet<OwnerId>>::new();
    let mut candidates = Vec::new();
    for (owner_id, candidate) in singleton_candidates {
        if candidate.status != PeelCandidateStatus::BlockedResidualDependency {
            continue;
        }
        let closure = residual_dependency_closure(schedule, context, &BTreeSet::from([*owner_id]));
        if closure.len() <= 1 || !seen_owner_sets.insert(closure.clone()) {
            continue;
        }

        let mut declared = Vec::new();
        let mut representable = true;
        for owner in &closure {
            let Some(owner_declared) = declared_by_owner.get(owner) else {
                representable = false;
                break;
            };
            if owner_declared.is_empty() {
                representable = false;
                break;
            }
            declared.extend(owner_declared.iter().cloned());
        }
        if !representable {
            continue;
        }
        declared.sort();
        declared.dedup();

        let owners: Vec<OwnerId> = closure.into_iter().collect();
        let candidate = evaluate_residual_peel_candidate(
            schedule,
            context,
            &owners,
            declared,
            if owners.len() == 2 {
                PeelCandidateKind::OwnerPair
            } else {
                PeelCandidateKind::OwnerClosure
            },
        );
        if candidate.status == PeelCandidateStatus::PeelableNow {
            candidates.push(candidate);
        }
    }
    candidates
}

fn residual_dependency_closure(
    schedule: &Schedule,
    context: &PeelabilityContext<'_>,
    seeds: &BTreeSet<OwnerId>,
) -> BTreeSet<OwnerId> {
    let mut closure = seeds.clone();
    let mut queue: VecDeque<OwnerId> = seeds.iter().copied().collect();
    while let Some(owner_id) = queue.pop_front() {
        let Some(edge_indices) = context.owner_out_edges.get(&owner_id) else {
            continue;
        };
        for &edge_idx in edge_indices {
            let edge = &context.owner_edges[edge_idx];
            let Some(to_node) = schedule.owner_graph.node(edge.to) else {
                continue;
            };
            if to_node.destination != ModuleId::ResidualEntry {
                continue;
            }
            if closure.insert(edge.to) {
                queue.push_back(edge.to);
            }
        }
    }
    closure
}

fn owners_share_residual_destination(schedule: &Schedule, left: OwnerId, right: OwnerId) -> bool {
    let Some(left_node) = schedule.owner_graph.node(left) else {
        return false;
    };
    let Some(right_node) = schedule.owner_graph.node(right) else {
        return false;
    };
    left_node.destination == right_node.destination
        && is_residual_destination(schedule, left_node.destination)
}

fn sorted_owner_pair(left: OwnerId, right: OwnerId) -> (OwnerId, OwnerId) {
    if left <= right {
        (left, right)
    } else {
        (right, left)
    }
}

fn evaluate_residual_peel_candidate(
    schedule: &Schedule,
    context: &PeelabilityContext<'_>,
    owner_ids: &[OwnerId],
    declared: Vec<BindingName>,
    kind: PeelCandidateKind,
) -> OwnerGraphPeelCandidateReport {
    let candidate_module = ModuleId::Logical(LogicalModuleIndex(schedule.logical_modules.len()));
    let moved_owners: BTreeSet<OwnerId> = owner_ids.iter().copied().collect();
    let owner_id_keys: Vec<String> = owner_ids.iter().copied().map(owner_key).collect();
    let first_owner = owner_ids
        .first()
        .and_then(|id| schedule.owner_graph.node(*id))
        .expect("peel candidate should reference existing owner");
    let candidate_id = format!("peel_candidate:{}", owner_id_keys.join("+"));
    let candidate_label = format!("peel {}", declared.join(", "));
    let (candidate_edges, adjustment) = candidate_incident_edges(schedule, context, &moved_owners);
    let residual_dependency_blockers =
        candidate_residual_dependencies(schedule, context, &moved_owners);
    let cycle_blockers = candidate_blocking_sccs_fast(
        schedule,
        context,
        &candidate_edges,
        &adjustment,
        candidate_module,
        &candidate_label,
    );
    let status = if !residual_dependency_blockers.is_empty() {
        PeelCandidateStatus::BlockedResidualDependency
    } else if !cycle_blockers.is_empty() {
        PeelCandidateStatus::BlockedCycle
    } else {
        PeelCandidateStatus::PeelableNow
    };

    OwnerGraphPeelCandidateReport {
        id: candidate_id.clone(),
        owner_set_kind: kind,
        status,
        owner_ids: owner_id_keys,
        members: binding_reports(schedule, declared.iter()),
        current_destination: module_report_ref(schedule, first_owner.destination),
        hypothetical_destination: HypotheticalPeelDestinationReport {
            id: candidate_id,
            label: candidate_label,
        },
        residual_dependency_blockers,
        cycle_blockers,
    }
}

#[derive(Debug, Clone, Default)]
struct ResidualDependencyAccumulator {
    owner_edge_ids: BTreeSet<String>,
    bindings: BTreeSet<BindingName>,
    kinds: BTreeSet<EdgeKind>,
}

fn candidate_residual_dependencies(
    schedule: &Schedule,
    context: &PeelabilityContext<'_>,
    moved_owners: &BTreeSet<OwnerId>,
) -> Vec<PeelBlockingResidualDependencyReport> {
    let mut accum = BTreeMap::<ModuleId, ResidualDependencyAccumulator>::new();
    for owner_id in moved_owners {
        let Some(edge_indices) = context.owner_out_edges.get(owner_id) else {
            continue;
        };
        for &edge_idx in edge_indices {
            let edge = &context.owner_edges[edge_idx];
            if moved_owners.contains(&edge.to) {
                continue;
            }
            let Some(to_node) = schedule.owner_graph.node(edge.to) else {
                continue;
            };
            if to_node.destination != ModuleId::ResidualEntry {
                continue;
            }
            let entry = accum.entry(to_node.destination).or_default();
            entry.owner_edge_ids.insert(edge.id.clone());
            if let Some(binding) = edge.reason.binding() {
                entry.bindings.insert(binding.clone());
            }
            entry.kinds.insert(edge.reason.kind());
        }
    }
    accum
        .into_iter()
        .map(|(destination, entry)| {
            let read_members = binding_reports(schedule, entry.bindings.iter());
            PeelBlockingResidualDependencyReport {
                destination: module_report_ref(schedule, destination),
                owner_edge_ids: entry.owner_edge_ids.into_iter().collect(),
                read_members,
                edge_kinds: entry.kinds.into_iter().collect(),
            }
        })
        .collect()
}

fn candidate_incident_edges(
    schedule: &Schedule,
    context: &PeelabilityContext<'_>,
    moved_owners: &BTreeSet<OwnerId>,
) -> (Vec<CandidateIncidentEdge>, CandidateGraphAdjustment) {
    let mut edge_indices = BTreeSet::new();
    for owner_id in moved_owners {
        if let Some(indices) = context.owner_out_edges.get(owner_id) {
            edge_indices.extend(indices.iter().copied());
        }
        if let Some(indices) = context.owner_in_edges.get(owner_id) {
            edge_indices.extend(indices.iter().copied());
        }
    }

    let mut adjustment = CandidateGraphAdjustment::default();
    let mut accum = BTreeMap::<(CandidateEdgeDirection, ModuleId), QuotientEdgeAccumulator>::new();
    let mut seen_side_effect_candidate_pairs =
        BTreeSet::<(CandidateEdgeDirection, ModuleId)>::new();

    for edge_idx in edge_indices {
        let edge = &context.owner_edges[edge_idx];
        adjustment.removed_owner_edge_indices.insert(edge_idx);

        let Some(from_node) = schedule.owner_graph.node(edge.from) else {
            continue;
        };
        let Some(to_node) = schedule.owner_graph.node(edge.to) else {
            continue;
        };
        let old_from = from_node.destination;
        let old_to = to_node.destination;
        if old_from != old_to {
            *adjustment
                .removed_reason_count
                .entry((old_from, old_to))
                .or_insert(0) += 1;
            if edge.reason.constrains_realizability() {
                *adjustment
                    .removed_constraining_reason_count
                    .entry((old_from, old_to))
                    .or_insert(0) += 1;
            }
        }

        let from_moved = moved_owners.contains(&edge.from);
        let to_moved = moved_owners.contains(&edge.to);
        if from_moved == to_moved {
            continue;
        }
        let (direction, module) = if from_moved {
            (CandidateEdgeDirection::FromCandidate, old_to)
        } else {
            (CandidateEdgeDirection::ToCandidate, old_from)
        };
        if edge.reason.is_side_effect_order()
            && !seen_side_effect_candidate_pairs.insert((direction, module))
        {
            continue;
        }
        let entry = accum.entry((direction, module)).or_default();
        entry.kinds.insert(edge.reason.kind());
        entry.owner_edge_ids.push(edge.id.clone());
        if edge.reason.constrains_realizability() {
            entry.constraining_owner_edge_ids.push(edge.id.clone());
        }
        entry.reason_count += 1;
        entry.constrains_realizability |= edge.reason.constrains_realizability();
    }

    let mut candidate_edges = Vec::new();
    for ((direction, module), entry) in accum {
        let Some(module_idx) = context.module_idx(module) else {
            continue;
        };
        candidate_edges.push(CandidateIncidentEdge {
            id: format!("candidate_edge:{}", candidate_edges.len()),
            direction,
            module_idx,
            constraining_owner_edge_ids: entry.constraining_owner_edge_ids,
            constrains_realizability: entry.constrains_realizability,
        });
    }

    (candidate_edges, adjustment)
}

fn candidate_blocking_sccs_fast(
    schedule: &Schedule,
    context: &PeelabilityContext<'_>,
    candidate_edges: &[CandidateIncidentEdge],
    adjustment: &CandidateGraphAdjustment,
    candidate_module: ModuleId,
    candidate_label: &str,
) -> Vec<PeelBlockingSccReport> {
    let mut forward = vec![false; context.modules.len()];
    let mut backward = vec![false; context.modules.len()];
    let mut queue = VecDeque::new();
    for edge in candidate_edges
        .iter()
        .filter(|edge| edge.direction == CandidateEdgeDirection::FromCandidate)
    {
        if !forward[edge.module_idx] {
            forward[edge.module_idx] = true;
            queue.push_back(edge.module_idx);
        }
    }
    while let Some(source_idx) = queue.pop_front() {
        for edge in &context.forward_edges[source_idx] {
            if !context.current_edge_remains(edge.pair, adjustment) {
                continue;
            }
            if !forward[edge.target_idx] {
                forward[edge.target_idx] = true;
                queue.push_back(edge.target_idx);
            }
        }
    }

    queue.clear();
    for edge in candidate_edges
        .iter()
        .filter(|edge| edge.direction == CandidateEdgeDirection::ToCandidate)
    {
        if !backward[edge.module_idx] {
            backward[edge.module_idx] = true;
            queue.push_back(edge.module_idx);
        }
    }
    while let Some(target_idx) = queue.pop_front() {
        for edge in &context.reverse_edges[target_idx] {
            if !context.current_edge_remains(edge.pair, adjustment) {
                continue;
            }
            if !backward[edge.source_idx] {
                backward[edge.source_idx] = true;
                queue.push_back(edge.source_idx);
            }
        }
    }

    let mut in_scc = vec![false; context.modules.len()];
    let mut has_cycle = false;
    for idx in 0..context.modules.len() {
        in_scc[idx] = forward[idx] && backward[idx];
        has_cycle |= in_scc[idx];
    }
    if !has_cycle {
        return Vec::new();
    }

    let mut module_edge_ids = BTreeSet::new();
    let mut constraining_module_edge_ids = BTreeSet::new();
    let mut constraining_owner_edge_ids = BTreeSet::new();

    for edge in candidate_edges {
        if !in_scc[edge.module_idx] {
            continue;
        }
        module_edge_ids.insert(edge.id.clone());
        if edge.constrains_realizability {
            constraining_module_edge_ids.insert(edge.id.clone());
            constraining_owner_edge_ids.extend(edge.constraining_owner_edge_ids.iter().cloned());
        }
    }

    for (source_idx, module_edges) in context.forward_edges.iter().enumerate() {
        if !in_scc[source_idx] {
            continue;
        }
        for edge in module_edges {
            if !in_scc[edge.target_idx] || !context.current_edge_remains(edge.pair, adjustment) {
                continue;
            }
            if let Some(totals) = context.module_pair_totals.get(&edge.pair) {
                if let Some(id) = &totals.module_edge_id {
                    module_edge_ids.insert(id.clone());
                    if context.current_edge_constrains(edge.pair, adjustment) {
                        constraining_module_edge_ids.insert(id.clone());
                    }
                }
                if context.current_edge_constrains(edge.pair, adjustment) {
                    for edge_idx in &totals.constraining_owner_edge_indices {
                        if adjustment.removed_owner_edge_indices.contains(edge_idx) {
                            continue;
                        }
                        constraining_owner_edge_ids
                            .insert(context.owner_edges[*edge_idx].id.clone());
                    }
                }
            }
        }
    }

    if constraining_module_edge_ids.is_empty() {
        return Vec::new();
    }

    let mut modules: Vec<String> = (0..context.modules.len())
        .filter(|idx| in_scc[*idx])
        .map(|idx| module_key(context.modules[idx]))
        .collect();
    modules.push(module_key(candidate_module));
    modules.sort();

    let mut labels: Vec<String> = (0..context.modules.len())
        .filter(|idx| in_scc[*idx])
        .map(|idx| schedule.module_name(context.modules[idx]))
        .collect();
    labels.push(candidate_label.to_string());
    labels.sort();

    vec![PeelBlockingSccReport {
        modules,
        labels,
        module_edge_ids: module_edge_ids.into_iter().collect(),
        constraining_module_edge_ids: constraining_module_edge_ids.into_iter().collect(),
        constraining_owner_edge_ids: constraining_owner_edge_ids.into_iter().collect(),
    }]
}

fn is_residual_destination(schedule: &Schedule, id: ModuleId) -> bool {
    match id {
        ModuleId::ResidualEntry => true,
        ModuleId::Logical(LogicalModuleIndex(idx)) => schedule
            .logical_modules
            .get(idx)
            .is_some_and(|module| module.residual),
    }
}

fn owner_key(id: OwnerId) -> String {
    format!("owner:{}", id.0)
}

fn owner_id_from_key(key: &str) -> Option<OwnerId> {
    key.strip_prefix("owner:")
        .and_then(|idx| idx.parse::<usize>().ok())
        .map(OwnerId)
}

fn module_key(id: ModuleId) -> String {
    match id {
        ModuleId::ResidualEntry => "residual".to_string(),
        ModuleId::Logical(LogicalModuleIndex(idx)) => format!("logical:{idx}"),
    }
}

fn module_id_from_key(key: &str) -> Option<ModuleId> {
    if key == "residual" {
        return Some(ModuleId::ResidualEntry);
    }
    key.strip_prefix("logical:")
        .and_then(|idx| idx.parse::<usize>().ok())
        .map(|idx| ModuleId::Logical(LogicalModuleIndex(idx)))
}

fn module_report_ref(schedule: &Schedule, id: ModuleId) -> ModuleReportRef {
    match id {
        ModuleId::ResidualEntry => ModuleReportRef {
            id: module_key(id),
            label: schedule.module_name(id),
            residual: true,
            index: None,
            target_file: None,
        },
        ModuleId::Logical(LogicalModuleIndex(idx)) => ModuleReportRef {
            id: module_key(id),
            label: schedule.module_name(id),
            residual: schedule
                .logical_modules
                .get(idx)
                .is_some_and(|module| module.residual),
            index: Some(idx),
            target_file: schedule
                .logical_modules
                .get(idx)
                .map(|module| module.target_file.clone()),
        },
    }
}

/// Render a compact human-readable summary of cycle reports for the
/// bail message. The full per-cycle evidence + cut goes to a side-
/// output file (`<chunk_id>/cycles.json`); the summary stays under
/// the typical CI log-tail threshold so the bail-message version
/// fits in stderr without truncation.
///
/// Per cycle, the summary lists:
/// - SCC size (modules) and total evidence-edge count.
/// - Top-5 modules by in-degree within the SCC — these are the
///   hubs whose incoming edges drive most of the cycle weight.
/// - Top-5 cut edges by reason count — the highest-leverage
///   `(from, to)` pairs to break.
/// - Cut total size (number of constraining reasons selected by
///   the FAS heuristic).
pub fn render_cycle_summary(cycles: &[CycleReport]) -> String {
    use std::collections::HashMap;
    let mut out = String::new();
    for (i, cycle) in cycles.iter().enumerate() {
        let mut in_degree: HashMap<&str, usize> = HashMap::new();
        for edge in &cycle.evidence {
            *in_degree.entry(edge.to.as_str()).or_insert(0) += 1;
        }
        let mut top_in: Vec<(&str, usize)> = in_degree.into_iter().collect();
        top_in.sort_by(|a, b| b.1.cmp(&a.1).then(a.0.cmp(b.0)));
        top_in.truncate(5);

        let mut cut_pairs: HashMap<(&str, &str), usize> = HashMap::new();
        for edge in &cycle.cut {
            *cut_pairs
                .entry((edge.from.as_str(), edge.to.as_str()))
                .or_insert(0) += 1;
        }
        let mut top_cut: Vec<((&str, &str), usize)> = cut_pairs.into_iter().collect();
        top_cut.sort_by(|a, b| b.1.cmp(&a.1).then(a.0.cmp(&b.0)));
        top_cut.truncate(5);

        out.push_str(&format!(
            "Cycle #{i}: {} modules, {} evidence edges, cut {} reasons across {} (from, to) pairs.\n",
            cycle.modules.len(),
            cycle.evidence.len(),
            cycle.cut.len(),
            cut_pairs_count(&cycle.cut),
        ));
        out.push_str("  Top in-degree hubs (incoming evidence edges):\n");
        for (m, n) in &top_in {
            out.push_str(&format!("    {n:>6}  {m}\n"));
        }
        out.push_str("  Top cut edges (R/S reasons to break):\n");
        for ((f, t), n) in &top_cut {
            out.push_str(&format!("    {n:>6}  {f}  ->  {t}\n"));
        }
    }
    out
}

fn cut_pairs_count(cut: &[CycleEdge]) -> usize {
    use std::collections::HashSet;
    let mut seen: HashSet<(&str, &str)> = HashSet::new();
    for edge in cut {
        seen.insert((edge.from.as_str(), edge.to.as_str()));
    }
    seen.len()
}

/// Find SCCs in the dep graph and produce a report listing every
/// non-trivial cycle (size > 1 OR a self-loop). Trivial single-node
/// non-self-loop SCCs are dropped.
pub fn validate_schedule(
    graph: &ModuleDepGraph,
    module_name: &dyn Fn(ModuleId) -> String,
) -> ScheduleReport {
    let sccs = tarjan_scc(&graph.graph);
    let mut cycles = Vec::new();
    for scc in sccs {
        let in_scc: HashSet<ModuleId> = scc.iter().copied().collect();
        let is_cycle =
            scc.len() > 1 || (scc.len() == 1 && graph.graph.contains_edge(scc[0], scc[0]));
        if !is_cycle {
            continue;
        }
        // Realizability filter (per DESIGN.md "The realizability
        // theorem"): an `I ∪ S` SCC is unrealizable iff at least
        // one cross-module edge between its members carries a
        // realizability-constraining reason — an at-init read
        // (`R`) or a side-effect ordering edge (`S`). Lazy reads
        // alone don't constrain it: the ESM linker evaluates the
        // SCC in *some* order, and the lazy reads only fire
        // afterwards (no TDZ, no missed side-effect ordering).
        let scc_constrains_evaluation_order = scc.iter().any(|&from| {
            scc.iter()
                .any(|&to| from != to && graph.has_realizability_constraining_edge(from, to))
        });
        if !scc_constrains_evaluation_order {
            continue;
        }
        let mut evidence = Vec::new();
        for (from, to, weight) in graph.iter_edges() {
            if !in_scc.contains(&from) || !in_scc.contains(&to) {
                continue;
            }
            for reason in &weight.reasons {
                evidence.push(CycleEdge {
                    from: module_name(from),
                    to: module_name(to),
                    statement_ordinal: reason.statement_ordinal(),
                    binding: reason.binding().cloned(),
                    kind: reason.kind(),
                });
            }
        }
        let cut = compute_realizability_cut(graph, &scc, module_name);
        cycles.push(CycleReport {
            modules: scc.iter().copied().map(module_name).collect(),
            evidence,
            cut,
        });
    }
    ScheduleReport {
        cycles,
        linker_order: Vec::new(),
    }
}

/// Compute a near-minimum cut of realizability-constraining edges
/// inside `scc` whose removal makes the SCC realizable.
///
/// Each iteration:
/// 1. Tarjan-SCC the working graph (initially the induced subgraph
///    on `scc` from `graph`).
/// 2. If no SCC of size ≥ 2 carries a cross-module
///    realizability-constraining edge, return the accumulated cut.
/// 3. Otherwise, pick the first such SCC, run
///    `petgraph::algo::greedy_feedback_arc_set` (Eades-Lin-Smyth)
///    on its induced subgraph, and pick the first FAS edge whose
///    metadata has an `AtInitRead` or `SideEffect` reason.
/// 4. Fall back to scanning the SCC's edges if the FAS only
///    yielded lazy edges (rare; happens when tie-breaking biases
///    the order toward picking lazy edges as back-edges).
/// 5. Append the picked edge's R/S reasons to the cut and remove
///    it from the working graph.
///
/// Termination: each iteration removes at least one R/S edge from
/// the working graph, and the count of R/S edges is finite.
/// Soundness: when the loop exits, every remaining SCC has only
/// lazy cross-module edges between members — realizable per the
/// DESIGN.md realizability theorem. Cuts are sorted
/// deterministically `(from, to, statement_ordinal, binding, kind)`
/// so test snapshots compare cleanly.
fn compute_realizability_cut(
    graph: &ModuleDepGraph,
    scc: &[ModuleId],
    module_name: &dyn Fn(ModuleId) -> String,
) -> Vec<CycleEdge> {
    if scc.len() < 2 {
        return Vec::new();
    }
    // Working copy: induced subgraph on `scc`. Edge weight is the
    // full `EdgeMetadata` so we can read reasons when adding to
    // the cut. Cloning is cheap — petgraph's `DiGraphMap` clone
    // is per-edge, and an SCC is at most a few thousand edges in
    // practice.
    let in_scc: HashSet<ModuleId> = scc.iter().copied().collect();
    let mut working = DiGraphMap::<ModuleId, EdgeMetadata>::new();
    for &m in scc {
        working.add_node(m);
    }
    for (from, to, weight) in graph.iter_edges() {
        if !in_scc.contains(&from) || !in_scc.contains(&to) || from == to {
            continue;
        }
        working.add_edge(from, to, weight.clone());
    }

    let mut cut: Vec<CycleEdge> = Vec::new();
    loop {
        let sub_sccs = tarjan_scc(&working);
        let problematic = sub_sccs.into_iter().find(|s| {
            if s.len() < 2 {
                return false;
            }
            let in_s: HashSet<ModuleId> = s.iter().copied().collect();
            s.iter().any(|&from| {
                working.edges(from).any(|(_, to, w)| {
                    from != to && in_s.contains(&to) && w.constrains_realizability()
                })
            })
        });
        let Some(s) = problematic else { break };
        let in_s: HashSet<ModuleId> = s.iter().copied().collect();

        // Induce a sub-SCC subgraph as an index-based `DiGraph`.
        // petgraph's `greedy_feedback_arc_set` requires
        // `NodeId: GraphIndex`, which `DiGraphMap`'s arbitrary key
        // type doesn't satisfy — `DiGraph` indexes nodes by
        // contiguous `NodeIndex`. Carry `ModuleId` as the node
        // weight so we can map FAS endpoints back.
        let mut induced: DiGraph<ModuleId, ()> = DiGraph::new();
        let mut idx_of: HashMap<ModuleId, _> = HashMap::new();
        for &m in &s {
            let ix = induced.add_node(m);
            idx_of.insert(m, ix);
        }
        for &from in &s {
            for (_, to, _) in working.edges(from) {
                if from != to && in_s.contains(&to) {
                    induced.add_edge(idx_of[&from], idx_of[&to], ());
                }
            }
        }
        let fas: Vec<(ModuleId, ModuleId)> = greedy_feedback_arc_set(&induced)
            .map(|e| (induced[e.source()], induced[e.target()]))
            .collect();

        // Prefer R/S FAS edges; fall back to scanning the sub-SCC
        // for any R/S edge if FAS only flagged lazy edges (rare).
        let pick_in_fas = fas.iter().copied().find(|&(u, v)| {
            working
                .edge_weight(u, v)
                .is_some_and(EdgeMetadata::constrains_realizability)
        });
        let pick = pick_in_fas.or_else(|| {
            for &from in &s {
                for (_, to, w) in working.edges(from) {
                    if from != to && in_s.contains(&to) && w.constrains_realizability() {
                        return Some((from, to));
                    }
                }
            }
            None
        });
        let Some((u, v)) = pick else {
            // Should be unreachable — `problematic` confirmed at
            // least one constraining cross-module edge in `s`.
            break;
        };

        let weight = working
            .remove_edge(u, v)
            .expect("edge picked from working graph just above");
        for reason in &weight.reasons {
            if reason.is_lazy_read() {
                continue;
            }
            cut.push(CycleEdge {
                from: module_name(u),
                to: module_name(v),
                statement_ordinal: reason.statement_ordinal(),
                binding: reason.binding().cloned(),
                kind: reason.kind(),
            });
        }
    }

    cut.sort_by(|a, b| {
        (
            a.from.as_str(),
            a.to.as_str(),
            a.statement_ordinal,
            &a.binding,
            a.kind,
        )
            .cmp(&(
                b.from.as_str(),
                b.to.as_str(),
                b.statement_ordinal,
                &b.binding,
                b.kind,
            ))
    });
    cut
}

fn owned_view(bindings: &BTreeMap<BindingName, BindingKind>) -> BTreeMap<BindingName, ModuleId> {
    bindings
        .iter()
        .filter_map(|(name, kind)| match kind {
            BindingKind::Owned { owner } => Some((name.clone(), *owner)),
            BindingKind::Imported { .. } => None,
        })
        .collect()
}

/// Topological linearization of the dep graph, dependency-first.
/// Empty if the graph has cycles (`tarjan_scc` plus the validator
/// gate handle that case).
///
/// The dep-graph edge convention is `(M, M')` meaning `M` depends
/// on `M'`. `petgraph::algo::toposort` returns `u`-before-`v` for
/// every edge `(u, v)`, which under our convention puts dependents
/// before dependencies. The returned order is reversed so the
/// dependency comes first — matching the order ECMA-262's link
/// traversal needs to evaluate (deepest leaf first).
fn compute_linker_order(
    dep_graph: &ModuleDepGraph,
    logical_modules: &[LogicalModule],
) -> Vec<ModuleId> {
    let mut graph = DiGraphMap::<ModuleId, ()>::new();
    // Add every module the schedule knows about so the order
    // covers them even if they have no dep-graph edges (singleton
    // leaves still need a deterministic position for emit ordering).
    graph.add_node(ModuleId::ResidualEntry);
    for idx in 0..logical_modules.len() {
        graph.add_node(ModuleId::Logical(LogicalModuleIndex(idx)));
    }
    for (from, to, _) in dep_graph.iter_edges() {
        graph.add_node(from);
        graph.add_node(to);
        graph.add_edge(from, to, ());
    }
    match toposort(&graph, None) {
        Ok(order) => order.into_iter().rev().collect(),
        Err(_) => Vec::new(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use swc_common::{FileName, sync::Lrc};
    use swc_ecma_parser::{Parser, StringInput, Syntax, lexer::Lexer};

    fn parse(source: &str) -> Module {
        let cm: Lrc<swc_common::SourceMap> = Default::default();
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
        Parser::new_from(lexer).parse_module().unwrap()
    }

    #[test]
    fn function_body_reads_are_lazy() {
        let module = parse("function f() { return X; } const Y = 1;");
        let facts = analyze_chunk_facts(&module, &BTreeSet::new());
        assert_eq!(facts.len(), 2);
        // f() declares "f"; its body reference to X is lazy.
        assert_eq!(
            facts[0].declared,
            ["f"].iter().map(|s| s.to_string()).collect()
        );
        assert!(!facts[0].reads_at_init.contains("X"));
        assert_eq!(facts[0].kind, StatementKind::FnDecl);
        // Y declares "Y"; init is `1` (no reads).
        assert_eq!(
            facts[1].declared,
            ["Y"].iter().map(|s| s.to_string()).collect()
        );
        assert!(facts[1].reads_at_init.is_empty());
    }

    #[test]
    fn class_extends_clause_reads_at_init() {
        let module = parse("class B extends A { run() { return X; } }");
        let facts = analyze_chunk_facts(&module, &BTreeSet::new());
        assert_eq!(facts.len(), 1);
        // extends A is eager; method body reference to X is lazy.
        assert!(facts[0].reads_at_init.contains("A"));
        assert!(!facts[0].reads_at_init.contains("X"));
    }

    #[test]
    fn computed_key_reads_at_init() {
        let module = parse("const M = { [k.foo]: 1 };");
        let facts = analyze_chunk_facts(&module, &BTreeSet::new());
        // The key expression `k.foo` reads `k` at-init.
        assert!(facts[0].reads_at_init.contains("k"));
    }

    #[test]
    fn class_static_init_reads_at_init() {
        let module = parse("class C { static x = Y; }");
        let facts = analyze_chunk_facts(&module, &BTreeSet::new());
        assert!(facts[0].reads_at_init.contains("Y"));
    }

    #[test]
    fn class_instance_init_is_lazy() {
        let module = parse("class C { x = Y; }");
        let facts = analyze_chunk_facts(&module, &BTreeSet::new());
        // Instance field initializer evaluates per-instance, not at
        // class-decl time.
        assert!(!facts[0].reads_at_init.contains("Y"));
    }

    fn logical(idx: usize) -> ModuleId {
        ModuleId::Logical(LogicalModuleIndex(idx))
    }

    fn render(id: ModuleId) -> String {
        match id {
            ModuleId::Logical(LogicalModuleIndex(idx)) => format!("mod_{idx}"),
            ModuleId::ResidualEntry => "<residual>".to_string(),
        }
    }

    fn member_bindings(members: &[BindingReport]) -> Vec<String> {
        members
            .iter()
            .map(|member| member.binding.clone())
            .collect()
    }

    #[test]
    fn cycle_detected_between_two_modules() {
        // mod_a owns A; A's init reads B (owned by mod_b).
        // mod_b owns B; B's init reads A (owned by mod_a).
        let module = parse("const A = B + 1; const B = A + 1;");
        let facts = analyze_chunk_facts(&module, &BTreeSet::new());
        let mut binding_assignment = BTreeMap::new();
        binding_assignment.insert("A".to_string(), logical(0));
        binding_assignment.insert("B".to_string(), logical(1));
        let owner_graph = build_owner_graph(&facts, &binding_assignment);
        let graph = quotient_owner_graph(&owner_graph);
        let report = validate_schedule(&graph, &render);
        assert_eq!(report.cycles.len(), 1);
        assert_eq!(report.cycles[0].modules.len(), 2);
    }

    #[test]
    fn dag_has_no_cycles() {
        let module = parse("const A = 1; const B = A + 1; const C = B + A;");
        let facts = analyze_chunk_facts(&module, &BTreeSet::new());
        let mut binding_assignment = BTreeMap::new();
        binding_assignment.insert("A".to_string(), logical(0));
        binding_assignment.insert("B".to_string(), logical(1));
        binding_assignment.insert("C".to_string(), logical(2));
        let owner_graph = build_owner_graph(&facts, &binding_assignment);
        let graph = quotient_owner_graph(&owner_graph);
        let report = validate_schedule(&graph, &render);
        assert!(
            report.cycles.is_empty(),
            "expected no cycles, got {:?}",
            report.cycles
        );
    }

    /// Pin the cut behavior for the canonical mixed cycle: 2-module
    /// SCC with one lazy forward-edge and one at-init back-edge.
    /// The cut should contain exactly the at-init back-edge — lazy
    /// edges aren't realizability-constraining and removing one
    /// can't fix the cycle.
    #[test]
    fn cut_excludes_lazy_edges_in_mixed_cycle() {
        // mod_0 owns A and readB; readB body returns B (lazy read).
        // mod_1 owns B; B = A + 1 (at-init read of A).
        // R-edge: mod_1 → mod_0 (kind = at-init, binding = A).
        // L-edge: mod_0 → mod_1 (kind = lazy, binding = B).
        let module = parse("const A = 1; function readB() { return B; } const B = A + 1;");
        let facts = analyze_chunk_facts(&module, &BTreeSet::new());
        let mut binding_assignment = BTreeMap::new();
        binding_assignment.insert("A".to_string(), logical(0));
        binding_assignment.insert("readB".to_string(), logical(0));
        binding_assignment.insert("B".to_string(), logical(1));
        let owner_graph = build_owner_graph(&facts, &binding_assignment);
        let graph = quotient_owner_graph(&owner_graph);
        let report = validate_schedule(&graph, &render);
        assert_eq!(
            report.cycles.len(),
            1,
            "expected one cycle, got {:?}",
            report.cycles,
        );
        let cycle = &report.cycles[0];
        assert!(
            cycle.evidence.iter().any(|e| e.kind == EdgeKind::LazyRead),
            "evidence should include the lazy edge, got {:?}",
            cycle.evidence,
        );
        assert!(
            !cycle.cut.iter().any(|e| e.kind == EdgeKind::LazyRead),
            "cut must not include lazy reasons, got {:?}",
            cycle.cut,
        );
        assert_eq!(
            cycle.cut.len(),
            1,
            "min cut for a single mixed cycle is one edge, got {:?}",
            cycle.cut,
        );
        let entry = &cycle.cut[0];
        assert_eq!(entry.from, "mod_1");
        assert_eq!(entry.to, "mod_0");
        assert_eq!(entry.binding.as_deref(), Some("A"));
        assert_eq!(entry.kind, EdgeKind::AtInitRead);
    }

    /// Pure-S cycle: cut consists of side-effect reasons; no
    /// lazy or at-init reasons should appear.
    #[test]
    fn cut_emits_side_effect_edges_for_s_only_cycle() {
        // Three side-effecting `globalThis.tag = ...` writes
        // interleaved across mod_0 (ord 0, 2) and mod_1 (ord 1).
        // S-edges: mod_0 → mod_1 (ord 0 < ord 1) and
        // mod_1 → mod_0 (ord 1 < ord 2). Cycle.
        let module = parse(
            r#"const a1 = (globalThis.tag = "a1", 1); const b1 = (globalThis.tag = "b1", 2); const a2 = (globalThis.tag = "a2", 3);"#,
        );
        let facts = analyze_chunk_facts(&module, &BTreeSet::new());
        let mut binding_assignment = BTreeMap::new();
        binding_assignment.insert("a1".to_string(), logical(0));
        binding_assignment.insert("a2".to_string(), logical(0));
        binding_assignment.insert("b1".to_string(), logical(1));
        let owner_graph = build_owner_graph(&facts, &binding_assignment);
        let graph = quotient_owner_graph(&owner_graph);
        let report = validate_schedule(&graph, &render);
        assert_eq!(report.cycles.len(), 1);
        let cycle = &report.cycles[0];
        assert!(
            !cycle.cut.is_empty(),
            "cut should be non-empty for an unrealizable cycle, got {:?}",
            cycle.cut,
        );
        assert!(
            cycle
                .cut
                .iter()
                .all(|e| e.kind == EdgeKind::SideEffectOrder),
            "S-only cycle cut should be all side-effect reasons, got {:?}",
            cycle.cut,
        );
    }

    /// Lazy-only cycle: realizability gate accepts it, so no
    /// CycleReport is emitted and there's no cut to compute.
    #[test]
    fn cut_is_absent_for_lazy_only_cycle() {
        // mod_0 owns helperA, A; mod_1 owns helperB, B. Both
        // helpers reference the other module's binding lazily;
        // no cross-module at-init or side-effect edges.
        let module = parse(
            "function helperA() { return B; } function helperB() { return A; } const A = 1; const B = 2;",
        );
        let facts = analyze_chunk_facts(&module, &BTreeSet::new());
        let mut binding_assignment = BTreeMap::new();
        binding_assignment.insert("helperA".to_string(), logical(0));
        binding_assignment.insert("A".to_string(), logical(0));
        binding_assignment.insert("helperB".to_string(), logical(1));
        binding_assignment.insert("B".to_string(), logical(1));
        let owner_graph = build_owner_graph(&facts, &binding_assignment);
        let graph = quotient_owner_graph(&owner_graph);
        let report = validate_schedule(&graph, &render);
        assert!(
            report.cycles.is_empty(),
            "lazy-only cycle is realizable; the gate must accept and emit no cycle (got {:?})",
            report.cycles,
        );
    }

    fn schedule_for(source: &str, ownership: &[(&str, ModuleId)]) -> Schedule {
        let module = parse(source);
        let facts = analyze_chunk_facts(&module, &BTreeSet::new());
        let mut bindings = BTreeMap::new();
        let mut max_idx = 0usize;
        for (name, id) in ownership {
            bindings.insert(name.to_string(), BindingKind::Owned { owner: *id });
            if let ModuleId::Logical(LogicalModuleIndex(i)) = id {
                max_idx = max_idx.max(*i);
            }
        }
        let logical_modules: Vec<LogicalModule> = (0..=max_idx)
            .map(|i| LogicalModule {
                id: format!("mod_{i}"),
                target_file: format!("mod_{i}.js"),
                residual: false,
                rename_map: BTreeMap::new(),
            })
            .collect();
        Schedule::build(
            "test_chunk".to_string(),
            facts,
            bindings,
            logical_modules,
            BTreeMap::new(),
        )
    }

    fn schedule_with_residual_module(
        source: &str,
        residual_bindings: &[&str],
        logical_bindings: &[&str],
    ) -> Schedule {
        let module = parse(source);
        let facts = analyze_chunk_facts(&module, &BTreeSet::new());
        let residual = logical(0);
        let logical = logical(1);
        let mut bindings = BTreeMap::new();
        for name in residual_bindings {
            bindings.insert(name.to_string(), BindingKind::Owned { owner: residual });
        }
        for name in logical_bindings {
            bindings.insert(name.to_string(), BindingKind::Owned { owner: logical });
        }
        let logical_modules = vec![
            LogicalModule {
                id: "residual".to_string(),
                target_file: "residual/unhandled.js".to_string(),
                residual: true,
                rename_map: BTreeMap::new(),
            },
            LogicalModule {
                id: "mod_1".to_string(),
                target_file: "mod_1.js".to_string(),
                residual: false,
                rename_map: BTreeMap::new(),
            },
        ];
        Schedule::build(
            "test_chunk".to_string(),
            facts,
            bindings,
            logical_modules,
            BTreeMap::new(),
        )
    }

    #[test]
    fn owner_graph_retains_reads_to_unassigned_declared_bindings() {
        let schedule = schedule_for("const A = X + 1; const X = 42;", &[("A", logical(0))]);

        let owner_edge = schedule
            .owner_graph
            .graph
            .edge_weight(OwnerId(0), OwnerId(1))
            .expect("A's owner should point at X's owner before quotienting");
        assert!(
            owner_edge.reasons.iter().any(|reason| matches!(
                reason,
                EdgeReason::AtInitRead {
                    binding,
                    statement_ordinal: StatementOrdinal(0),
                } if binding == "X"
            )),
            "owner graph should retain the unassigned declared provider edge: {owner_edge:?}",
        );
        assert!(
            schedule
                .dep_graph
                .graph
                .contains_edge(logical(0), ModuleId::ResidualEntry),
            "the quotient should expose the logical-module -> residual read",
        );

        let report = schedule.owner_graph_report();
        let residual_owner = report
            .nodes
            .iter()
            .find(|node| node.id == "owner:1")
            .expect("X owner should be reported");
        assert_eq!(residual_owner.destination.id, "residual");
    }

    #[test]
    fn peelability_reports_symbols_currently_peelable_from_residual() {
        let schedule = schedule_with_residual_module(
            "const Leaf = 1; const ResidualUse = Leaf + 1; const Existing = ResidualUse + 1;",
            &["Leaf", "ResidualUse"],
            &["Existing"],
        );

        let report = schedule.owner_graph_report();
        assert_eq!(report.peelability.residual_destinations.len(), 1);
        assert_eq!(
            report.peelability.residual_destinations[0].label,
            "residual"
        );
        let leaf_horizon = report
            .peelability
            .residual_owner_horizon
            .iter()
            .find(|owner| member_bindings(&owner.members) == vec!["Leaf".to_string()])
            .expect("Leaf horizon should be reported");
        assert_eq!(leaf_horizon.status, ResidualOwnerPeelStatus::Direct);
        assert_eq!(leaf_horizon.peel_set_ids.len(), 1);
        assert!(leaf_horizon.companion_options.is_empty());
        assert_eq!(leaf_horizon.statement_ordinal, StatementOrdinal(0));
        assert_eq!(leaf_horizon.statement_kind, StatementKind::VarDecl);
        assert_eq!(leaf_horizon.current_destination.label, "residual");
        assert!(
            report
                .peelability
                .minimal_peel_sets
                .iter()
                .any(
                    |set| member_bindings(&set.members) == vec!["Leaf".to_string()]
                        && set.owner_set_kind == PeelCandidateKind::SingleOwner
                ),
            "Leaf should appear as a singleton peel set: {:#?}",
            report.peelability,
        );
        let leaf = report
            .peelability
            .evaluated_owner_sets
            .iter()
            .find(|candidate| member_bindings(&candidate.members) == vec!["Leaf".to_string()])
            .expect("Leaf candidate should be reported");
        assert_eq!(leaf.owner_set_kind, PeelCandidateKind::SingleOwner);
        assert_eq!(leaf.status, PeelCandidateStatus::PeelableNow);
        assert!(leaf.cycle_blockers.is_empty());
    }

    #[test]
    fn peelability_blocks_symbol_that_would_import_from_residual_entry() {
        let schedule = schedule_for("function Leaf() { return Dep; } const Dep = 1;", &[]);

        let report = schedule.owner_graph_report();
        let leaf_horizon = report
            .peelability
            .residual_owner_horizon
            .iter()
            .find(|owner| member_bindings(&owner.members) == vec!["Leaf".to_string()])
            .expect("Leaf horizon should be reported");
        assert_eq!(leaf_horizon.status, ResidualOwnerPeelStatus::WithCompanions);
        assert!(
            leaf_horizon
                .companion_options
                .iter()
                .any(|option| member_bindings(&option.companion_members)
                    == vec!["Dep".to_string()]),
            "Leaf should point at Dep as a required companion: {:#?}",
            report.peelability,
        );
        let leaf = report
            .peelability
            .evaluated_owner_sets
            .iter()
            .find(|candidate| member_bindings(&candidate.members) == vec!["Leaf".to_string()])
            .expect("Leaf candidate should be reported");
        assert_eq!(leaf.owner_set_kind, PeelCandidateKind::SingleOwner);
        assert_eq!(leaf.status, PeelCandidateStatus::BlockedResidualDependency);
        assert!(
            leaf.cycle_blockers.is_empty(),
            "this is an emit-resolvability blocker, not a cycle blocker: {leaf:#?}",
        );
        assert!(
            leaf.residual_dependency_blockers
                .iter()
                .any(|dependency| member_bindings(&dependency.read_members)
                    == vec!["Dep".to_string()]
                    && !dependency.owner_edge_ids.is_empty()),
            "blocked candidate should point at residual-entry read evidence: {leaf:#?}",
        );
        assert!(
            report.peelability.minimal_peel_sets.iter().any(|closure| {
                member_bindings(&closure.members) == vec!["Dep".to_string(), "Leaf".to_string()]
                    && closure.owner_ids.len() == 2
            }),
            "Leaf should be peelable together with its residual-entry dependency: {:#?}",
            report.peelability,
        );
    }

    #[test]
    fn peelability_blocks_residual_symbol_that_would_create_constraining_scc() {
        let schedule =
            schedule_with_residual_module("const A = B + 1; const B = A + 1;", &["A", "B"], &[]);

        let report = schedule.owner_graph_report();
        let a_horizon = report
            .peelability
            .residual_owner_horizon
            .iter()
            .find(|owner| member_bindings(&owner.members) == vec!["A".to_string()])
            .expect("A horizon should be reported");
        assert_eq!(a_horizon.status, ResidualOwnerPeelStatus::WithCompanions);
        let a = report
            .peelability
            .evaluated_owner_sets
            .iter()
            .find(|candidate| member_bindings(&candidate.members) == vec!["A".to_string()])
            .expect("A candidate should be reported");
        assert_eq!(a.owner_set_kind, PeelCandidateKind::SingleOwner);
        assert_eq!(a.status, PeelCandidateStatus::BlockedCycle);
        assert_eq!(a.cycle_blockers.len(), 1);
        assert!(
            !a.cycle_blockers[0].constraining_owner_edge_ids.is_empty(),
            "blocked candidate should point at owner-edge evidence: {a:#?}",
        );

        let pair = report
            .peelability
            .evaluated_owner_sets
            .iter()
            .find(|candidate| {
                candidate.owner_set_kind == PeelCandidateKind::OwnerPair
                    && member_bindings(&candidate.members) == vec!["A".to_string(), "B".to_string()]
            })
            .expect("A+B should be reported as a pair-only peel candidate");
        assert_eq!(pair.status, PeelCandidateStatus::PeelableNow);
        assert_eq!(pair.owner_ids.len(), 2);
        assert!(pair.cycle_blockers.is_empty());
        assert!(
            report
                .peelability
                .minimal_peel_sets
                .iter()
                .any(|closure| member_bindings(&closure.members)
                    == vec!["A".to_string(), "B".to_string()]),
            "pair closure summary should include A+B: {:#?}",
            report.peelability,
        );
    }

    #[test]
    fn peelability_does_not_overclaim_pair_when_three_owner_cycle_remains() {
        let schedule = schedule_with_residual_module(
            "const A = B + 1; const B = C + 1; const C = A + 1;",
            &["A", "B", "C"],
            &[],
        );

        let report = schedule.owner_graph_report();
        assert!(
            report.peelability.minimal_peel_sets.is_empty(),
            "two-owner closures should not be reported when any pair remains cyclic: {:#?}",
            report.peelability,
        );
        assert!(
            report
                .peelability
                .residual_owner_horizon
                .iter()
                .all(|owner| owner.status == ResidualOwnerPeelStatus::Blocked),
            "three-owner at-init cycle should not expose direct or companion peels: {:#?}",
            report.peelability,
        );
        assert!(
            report
                .peelability
                .evaluated_owner_sets
                .iter()
                .all(|candidate| {
                    candidate.owner_set_kind != PeelCandidateKind::OwnerPair
                        || candidate.status != PeelCandidateStatus::PeelableNow
                }),
            "no pair should be reported as peelable for a three-owner cycle: {:#?}",
            report.peelability,
        );
    }

    // --- Purity classifier ---------------------------------------------------

    fn classify(src: &str) -> Purity {
        // Wrap the expression in a const so we can parse a module.
        let module = parse(&format!("const _ = {src};"));
        let var = match &module.body[0] {
            ModuleItem::Stmt(Stmt::Decl(Decl::Var(var))) => var,
            other => panic!("expected `const _ = ...;`, got {other:?}"),
        };
        let init = var.decls[0].init.as_deref().expect("init expected");
        classify_expr_purity(
            init,
            &BTreeSet::new(),
            &BTreeSet::new(),
            &ChunkCodeGraph::default(),
        )
    }

    /// Run the classifier against `src` after computing the
    /// chunk-top-level shadowed-globals set from a wrapping
    /// module. Lets tests check the shadowing fallback.
    fn classify_with_module(prefix: &str, expr_src: &str) -> Purity {
        let module = parse(&format!("{prefix}\nconst _ = {expr_src};"));
        let shadowed = compute_shadowed_globals(&module.body);
        let var = match module.body.last().expect("non-empty body") {
            ModuleItem::Stmt(Stmt::Decl(Decl::Var(var))) => var,
            other => panic!("expected last stmt to be `const _ = …;`, got {other:?}"),
        };
        let init = var.decls[0].init.as_deref().expect("init expected");
        classify_expr_purity(
            init,
            &shadowed,
            &BTreeSet::new(),
            &ChunkCodeGraph::default(),
        )
    }

    /// Run the classifier against `src` with both shadowing and an
    /// explicit declared-pure binding set.
    fn classify_with_declared_pure(prefix: &str, expr_src: &str, declared: &[&str]) -> Purity {
        let module = parse(&format!("{prefix}\nconst _ = {expr_src};"));
        let shadowed = compute_shadowed_globals(&module.body);
        let declared_pure: BTreeSet<String> = declared.iter().map(|s| (*s).to_string()).collect();
        let var = match module.body.last().expect("non-empty body") {
            ModuleItem::Stmt(Stmt::Decl(Decl::Var(var))) => var,
            other => panic!("expected last stmt to be `const _ = …;`, got {other:?}"),
        };
        let init = var.decls[0].init.as_deref().expect("init expected");
        classify_expr_purity(init, &shadowed, &declared_pure, &ChunkCodeGraph::default())
    }

    #[test]
    fn classify_literal_kinds_are_pure() {
        assert_eq!(classify("42"), Purity::Pure);
        assert_eq!(classify("\"hi\""), Purity::Pure);
        assert_eq!(classify("true"), Purity::Pure);
        assert_eq!(classify("null"), Purity::Pure);
        assert_eq!(classify("/foo/g"), Purity::Pure);
        assert_eq!(classify("`literal`"), Purity::Pure);
    }

    #[test]
    fn classify_ident_read_is_pure() {
        assert_eq!(classify("FOO"), Purity::Pure);
    }

    #[test]
    fn classify_pure_unary_and_binary() {
        assert_eq!(classify("-1"), Purity::Pure);
        assert_eq!(classify("!FOO"), Purity::Pure);
        assert_eq!(classify("typeof FOO"), Purity::Pure);
        assert_eq!(classify("A + 1"), Purity::Pure);
        assert_eq!(classify("A && B"), Purity::Pure);
        assert_eq!(classify("A ? B : C"), Purity::Pure);
    }

    #[test]
    fn classify_delete_is_impure() {
        assert_eq!(classify("delete o.x"), Purity::Impure);
    }

    #[test]
    fn classify_assignment_and_update_are_impure() {
        assert_eq!(classify("(x = 1)"), Purity::Impure);
        assert_eq!(classify("x++"), Purity::Impure);
    }

    #[test]
    fn classify_call_new_tagged_template_are_unknown() {
        assert_eq!(classify("foo()"), Purity::Unknown);
        assert_eq!(classify("new Foo()"), Purity::Unknown);
        assert_eq!(classify("tag`hi ${x}`"), Purity::Unknown);
    }

    #[test]
    fn classify_member_access_is_unknown() {
        assert_eq!(classify("o.x"), Purity::Unknown);
        assert_eq!(classify("o[k]"), Purity::Unknown);
        assert_eq!(classify("o?.x"), Purity::Unknown);
    }

    #[test]
    fn classify_object_literal_pure_when_props_pure() {
        assert_eq!(classify("({ a: 1, b: 'x' })"), Purity::Pure);
        assert_eq!(classify("({ [k]: 1 })"), Purity::Pure);
        // Computed key with member access — getter could fire.
        assert_eq!(classify("({ [k.x]: 1 })"), Purity::Unknown);
        // Spread of an arbitrary expr — iterator could fire.
        assert_eq!(classify("({ ...other })"), Purity::Unknown);
        // Method definitions are pure (defining, not calling).
        assert_eq!(classify("({ m() { return io(); } })"), Purity::Pure);
    }

    #[test]
    fn classify_array_literal_pure_when_elements_pure() {
        assert_eq!(classify("[1, 2, 'x']"), Purity::Pure);
        assert_eq!(classify("[A, B]"), Purity::Pure);
        assert_eq!(classify("[1, foo()]"), Purity::Unknown);
        // Spread is `Unknown` even on an array literal.
        assert_eq!(classify("[...other]"), Purity::Unknown);
    }

    #[test]
    fn classify_function_and_arrow_are_pure() {
        assert_eq!(classify("function () { return io(); }"), Purity::Pure);
        assert_eq!(classify("() => io()"), Purity::Pure);
    }

    #[test]
    fn classify_class_expr_pure_without_static_init() {
        assert_eq!(classify("class { m() { return io(); } }"), Purity::Pure);
        assert_eq!(classify("class { static x = 1 }"), Purity::Pure);
        assert_eq!(classify("class { static x = io() }"), Purity::Impure);
        assert_eq!(classify("class { static {} }"), Purity::Impure);
    }

    #[test]
    fn classify_template_with_pure_exprs_is_pure() {
        assert_eq!(classify("`a${A}b${1+2}c`"), Purity::Pure);
        assert_eq!(classify("`a${foo()}`"), Purity::Unknown);
    }

    #[test]
    fn classify_sequence_takes_worst() {
        assert_eq!(classify("(A, B, C)"), Purity::Pure);
        assert_eq!(classify("(A, foo(), C)"), Purity::Unknown);
        assert_eq!(classify("(A, x = 1, C)"), Purity::Impure);
    }

    // --- Whitelist: pure static property reads -------------------------------

    #[test]
    fn whitelist_static_props_are_pure() {
        // Math / Number / Symbol constants: pure internal-slot
        // reads, no coercion.
        assert_eq!(classify("Math.PI"), Purity::Pure);
        assert_eq!(classify("Math.E"), Purity::Pure);
        assert_eq!(classify("Math.SQRT2"), Purity::Pure);
        assert_eq!(classify("Number.EPSILON"), Purity::Pure);
        assert_eq!(classify("Number.MAX_SAFE_INTEGER"), Purity::Pure);
        assert_eq!(classify("Symbol.iterator"), Purity::Pure);
        assert_eq!(classify("Symbol.toStringTag"), Purity::Pure);
    }

    #[test]
    fn whitelist_misses_fall_back_to_unknown() {
        // Same receivers, properties that aren't on the whitelist:
        // could be a getter / a coercing call. Stays Unknown.
        assert_eq!(classify("Math.unknownProp"), Purity::Unknown);
        assert_eq!(classify("Number.unknownProp"), Purity::Unknown);
        assert_eq!(classify("Symbol.unknownProp"), Purity::Unknown);
    }

    // --- Whitelist: pure calls -----------------------------------------------

    #[test]
    fn whitelist_static_calls_are_pure_regardless_of_arg() {
        // Type predicates do not coerce or read user props on the
        // argument, so any Pure-classified arg keeps the call Pure.
        assert_eq!(classify("Array.isArray(x)"), Purity::Pure);
        assert_eq!(classify("Array.isArray([1, 2, 3])"), Purity::Pure);
        assert_eq!(classify("Number.isNaN(x)"), Purity::Pure);
        assert_eq!(classify("Number.isFinite(x)"), Purity::Pure);
        assert_eq!(classify("Number.isInteger(x)"), Purity::Pure);
        assert_eq!(classify("Number.isSafeInteger(x)"), Purity::Pure);
    }

    #[test]
    fn whitelist_static_calls_unknown_arg_infects() {
        // An argument whose evaluation may itself fire user code
        // poisons the whole call: even though `Array.isArray` is
        // a pure operation, evaluating `io()` first is not.
        assert_eq!(classify("Array.isArray(io())"), Purity::Unknown);
        assert_eq!(classify("Number.isNaN(o.x)"), Purity::Unknown);
    }

    // --- PURE_STATIC_FUNCTION_REFS: read-vs-call distinction ---------------

    #[test]
    fn static_function_ref_object_aliases_are_pure() {
        // Bare member READS access own data properties of the
        // built-in `Object` per ECMA-262 §20.1.2 — no getter
        // fires, no observable side effect. Aliasing the function
        // value into a binding stays pure (the value isn't called).
        assert_eq!(classify("Object.defineProperty"), Purity::Pure);
        assert_eq!(classify("Object.freeze"), Purity::Pure);
        assert_eq!(classify("Object.values"), Purity::Pure);
        assert_eq!(classify("Object.keys"), Purity::Pure);
    }

    #[test]
    fn static_function_ref_object_calls_remain_unknown() {
        // The CALL form of each function-ref entry is unsafe (see
        // `PURE_STATIC_FUNCTION_REFS` doc-comment for why each is
        // excluded from `PURE_STATIC_CALLS`). The function-ref
        // entry only opens the read path; the call must stay
        // Unknown so the soundness contract holds.
        assert_eq!(
            classify("Object.defineProperty(t, 'k', { value: 1 })"),
            Purity::Unknown
        );
        assert_eq!(classify("Object.freeze({ x: 1 })"), Purity::Unknown);
        assert_eq!(classify("Object.values(o)"), Purity::Unknown);
        assert_eq!(classify("Object.keys(o)"), Purity::Unknown);
    }

    #[test]
    fn static_function_ref_object_shadowed_falls_back_to_unknown() {
        // `Object` joins WHITELIST_RECEIVERS in this PR; if the
        // chunk shadows it (via a top-level decl OR an import
        // specifier per A8), the function-ref read must fall back
        // to Unknown — `Object.X` then resolves through the
        // user-bound value.
        assert_eq!(
            classify_with_module("const Object = userland;", "Object.defineProperty"),
            Purity::Unknown
        );
        assert_eq!(
            classify_with_module(
                r#"import { Object } from "./userland.js";"#,
                "Object.freeze"
            ),
            Purity::Unknown
        );
    }

    #[test]
    fn whitelist_global_callables_are_pure() {
        // Boolean(x) is `ToBoolean(x)`; per spec, no path fires
        // user code (objects → true unconditionally; primitives
        // are case-analysed structurally).
        assert_eq!(classify("Boolean(x)"), Purity::Pure);
        assert_eq!(classify("Boolean(0)"), Purity::Pure);
        assert_eq!(classify("Boolean({})"), Purity::Pure);
    }

    #[test]
    fn unsafe_global_callables_stay_unknown() {
        // ToNumber / ToString / ToPrimitive can call user
        // `valueOf` / `toString` / `[Symbol.toPrimitive]` on
        // object args; we don't track types, so these remain
        // Unknown to keep the whitelist sound.
        assert_eq!(classify("Number(x)"), Purity::Unknown);
        assert_eq!(classify("String(x)"), Purity::Unknown);
        assert_eq!(classify("Symbol(x)"), Purity::Unknown);
        assert_eq!(classify("parseInt(x, 10)"), Purity::Unknown);
        assert_eq!(classify("parseFloat(x)"), Purity::Unknown);
        assert_eq!(classify("isNaN(x)"), Purity::Unknown);
        assert_eq!(classify("isFinite(x)"), Purity::Unknown);
    }

    #[test]
    fn unsafe_static_calls_stay_unknown() {
        // Anything that coerces / iterates / fires getters /
        // mutates / reads through proxies is *not* on the
        // whitelist. These all stay Unknown.
        for src in [
            "Array.from(x)",
            "Array.of(1, 2, 3)",
            "Math.abs(x)",
            "Math.max(1, 2)",
            "Math.floor(x)",
            "Math.round(x)",
            "Math.sqrt(x)",
            "Object.keys(x)",
            "Object.values(x)",
            "Object.entries(x)",
            "Object.freeze(x)",
            "Object.assign({}, x)",
            "Object.fromEntries(x)",
            "Object.getOwnPropertyDescriptor(x, 'k')",
            "Object.hasOwn(x, 'k')",
            "JSON.parse(x)",
            "JSON.stringify(x)",
            "Number.parseInt(x)",
            "Number.parseFloat(x)",
            "String.fromCharCode(65)",
            "String.fromCodePoint(65)",
            "Symbol.for('k')",
            "Symbol.keyFor(s)",
        ] {
            assert_eq!(
                classify(src),
                Purity::Unknown,
                "expected {src} to stay Unknown (would fire user code)"
            );
        }
    }

    // --- Whitelist: shadowing fallback ---------------------------------------

    #[test]
    fn shadowed_receiver_disables_whitelist() {
        // A chunk-top-level binding for `Math` makes `Math.PI` no
        // longer reach the global; the whitelist must fall back
        // to Unknown.
        assert_eq!(
            classify_with_module("const Math = userland;", "Math.PI"),
            Purity::Unknown
        );
        assert_eq!(
            classify_with_module("function Math() {}", "Math.E"),
            Purity::Unknown
        );
        assert_eq!(
            classify_with_module("const Array = X;", "Array.isArray(x)"),
            Purity::Unknown
        );
        assert_eq!(
            classify_with_module("let Number = X;", "Number.isNaN(x)"),
            Purity::Unknown
        );
        assert_eq!(
            classify_with_module("const Boolean = X;", "Boolean(x)"),
            Purity::Unknown
        );
    }

    #[test]
    fn unshadowed_receiver_keeps_whitelist() {
        // A chunk that declares an unrelated binding leaves the
        // whitelist active — only same-named shadowing disables.
        assert_eq!(
            classify_with_module("const other = userland;", "Math.PI"),
            Purity::Pure
        );
    }

    #[test]
    fn import_specifier_locals_shadow_whitelist() {
        // Import bindings are top-level lexical decls and shadow
        // the global the same way `const Math = …` does. The
        // classifier must reach the same Unknown fallback. (Soundness
        // matters: the imported value can be anything, so
        // `<imported>.<prop>` is a property read that may fire a
        // user-defined getter.)
        assert_eq!(
            classify_with_module(r#"import { Math } from "./userland.js";"#, "Math.PI"),
            Purity::Unknown
        );
        assert_eq!(
            classify_with_module(r#"import Boolean from "./userland.js";"#, "Boolean(x)"),
            Purity::Unknown
        );
        assert_eq!(
            classify_with_module(
                r#"import * as Number from "./userland.js";"#,
                "Number.isNaN(x)"
            ),
            Purity::Unknown
        );
        assert_eq!(
            classify_with_module(
                r#"import { something as Array } from "./userland.js";"#,
                "Array.isArray(x)"
            ),
            Purity::Unknown
        );
    }

    // --- Declared purity (spec annotation) ---------------------------------

    #[test]
    fn declared_pure_ident_call_classifies_pure() {
        // A spec member with `purity: "pure"` populates the
        // declared-pure set. A call whose callee is the bound
        // Ident classifies Pure regardless of the body content
        // (the validator does not re-verify; author trust). Args
        // are still evaluated normally — pure args here, so the
        // whole call is Pure.
        assert_eq!(
            classify_with_declared_pure("function f(x) { return x; }", "f(42)", &["f"]),
            Purity::Pure
        );
        assert_eq!(
            classify_with_declared_pure("function f(x) { return x; }", "f({ k: 'v' })", &["f"]),
            Purity::Pure
        );
    }

    #[test]
    fn declared_pure_call_with_impure_arg_inherits_arg_purity() {
        // The declared-purity contract covers the function value;
        // arg evaluation is independent. An impure arg makes the
        // whole call Unknown.
        assert_eq!(
            classify_with_declared_pure(
                "function f(x) { return x; } function io() { return 1; }",
                "f(io())",
                &["f"]
            ),
            Purity::Unknown
        );
    }

    #[test]
    fn declared_pure_overrides_global_shadowing() {
        // Author trust contract: a declared-pure annotation wins
        // over both the whitelist's shadowing fallback and the
        // body's actual contents. The validator does not
        // second-guess.
        assert_eq!(
            classify_with_declared_pure(
                r#"import { Boolean } from "./userland.js";"#,
                "Boolean(x)",
                &["Boolean"]
            ),
            Purity::Pure
        );
    }

    #[test]
    fn declared_pure_does_not_bleed_to_unannotated_callees() {
        // Only the listed binding is treated pure. A call to a
        // sibling that wasn't annotated stays subject to the
        // normal classifier path (Unknown for opaque idents).
        assert_eq!(
            classify_with_declared_pure(
                "function pure(x) { return x; } function impure(x) { return x; }",
                "impure(x)",
                &["pure"]
            ),
            Purity::Unknown
        );
    }

    // --- ChunkCodeGraph: function-body purity inference --------------------

    /// Build a `ChunkCodeGraph` for `src` and return the purity it
    /// computed for the named function. Tests the full pipeline:
    /// chunk parsing → function collection → fixed-point.
    fn fn_purity(src: &str, name: &str) -> Option<Purity> {
        let module = parse(src);
        let body = split_comma_list_var_decls(&module.body);
        let shadowed = compute_shadowed_globals(&body);
        let graph = ChunkCodeGraph::build(&body, &shadowed, &BTreeSet::new());
        graph.function_purity(name)
    }

    #[test]
    fn fn_purity_pure_hof_wrapper() {
        // Body returns a fresh object literal whose values are a
        // bound parameter — no observable side effect.
        assert_eq!(
            fn_purity(
                r#"function wrap(f) { return { kind: "wrapped", impl: f }; }"#,
                "wrap"
            ),
            Some(Purity::Pure)
        );
    }

    #[test]
    fn fn_purity_impure_globalthis_write() {
        // Assignment to a member of `globalThis` is unambiguously
        // impure regardless of what's on the RHS.
        assert_eq!(
            fn_purity("function tag(x) { globalThis.tag = x; }", "tag"),
            Some(Purity::Impure)
        );
    }

    #[test]
    fn fn_purity_unknown_when_calling_console_log() {
        // `console.log(...)` is a member-call on a non-whitelisted
        // receiver — Unknown. Caller inherits.
        assert_eq!(
            fn_purity(
                r#"function logged(x) { console.log("init", x); return x; }"#,
                "logged"
            ),
            Some(Purity::Unknown)
        );
    }

    #[test]
    fn fn_purity_propagates_transitive_impurity() {
        // `caller` only calls `tainted`. `tainted` writes
        // `globalThis.touched`, so it's Impure. Fixed-point
        // propagates: `caller` becomes Impure on iteration 2.
        let src = r#"
            function tainted() { globalThis.touched = true; return 1; }
            function caller() { return tainted(); }
        "#;
        assert_eq!(fn_purity(src, "tainted"), Some(Purity::Impure));
        assert_eq!(fn_purity(src, "caller"), Some(Purity::Impure));
    }

    #[test]
    fn fn_purity_mutual_recursion_converges_pure() {
        // `even` and `odd` only reference each other inside their
        // bodies. Optimistic init (Pure) holds through the
        // fixed-point — neither body has an impure operation.
        let src = r#"
            function even(n) { return n === 0 ? true : odd(n - 1); }
            function odd(n) { return n === 0 ? false : even(n - 1); }
        "#;
        assert_eq!(fn_purity(src, "even"), Some(Purity::Pure));
        assert_eq!(fn_purity(src, "odd"), Some(Purity::Pure));
    }

    #[test]
    fn fn_purity_arrow_const_init() {
        // `const f = (x) => …` — chunk-top function in a VarDecl
        // initializer. Concise-arrow body classifies the single
        // return expression.
        assert_eq!(
            fn_purity("const wrap = (x) => ({ val: x });", "wrap"),
            Some(Purity::Pure)
        );
    }

    #[test]
    fn fn_purity_call_inherits_chunk_local_function_purity() {
        // `f()` where `f` is a chunk-top function in the cache
        // resolves through `ChunkCodeGraph::function_purity`. With
        // `f` body Pure, the call is Pure.
        let module = parse("function f() { return 42; } const x = f();");
        let body = split_comma_list_var_decls(&module.body);
        let shadowed = compute_shadowed_globals(&body);
        let graph = ChunkCodeGraph::build(&body, &shadowed, &BTreeSet::new());
        let var = match &body[1] {
            ModuleItem::Stmt(Stmt::Decl(Decl::Var(var))) => var,
            other => panic!("expected VarDecl, got {other:?}"),
        };
        let init = var.decls[0].init.as_deref().expect("init");
        assert_eq!(
            classify_expr_purity(init, &shadowed, &BTreeSet::new(), &graph),
            Purity::Pure
        );
    }

    #[test]
    fn fn_purity_let_var_bound_arrows_are_not_cached() {
        // `let` and `var` bindings are reassignable. Caching their
        // body's purity would be unsound: a later `f = …` could
        // replace the value with something impure between graph
        // construction and the call site. Restrict graph entries
        // to `const`-bound function/arrow initializers.
        assert_eq!(
            fn_purity("let f = () => 1;", "f"),
            None,
            "`let`-bound arrow must not be in the function-purity graph"
        );
        assert_eq!(
            fn_purity("var f = function () { return 1; };", "f"),
            None,
            "`var`-bound function expr must not be in the function-purity graph"
        );
        // Sanity: `const` still works.
        assert_eq!(fn_purity("const f = () => 1;", "f"), Some(Purity::Pure));
    }

    #[test]
    fn fn_purity_throw_makes_function_impure_even_with_pure_arg() {
        // `throw e` alters control flow observably regardless of
        // whether `e` itself is pure. A function that always
        // throws must not classify as Pure.
        assert_eq!(
            fn_purity(r#"function f() { throw "boom"; }"#, "f"),
            Some(Purity::Impure)
        );
        // Conditional throw is still Impure (we don't reason
        // about reachability — soundness-first).
        assert_eq!(
            fn_purity(r#"function f(x) { if (x) throw "boom"; return x; }"#, "f"),
            Some(Purity::Impure)
        );
    }

    #[test]
    fn fn_purity_debugger_makes_function_impure() {
        // `debugger` pauses execution observably to a host
        // attached to the process — not Pure.
        assert_eq!(
            fn_purity("function f() { debugger; return 1; }", "f"),
            Some(Purity::Impure)
        );
    }

    // --- Call-graph topology: deep chains, isolated nodes ------------------

    #[test]
    fn fn_purity_deep_pure_chain_propagates_in_one_pass() {
        // `a → b → c → d → e`: a long chain of chunk-local calls,
        // each function pure on its own. SCC bottom-up classifies
        // `e` first (no callees), then `d`, ..., then `a` — each
        // function classified once. With the previous global
        // fixed-point this would still terminate but rewalk every
        // body each pass; with SCC-bottom-up each is touched once.
        let src = r#"
            function e() { return 0; }
            function d() { return e(); }
            function c() { return d(); }
            function b() { return c(); }
            function a() { return b(); }
        "#;
        for name in ["a", "b", "c", "d", "e"] {
            assert_eq!(
                fn_purity(src, name),
                Some(Purity::Pure),
                "expected {name} to classify Pure"
            );
        }
    }

    #[test]
    fn fn_purity_deep_chain_propagates_impurity_to_root() {
        // Same shape but `e` writes `globalThis`. SCC processes
        // `e` first → Impure; the worklist propagates Impure up
        // the chain (`d` calls `e` → Impure; `c` calls `d` →
        // Impure; ...; `a` → Impure). Each function still only
        // re-classified after a callee changes — bounded total
        // work even on long chains.
        let src = r#"
            function e() { globalThis.touched = true; return 0; }
            function d() { return e(); }
            function c() { return d(); }
            function b() { return c(); }
            function a() { return b(); }
        "#;
        for name in ["a", "b", "c", "d", "e"] {
            assert_eq!(
                fn_purity(src, name),
                Some(Purity::Impure),
                "expected {name} to inherit Impure from `e`"
            );
        }
    }

    #[test]
    fn fn_purity_independent_functions_isolated_in_call_graph() {
        // No edges between `a` / `b` / `c`. Each is its own SCC;
        // classification of each is independent. `a` Impure must
        // not affect `b` or `c`.
        let src = r#"
            function a() { globalThis.touched = true; }
            function b() { return 1; }
            function c() { return 2; }
        "#;
        assert_eq!(fn_purity(src, "a"), Some(Purity::Impure));
        assert_eq!(fn_purity(src, "b"), Some(Purity::Pure));
        assert_eq!(fn_purity(src, "c"), Some(Purity::Pure));
    }

    #[test]
    fn fn_purity_mutual_recursion_with_external_impure_callee() {
        // Mutual recursion `a <-> b` (one SCC) + `a` also calls
        // `c` (separate SCC, Impure). `c` is processed first
        // (sink); `c` Impure. SCC {a, b}: optimistic Pure init,
        // worklist sees `a` calls `c` (Impure) → `a` becomes
        // Impure → `b` (which calls `a`) gets pushed to worklist
        // → `b` becomes Impure.
        let src = r#"
            function c() { globalThis.touched = true; return 0; }
            function a(n) { return n === 0 ? c() : b(n - 1); }
            function b(n) { return n === 0 ? 0 : a(n - 1); }
        "#;
        assert_eq!(fn_purity(src, "c"), Some(Purity::Impure));
        assert_eq!(fn_purity(src, "a"), Some(Purity::Impure));
        assert_eq!(fn_purity(src, "b"), Some(Purity::Impure));
    }

    // --- has_side_effect refinement ------------------------------------------

    fn has_side_effect_for(src: &str) -> Vec<bool> {
        let module = parse(src);
        analyze_chunk_facts(&module, &BTreeSet::new())
            .into_iter()
            .map(|f| f.has_side_effect)
            .collect()
    }

    #[test]
    fn pure_const_decl_is_not_side_effecting() {
        assert_eq!(has_side_effect_for("const X = 42;"), vec![false]);
        assert_eq!(has_side_effect_for("const X = { a: 1 };"), vec![false]);
        assert_eq!(has_side_effect_for("const X = [1, 2, 3];"), vec![false]);
        assert_eq!(has_side_effect_for("const X = OTHER;"), vec![false]);
        assert_eq!(has_side_effect_for("const X = A + B;"), vec![false]);
    }

    #[test]
    fn impure_const_decl_is_side_effecting() {
        assert_eq!(has_side_effect_for("const X = compute();"), vec![true]);
        assert_eq!(has_side_effect_for("const X = new Foo();"), vec![true]);
        assert_eq!(has_side_effect_for("const X = (y = 1, y);"), vec![true]);
    }

    #[test]
    fn function_decl_is_not_side_effecting() {
        assert_eq!(
            has_side_effect_for("function f() { return io(); }"),
            vec![false]
        );
    }

    #[test]
    fn class_decl_pure_without_static_init() {
        assert_eq!(
            has_side_effect_for("class C { m() { return io(); } }"),
            vec![false]
        );
        assert_eq!(
            has_side_effect_for("class C { static x = 1; }"),
            vec![false]
        );
        assert_eq!(
            has_side_effect_for("class C { static x = io(); }"),
            vec![true]
        );
        assert_eq!(has_side_effect_for("class C { static {} }"), vec![true]);
    }

    #[test]
    fn bare_expression_classified_by_purity() {
        // Plain ident-read expression statement: pure.
        assert_eq!(has_side_effect_for("X;"), vec![false]);
        // Function call expression statement: side-effecting.
        assert_eq!(has_side_effect_for("io();"), vec![true]);
    }

    #[test]
    fn multi_declarator_var_decl_is_side_effecting_if_any_init_is() {
        // After the comma-list pre-split, a multi-declarator
        // var-decl becomes one row per declarator. So a
        // mixed-purity comma-list produces both a Pure row and
        // an Impure row, not a single conservative row.
        assert_eq!(
            has_side_effect_for("const A = 1, B = compute();"),
            vec![false, true]
        );
        assert_eq!(
            has_side_effect_for("const A = 1, B = 2, C = 3;"),
            vec![false, false, false]
        );
    }

    // --- Comma-list splitter -------------------------------------------------

    fn statement_kinds(source: &str) -> Vec<StatementKind> {
        let module = parse(source);
        analyze_chunk_facts(&module, &BTreeSet::new())
            .into_iter()
            .map(|f| f.kind)
            .collect()
    }

    fn declared_per_statement(source: &str) -> Vec<Vec<String>> {
        let module = parse(source);
        analyze_chunk_facts(&module, &BTreeSet::new())
            .into_iter()
            .map(|f| f.declared.into_iter().collect::<Vec<_>>())
            .collect()
    }

    #[test]
    fn split_two_declarator_const() {
        assert_eq!(
            statement_kinds("const A = 1, B = 2;"),
            vec![StatementKind::VarDecl, StatementKind::VarDecl]
        );
        assert_eq!(
            declared_per_statement("const A = 1, B = 2;"),
            vec![vec!["A".to_string()], vec!["B".to_string()]]
        );
    }

    #[test]
    fn split_three_declarator_let() {
        assert_eq!(
            declared_per_statement("let A = 1, B = 2, C = 3;"),
            vec![
                vec!["A".to_string()],
                vec!["B".to_string()],
                vec!["C".to_string()],
            ]
        );
    }

    #[test]
    fn split_export_const_with_comma_list() {
        // `export const A = 1, B = 2;` splits into two ExportDecls,
        // each declaring one name. Kind stays VarDecl (per
        // classify_item, ExportDecl-of-Var classifies as VarDecl).
        assert_eq!(
            statement_kinds("export const A = 1, B = 2;"),
            vec![StatementKind::VarDecl, StatementKind::VarDecl]
        );
        assert_eq!(
            declared_per_statement("export const A = 1, B = 2;"),
            vec![vec!["A".to_string()], vec!["B".to_string()]]
        );
    }

    #[test]
    fn single_declarator_var_decl_is_unchanged() {
        assert_eq!(statement_kinds("var A;"), vec![StatementKind::VarDecl]);
        assert_eq!(
            declared_per_statement("var A;"),
            vec![vec!["A".to_string()]]
        );
    }

    #[test]
    fn non_var_decl_statements_are_not_split() {
        // function / class declarations have no comma-list shape.
        // Mixed source: const + function + class + bare expression.
        assert_eq!(
            statement_kinds("const A = 1; function f() {} class C {} 'side-effecting-string';"),
            vec![
                StatementKind::VarDecl,
                StatementKind::FnDecl,
                StatementKind::ClassDecl,
                StatementKind::SideEffect,
            ]
        );
    }

    // --- Comma-list owner attribution in owner graph quotient ---------------

    #[test]
    fn split_comma_list_attributes_reads_per_declarator() {
        // `const A = 1, B = X;` — A → mod_0, B → mod_1, X → mod_1.
        // Pre-split, `stmt_owner` would pick A's owner (mod_0)
        // for the whole comma-list and attribute `B`'s read of X
        // to mod_0, creating an R-edge mod_0 → mod_1 even though
        // the actual emitted module for B is mod_1. Post-split,
        // each declarator is its own statement: A's row owns
        // nothing readwise (literal init), B's row owns the read
        // of X but its home is mod_1 — so no edge (B reads X
        // within its own module).
        let schedule = schedule_for(
            "const A = 1, B = X; const X = 42;",
            &[("A", logical(0)), ("B", logical(1)), ("X", logical(1))],
        );
        // No cross-module read edges should exist: A's init is
        // pure, B reads X (same module).
        let mod_0 = ModuleId::Logical(LogicalModuleIndex(0));
        let mod_1 = ModuleId::Logical(LogicalModuleIndex(1));
        assert!(
            !schedule.dep_graph.graph.contains_edge(mod_0, mod_1),
            "no edge mod_0 → mod_1 expected, got: {:?}",
            schedule.dep_graph.graph.edge_weight(mod_0, mod_1),
        );
        assert!(
            !schedule.dep_graph.graph.contains_edge(mod_1, mod_0),
            "no edge mod_1 → mod_0 expected, got: {:?}",
            schedule.dep_graph.graph.edge_weight(mod_1, mod_0),
        );
    }

    #[test]
    fn split_comma_list_surfaces_real_cross_declarator_cycle() {
        // `const A = X, B = 1;` — A → mod_a, B → mod_b, X → mod_b.
        // mod_a's `A` reads X from mod_b → R-edge mod_a → mod_b.
        // Now also `const Y = A;` in mod_b reads A from mod_a:
        // → R-edge mod_b → mod_a. Cycle.
        //
        // Pre-split, the comma-list `const A = X, B = 1;` would
        // attribute the read of X to mod_a (A is declared first,
        // owner mod_a). So the edge is mod_a → mod_b. mod_b's
        // `Y = A` adds mod_b → mod_a. Cycle detected (correctly,
        // by accident). Post-split, A's row attributes the read
        // to mod_a, B's row to mod_b — same edges, same cycle.
        // This case demonstrates the split doesn't *miss* real
        // cycles either: the bug bit when multiple declarators
        // had differently-owned reads on the same line.
        let schedule = schedule_for(
            "const A = X, B = 1; const X = 42; const Y = A;",
            &[
                ("A", logical(0)),
                ("B", logical(1)),
                ("X", logical(1)),
                ("Y", logical(1)),
            ],
        );
        let report = schedule.validate();
        assert!(
            !report.cycles.is_empty(),
            "expected a real cycle to be reported"
        );
    }

    // --- linker_order in ScheduleReport --------------------------------------

    #[test]
    fn validate_surfaces_linker_order_for_acyclic_spec() {
        // mod_0 reads B from mod_1 at-init → mod_1 must precede
        // mod_0 in the linker's evaluation order.
        let schedule = schedule_for(
            "const A = B + 1; const B = 42;",
            &[("A", logical(0)), ("B", logical(1))],
        );
        let report = schedule.validate();
        let order = &report.linker_order;
        let pos = |name: &str| -> usize {
            order
                .iter()
                .position(|m| m == name)
                .unwrap_or_else(|| panic!("module {name} not in {order:?}"))
        };
        assert!(
            pos("mod_1") < pos("mod_0"),
            "mod_1 must precede mod_0 in linker_order; got {order:?}",
        );
    }

    #[test]
    fn validate_returns_empty_linker_order_for_cyclic_spec() {
        // mod_0 reads B (mod_1); mod_1 reads A (mod_0). Cycle.
        let schedule = schedule_for(
            "const A = B + 1; const B = A + 1;",
            &[("A", logical(0)), ("B", logical(1))],
        );
        let report = schedule.validate();
        assert!(!report.cycles.is_empty(), "expected a cycle in {report:?}",);
        assert!(
            report.linker_order.is_empty(),
            "linker_order must be empty when the dep graph is cyclic; got {:?}",
            report.linker_order,
        );
    }

    #[test]
    fn schedule_report_serializes_linker_order_as_snake_case() {
        let schedule = schedule_for(
            "const A = 1; const B = A + 1;",
            &[("A", logical(0)), ("B", logical(1))],
        );
        let report = schedule.validate();
        let json = serde_json::to_string(&report).expect("serialize ScheduleReport");
        assert!(
            json.contains(r#""linker_order""#),
            "ScheduleReport must serialize linker_order as `linker_order`; got: {json}",
        );
    }
}
