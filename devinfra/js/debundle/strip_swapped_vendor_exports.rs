use std::collections::{BTreeMap, BTreeSet};

use anyhow::{Context, Result, bail};
use binding_targets::{
    TargetAccessRecorder, binding_names, record_assign_target, record_update_target,
};
use serde::Serialize;
use swc_ecma_ast::*;
use swc_ecma_visit::{Visit, VisitWith};

use artifact::{ChunkBundle, JsFile, get_chunk_entry_path};
use spec::{PartialSwapSymbol, VendorLevel, VendorMark};

pub struct StripSwappedVendorExportsResult {
    pub artifact: ChunkBundle,
    pub manifest: StripSwappedVendorExportsManifest,
}

#[derive(Debug, Clone, Serialize)]
pub struct StripSwappedVendorExportsManifest {
    pub per_chunk: BTreeMap<String, ChunkStripStats>,
}

#[derive(Debug, Clone, Serialize)]
pub struct ChunkStripStats {
    pub chunk_path: String,
    pub stripped_export_specifiers: usize,
    pub dropped_top_level_items: usize,
    pub retained_top_level_items: usize,
}

/// Per-chunk pass that drops swapped names from the vendor entry's
/// trailing `export { … }` block (Phase 1) and sweeps top-level
/// bindings that are no longer reachable from the residual export
/// surface plus retained side-effect statements (Phase 2).
///
/// Runs after `apply_partial_vendor_swaps` — the consumer side has
/// already been rewritten to import each swapped name from upstream,
/// so the chunk's residual `export { … }` entries for those names
/// are dead weight. Without this pass the on-disk vendor blob stays
/// byte-identical to pre-swap.
pub fn strip_swapped_vendor_exports(
    mut artifact: ChunkBundle,
    vendor: &BTreeMap<String, VendorMark>,
) -> Result<StripSwappedVendorExportsResult> {
    let chunk_table = artifact.chunk_table.clone();
    let mut per_chunk = BTreeMap::new();

    for (chunk_path, mark) in vendor {
        let symbols = match &mark.level {
            VendorLevel::PartialSwap(partial) => &partial.symbols,
            VendorLevel::BundledPartialSwap(partial) => &partial.symbols,
            _ => continue,
        };

        let chunk_name = chunk_id_from_chunk_path(chunk_path)?;
        let chunk_id = chunk_table.get(&chunk_name).with_context(|| {
            format!(
                "strip_swapped_vendor_exports vendor entry {chunk_path} targets unknown chunk: {chunk_name}"
            )
        })?;
        let entry_relative_file = get_chunk_entry_path(&artifact, chunk_id).with_context(|| {
            format!(
                "strip_swapped_vendor_exports vendor entry {chunk_path} targets missing chunk (chunk_id={chunk_name})"
            )
        })?;

        let js_chunk = artifact.js_chunk_mut(chunk_id)?;
        let file = js_chunk.remove_file(&entry_relative_file).with_context(|| {
            format!(
                "strip_swapped_vendor_exports vendor entry {chunk_path}: entry file {entry_relative_file} missing from chunk {chunk_name}"
            )
        })?;
        let (parts, mut ast) = file.into_ast_parts().with_context(|| {
            format!(
                "strip_swapped_vendor_exports vendor entry {chunk_path}: chunk {chunk_name} entry has no AST"
            )
        })?;

        let stats = strip_one_chunk(&mut ast.module, symbols, chunk_path)?;
        per_chunk.insert(chunk_path.clone(), stats);

        js_chunk.insert_file(JsFile::from_ast_parts(parts, ast));
    }

    Ok(StripSwappedVendorExportsResult {
        artifact,
        manifest: StripSwappedVendorExportsManifest { per_chunk },
    })
}

fn strip_one_chunk(
    module: &mut Module,
    symbols: &BTreeMap<String, PartialSwapSymbol>,
    chunk_path: &str,
) -> Result<ChunkStripStats> {
    let swapped: BTreeSet<String> = symbols.keys().cloned().collect();

    split_top_level_var_decls(module);
    let stripped = strip_export_specifiers(module, symbols, chunk_path)?;
    let stripped_export_specifiers = stripped.len();
    let post_strip_exports = collect_exported_names(module);

    let dropped_total_before = module.body.len();
    sweep_unreachable_top_level(module, &post_strip_exports, &stripped, chunk_path)?;
    let retained = module.body.len();
    let dropped = dropped_total_before - retained;

    // Phase 2 must not change the export surface relative to Phase 1.
    let post_dce_exports = collect_exported_names(module);
    if post_dce_exports != post_strip_exports {
        let removed: Vec<_> = post_strip_exports
            .difference(&post_dce_exports)
            .cloned()
            .collect();
        let added: Vec<_> = post_dce_exports
            .difference(&post_strip_exports)
            .cloned()
            .collect();
        bail!(
            "strip_swapped_vendor_exports vendor entry {chunk_path}: DCE pass changed the export surface (removed=[{}], added=[{}])",
            removed.join(","),
            added.join(","),
        );
    }

    // Sanity: stripped names should not appear in pre or post export set.
    let leaked: Vec<_> = swapped.intersection(&post_strip_exports).cloned().collect();
    if !leaked.is_empty() {
        bail!(
            "strip_swapped_vendor_exports vendor entry {chunk_path}: swapped names still exported after strip: [{}]",
            leaked.join(","),
        );
    }

    Ok(ChunkStripStats {
        chunk_path: chunk_path.to_string(),
        stripped_export_specifiers,
        dropped_top_level_items: dropped,
        retained_top_level_items: retained,
    })
}

#[derive(Debug, Clone)]
struct StrippedExport {
    package: String,
    locals: BTreeSet<Id>,
}

fn chunk_id_from_chunk_path(chunk_path: &str) -> Result<String> {
    if chunk_path.is_empty() {
        bail!("strip_swapped_vendor_exports: empty chunk path");
    }
    let chunk_id = chunk_path.strip_suffix(".js").with_context(|| {
        format!("strip_swapped_vendor_exports: chunk path must end in .js: {chunk_path}")
    })?;
    Ok(chunk_id.to_string())
}

/// Walk `module.body` once and strip the chunk's *local* re-exports of
/// every name in `swapped`. Two shapes are handled:
///
/// - `export { x, y as z }` (`ExportNamed` with `src.is_none()`): the
///   matching specifier is dropped from the list; an empty list collapses
///   the statement.
/// - `export const x = …` / `export function x() {}` / `export class x {}`
///   (`ExportDecl`): the `export` prefix is dropped — the declaration
///   itself stays, becoming a chunk-local binding the DCE pass can
///   collect if no live item references it.
///
/// `export { x } from "./y"` (`ExportNamed` with `src.is_some()`) is left
/// alone — those forward upstream names through a side import, not from
/// a chunk-local binding.
fn strip_export_specifiers(
    module: &mut Module,
    symbols: &BTreeMap<String, PartialSwapSymbol>,
    chunk_path: &str,
) -> Result<BTreeMap<String, StrippedExport>> {
    let swapped: BTreeSet<String> = symbols.keys().cloned().collect();
    let mut found: BTreeMap<String, StrippedExport> = BTreeMap::new();
    let mut new_body = Vec::with_capacity(module.body.len());

    for item in std::mem::take(&mut module.body) {
        match item {
            ModuleItem::ModuleDecl(ModuleDecl::ExportNamed(mut named)) => {
                if named.src.is_some() {
                    new_body.push(ModuleItem::ModuleDecl(ModuleDecl::ExportNamed(named)));
                    continue;
                }
                let mut kept = Vec::with_capacity(named.specifiers.len());
                for spec in std::mem::take(&mut named.specifiers) {
                    let ExportSpecifier::Named(ref named_spec) = spec else {
                        kept.push(spec);
                        continue;
                    };
                    let exported = named_spec
                        .exported
                        .as_ref()
                        .map(module_export_name)
                        .unwrap_or_else(|| module_export_name(&named_spec.orig));
                    if swapped.contains(&exported) {
                        let Some(symbol) = symbols.get(&exported) else {
                            unreachable!("swapped names are derived from symbols");
                        };
                        let local = match &named_spec.orig {
                            ModuleExportName::Ident(ident) => ident.to_id(),
                            ModuleExportName::Str(orig) => {
                                bail!(
                                    "strip_swapped_vendor_exports vendor entry {chunk_path}: swapped export {exported} uses string-literal local name {:?}, which cannot be mapped to a chunk binding",
                                    orig.value,
                                );
                            }
                        };
                        found.insert(
                            exported,
                            StrippedExport {
                                package: symbol.package.clone(),
                                locals: BTreeSet::from([local]),
                            },
                        );
                    } else {
                        kept.push(spec);
                    }
                }
                if kept.is_empty() {
                    continue;
                }
                named.specifiers = kept;
                new_body.push(ModuleItem::ModuleDecl(ModuleDecl::ExportNamed(named)));
            }
            ModuleItem::ModuleDecl(ModuleDecl::ExportDecl(export_decl)) => {
                let inline_names = export_decl_declared_names(&export_decl.decl);
                // For an `ExportDecl`, every declared name is exported
                // under that same name. Drop the `export` prefix only
                // if *all* names declared by the statement are swapped;
                // otherwise we'd silently un-export a non-swapped
                // sibling (legal but surprising for a multi-declarator
                // `export const a = …, b = …`).
                if !inline_names.is_empty() && inline_names.iter().all(|n| swapped.contains(n)) {
                    for n in &inline_names {
                        let Some(symbol) = symbols.get(n) else {
                            unreachable!("inline names were checked against symbols");
                        };
                        found.insert(
                            n.clone(),
                            StrippedExport {
                                package: symbol.package.clone(),
                                locals: export_decl_declared_ids(&export_decl.decl),
                            },
                        );
                    }
                    new_body.push(ModuleItem::Stmt(Stmt::Decl(export_decl.decl)));
                } else {
                    new_body.push(ModuleItem::ModuleDecl(ModuleDecl::ExportDecl(export_decl)));
                }
            }
            other => new_body.push(other),
        }
    }
    module.body = new_body;

    let found_names = found.keys().cloned().collect::<BTreeSet<_>>();
    let missing: Vec<String> = swapped.difference(&found_names).cloned().collect();
    if !missing.is_empty() {
        bail!(
            "strip_swapped_vendor_exports vendor entry {chunk_path}: swapped symbols not found in any chunk-local export: [{}]",
            missing.join(","),
        );
    }
    Ok(found)
}

fn export_decl_declared_names(decl: &Decl) -> Vec<String> {
    match decl {
        Decl::Fn(f) => vec![f.ident.sym.to_string()],
        Decl::Class(c) => vec![c.ident.sym.to_string()],
        Decl::Var(v) => {
            let mut out = Vec::new();
            for d in &v.decls {
                collect_pat_names(&d.name, &mut out);
            }
            out
        }
        _ => Vec::new(),
    }
}

fn export_decl_declared_ids(decl: &Decl) -> BTreeSet<Id> {
    match decl {
        Decl::Fn(f) => BTreeSet::from([f.ident.to_id()]),
        Decl::Class(c) => BTreeSet::from([c.ident.to_id()]),
        Decl::Var(v) => v
            .decls
            .iter()
            .flat_map(|d| binding_names(&d.name))
            .collect(),
        _ => BTreeSet::new(),
    }
}

fn split_top_level_var_decls(module: &mut Module) {
    let mut out = Vec::with_capacity(module.body.len());
    for item in std::mem::take(&mut module.body) {
        match item {
            ModuleItem::Stmt(Stmt::Decl(Decl::Var(var))) if var.decls.len() > 1 => {
                for decl in var.decls {
                    out.push(ModuleItem::Stmt(Stmt::Decl(Decl::Var(Box::new(VarDecl {
                        span: var.span,
                        ctxt: var.ctxt,
                        kind: var.kind,
                        declare: var.declare,
                        decls: vec![decl],
                    })))));
                }
            }
            ModuleItem::ModuleDecl(ModuleDecl::ExportDecl(export_decl)) => match export_decl.decl {
                Decl::Var(var) if var.decls.len() > 1 => {
                    for decl in var.decls {
                        out.push(ModuleItem::ModuleDecl(ModuleDecl::ExportDecl(ExportDecl {
                            span: export_decl.span,
                            decl: Decl::Var(Box::new(VarDecl {
                                span: var.span,
                                ctxt: var.ctxt,
                                kind: var.kind,
                                declare: var.declare,
                                decls: vec![decl],
                            })),
                        })));
                    }
                }
                decl => out.push(ModuleItem::ModuleDecl(ModuleDecl::ExportDecl(ExportDecl {
                    span: export_decl.span,
                    decl,
                }))),
            },
            other => out.push(other),
        }
    }
    module.body = out;
}

/// Conservative top-level dead-code sweep. Each `module.body[i]` is
/// either a **side-effect** anchor (must stay), or a **declaration**
/// whose retention depends on whether anything live reads its names.
///
/// Algorithm:
/// 1. Classify each `body[i]` into `ItemClass::Decl { names, reads }`
///    or `ItemClass::SideEffect { reads }`. Hoistable, side-effect-free
///    shapes (`function X`, `class X`, `var/let/const X = <pure_init>`,
///    `export const X = <pure_init>`, etc.) go to `Decl`; everything
///    else (top-level expressions, `Object.defineProperty(...)` calls,
///    imports, side-effecting var inits) goes to `SideEffect`.
/// 2. Seed the live set with all `SideEffect` items, plus any `Decl`
///    that introduces a name in `live_exports`.
/// 3. Fixpoint: while there's a `Decl` not yet live whose declared
///    names are referenced by a live item, mark it live.
/// 4. Filter `module.body` to keep only live items in source order.
///
/// Reads are over-approximated to all free identifier names appearing
/// anywhere in the item — no scope analysis. This is safe (keeps more
/// code than strictly necessary) and avoids re-implementing lexical
/// scoping.
fn sweep_unreachable_top_level(
    module: &mut Module,
    live_exports: &BTreeSet<String>,
    stripped: &BTreeMap<String, StrippedExport>,
    chunk_path: &str,
) -> Result<()> {
    let analyses: Vec<ItemAnalysis> = module.body.iter().map(classify_item).collect();

    // Binding id -> index that declares it. If two items declare the
    // same binding (legal for `var`), prefer the last declaration; later
    // writes shadow earlier ones for reachability purposes.
    let mut declarer: BTreeMap<Id, usize> = BTreeMap::new();
    for (i, an) in analyses.iter().enumerate() {
        for id in &an.declared {
            declarer.insert(id.clone(), i);
        }
    }

    let mut mutation_items_by_target: BTreeMap<Id, Vec<usize>> = BTreeMap::new();
    for (i, an) in analyses.iter().enumerate() {
        for id in &an.local_effects {
            if declarer.contains_key(id) {
                mutation_items_by_target
                    .entry(id.clone())
                    .or_default()
                    .push(i);
            }
        }
    }

    let mut swapped_reachability = vec![BTreeSet::new(); analyses.len()];
    let mut queue: Vec<(usize, String)> = Vec::new();
    for (alias, stripped_export) in stripped {
        for local in &stripped_export.locals {
            let Some(&decl_idx) = declarer.get(local) else {
                bail!(
                    "strip_swapped_vendor_exports vendor entry {chunk_path}: swapped export {alias} maps to local `{}` but that binding has no top-level declaration",
                    id_name(local),
                );
            };
            if swapped_reachability[decl_idx].insert(stripped_export.package.clone()) {
                queue.push((decl_idx, stripped_export.package.clone()));
            }
        }
    }

    while let Some((i, package)) = queue.pop() {
        for dep_idx in dependency_items(&analyses[i], &declarer, &mutation_items_by_target) {
            if swapped_reachability[dep_idx].insert(package.clone()) {
                queue.push((dep_idx, package.clone()));
            }
        }
    }

    let mut live = vec![false; analyses.len()];
    for (i, an) in analyses.iter().enumerate() {
        let residual_export = an
            .export_aliases
            .iter()
            .any(|alias| live_exports.contains(alias));
        let hard_side_effect = (an.side_effect == SideEffectKind::Hard
            || (an.side_effect == SideEffectKind::LocalMutation
                && an.local_effects.iter().any(|id| !declarer.contains_key(id))))
            && swapped_reachability[i].is_empty();
        if residual_export || hard_side_effect {
            live[i] = true;
        }
    }

    let mut queue: Vec<usize> = (0..analyses.len()).filter(|&i| live[i]).collect();
    while let Some(i) = queue.pop() {
        for dep_idx in dependency_items(&analyses[i], &declarer, &mutation_items_by_target) {
            if !live[dep_idx] {
                live[dep_idx] = true;
                queue.push(dep_idx);
            }
        }
    }

    for (i, packages) in swapped_reachability.iter().enumerate() {
        if live[i] && packages.len() == 1 && !analyses[i].shareable_helper {
            let declared = analyses[i]
                .declared
                .iter()
                .map(id_name)
                .collect::<Vec<_>>()
                .join(",");
            let exports = analyses[i]
                .export_aliases
                .iter()
                .cloned()
                .collect::<Vec<_>>()
                .join(",");
            let packages = packages.iter().cloned().collect::<Vec<_>>().join(",");
            bail!(
                "strip_swapped_vendor_exports vendor entry {chunk_path}: split-brain vendor swap: top-level item {i} remains reachable from the residual chunk while also belonging to swapped package(s) [{packages}] (declared=[{declared}], exports=[{exports}])",
            );
        }
    }

    // Soundness gate: if any *kept* item reads a name declared only by
    // a *dropped* item, the classification missed a side-effect or the
    // fixpoint didn't converge. Bail with the offending pair.
    for (i, is_live) in live.iter().enumerate() {
        if !is_live {
            continue;
        }
        for id in analyses[i]
            .reads
            .iter()
            .chain(analyses[i].local_effects.iter())
        {
            if let Some(&decl_idx) = declarer.get(id)
                && !live[decl_idx]
            {
                bail!(
                    "strip_swapped_vendor_exports vendor entry {chunk_path}: live item {i} reads `{}` declared by dropped item {decl_idx}",
                    id_name(id),
                );
            }
        }
    }

    let mut original = std::mem::take(&mut module.body);
    for (i, is_live) in live.iter().enumerate().rev() {
        if !*is_live {
            original.remove(i);
        }
    }
    module.body = original;
    Ok(())
}

fn dependency_items(
    analysis: &ItemAnalysis,
    declarer: &BTreeMap<Id, usize>,
    mutation_items_by_target: &BTreeMap<Id, Vec<usize>>,
) -> BTreeSet<usize> {
    let mut out = BTreeSet::new();
    for id in analysis.reads.iter().chain(analysis.local_effects.iter()) {
        if let Some(&decl_idx) = declarer.get(id) {
            out.insert(decl_idx);
        }
    }
    for id in &analysis.declared {
        if let Some(mutation_items) = mutation_items_by_target.get(id) {
            out.extend(mutation_items.iter().copied());
        }
    }
    out
}

struct ItemAnalysis {
    declared: BTreeSet<Id>,
    reads: BTreeSet<Id>,
    local_effects: BTreeSet<Id>,
    export_aliases: BTreeSet<String>,
    side_effect: SideEffectKind,
    shareable_helper: bool,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum SideEffectKind {
    None,
    LocalMutation,
    Hard,
}

fn classify_item(item: &ModuleItem) -> ItemAnalysis {
    match item {
        ModuleItem::Stmt(Stmt::Decl(decl)) => classify_decl(decl),
        ModuleItem::Stmt(Stmt::Expr(expr_stmt)) => classify_expr_stmt(&expr_stmt.expr),
        ModuleItem::ModuleDecl(ModuleDecl::ExportDecl(export_decl)) => {
            let mut analysis = classify_decl(&export_decl.decl);
            analysis
                .export_aliases
                .extend(export_decl_declared_names(&export_decl.decl));
            analysis
        }
        ModuleItem::ModuleDecl(ModuleDecl::ExportNamed(named)) if named.src.is_none() => {
            let mut reads = BTreeSet::new();
            let mut export_aliases = BTreeSet::new();
            for spec in &named.specifiers {
                if let ExportSpecifier::Named(named_spec) = spec {
                    export_aliases.insert(
                        named_spec
                            .exported
                            .as_ref()
                            .map(module_export_name)
                            .unwrap_or_else(|| module_export_name(&named_spec.orig)),
                    );
                    if let ModuleExportName::Ident(ident) = &named_spec.orig {
                        reads.insert(ident.to_id());
                    }
                }
            }
            ItemAnalysis {
                declared: BTreeSet::new(),
                reads,
                local_effects: BTreeSet::new(),
                export_aliases,
                side_effect: SideEffectKind::None,
                shareable_helper: false,
            }
        }
        ModuleItem::ModuleDecl(ModuleDecl::ExportDefaultDecl(export_default)) => {
            let mut reads = BTreeSet::new();
            collect_refs(export_default, &mut reads);
            ItemAnalysis {
                declared: BTreeSet::new(),
                reads,
                local_effects: BTreeSet::new(),
                export_aliases: BTreeSet::from(["default".to_string()]),
                side_effect: SideEffectKind::None,
                shareable_helper: false,
            }
        }
        ModuleItem::ModuleDecl(ModuleDecl::ExportDefaultExpr(export_default)) => {
            let mut reads = BTreeSet::new();
            collect_refs(&*export_default.expr, &mut reads);
            // `export default <expr>` evaluates expr at module init;
            // if expr is impure (e.g. `export default sideEffect()`)
            // we must keep it. For a pure expr (`export default X`),
            // the expression itself is inert — the export is the
            // anchor of the read chain.
            ItemAnalysis {
                declared: BTreeSet::new(),
                reads,
                local_effects: BTreeSet::new(),
                export_aliases: BTreeSet::from(["default".to_string()]),
                side_effect: if is_pure_expr(&export_default.expr) {
                    SideEffectKind::None
                } else {
                    SideEffectKind::Hard
                },
                shareable_helper: false,
            }
        }
        ModuleItem::ModuleDecl(ModuleDecl::Import(_)) => ItemAnalysis {
            declared: BTreeSet::new(),
            reads: BTreeSet::new(),
            local_effects: BTreeSet::new(),
            export_aliases: BTreeSet::new(),
            side_effect: SideEffectKind::Hard,
            shareable_helper: false,
        },
        ModuleItem::ModuleDecl(ModuleDecl::ExportAll(_)) => ItemAnalysis {
            declared: BTreeSet::new(),
            reads: BTreeSet::new(),
            local_effects: BTreeSet::new(),
            export_aliases: BTreeSet::new(),
            side_effect: SideEffectKind::Hard,
            shareable_helper: false,
        },
        ModuleItem::ModuleDecl(ModuleDecl::ExportNamed(named)) => {
            let mut reads = BTreeSet::new();
            collect_refs(named, &mut reads);
            ItemAnalysis {
                declared: BTreeSet::new(),
                reads,
                local_effects: BTreeSet::new(),
                export_aliases: export_aliases_from_named(named),
                side_effect: SideEffectKind::Hard,
                shareable_helper: false,
            }
        }
        ModuleItem::ModuleDecl(_) => {
            let mut reads = BTreeSet::new();
            collect_refs(item, &mut reads);
            ItemAnalysis {
                declared: BTreeSet::new(),
                reads,
                local_effects: BTreeSet::new(),
                export_aliases: BTreeSet::new(),
                side_effect: SideEffectKind::Hard,
                shareable_helper: false,
            }
        }
        ModuleItem::Stmt(_) => {
            let mut reads = BTreeSet::new();
            collect_refs(item, &mut reads);
            ItemAnalysis {
                declared: BTreeSet::new(),
                reads,
                local_effects: BTreeSet::new(),
                export_aliases: BTreeSet::new(),
                side_effect: SideEffectKind::Hard,
                shareable_helper: false,
            }
        }
    }
}

fn classify_decl(decl: &Decl) -> ItemAnalysis {
    let mut reads = BTreeSet::new();
    match decl {
        Decl::Fn(fn_decl) => {
            let declared = BTreeSet::from([fn_decl.ident.to_id()]);
            collect_refs(&fn_decl.function, &mut reads);
            reads.remove(&fn_decl.ident.to_id());
            ItemAnalysis {
                declared,
                reads,
                local_effects: BTreeSet::new(),
                export_aliases: BTreeSet::new(),
                side_effect: SideEffectKind::None,
                shareable_helper: true,
            }
        }
        Decl::Class(class_decl) => {
            let declared = BTreeSet::from([class_decl.ident.to_id()]);
            collect_refs(&class_decl.class, &mut reads);
            reads.remove(&class_decl.ident.to_id());
            ItemAnalysis {
                declared,
                reads,
                local_effects: BTreeSet::new(),
                export_aliases: BTreeSet::new(),
                side_effect: SideEffectKind::None,
                shareable_helper: false,
            }
        }
        Decl::Var(var) => {
            let mut declared = BTreeSet::new();
            let mut has_side_effect_init = false;
            for d in &var.decls {
                declared.extend(binding_names(&d.name));
                if let Some(init) = &d.init {
                    if !is_pure_expr(init) {
                        has_side_effect_init = true;
                    }
                    collect_refs(&**init, &mut reads);
                }
            }
            for id in &declared {
                reads.remove(id);
            }
            ItemAnalysis {
                declared,
                reads,
                local_effects: BTreeSet::new(),
                export_aliases: BTreeSet::new(),
                side_effect: if has_side_effect_init {
                    SideEffectKind::Hard
                } else {
                    SideEffectKind::None
                },
                shareable_helper: false,
            }
        }
        Decl::Using(_)
        | Decl::TsInterface(_)
        | Decl::TsTypeAlias(_)
        | Decl::TsEnum(_)
        | Decl::TsModule(_) => {
            collect_refs(decl, &mut reads);
            ItemAnalysis {
                declared: BTreeSet::new(),
                reads,
                local_effects: BTreeSet::new(),
                export_aliases: BTreeSet::new(),
                side_effect: SideEffectKind::Hard,
                shareable_helper: false,
            }
        }
    }
}

fn classify_expr_stmt(expr: &Expr) -> ItemAnalysis {
    let mut reads = BTreeSet::new();
    collect_refs(expr, &mut reads);
    let local_effects = local_mutation_targets(expr);
    ItemAnalysis {
        declared: BTreeSet::new(),
        reads,
        local_effects: local_effects.clone(),
        export_aliases: BTreeSet::new(),
        side_effect: if local_effects.is_empty() {
            SideEffectKind::Hard
        } else {
            SideEffectKind::LocalMutation
        },
        shareable_helper: false,
    }
}

fn local_mutation_targets(expr: &Expr) -> BTreeSet<Id> {
    match expr {
        Expr::Assign(assign) => {
            let mut recorder = LocalEffectRecorder::default();
            record_assign_target(&assign.left, &mut recorder);
            recorder.member_writes
        }
        Expr::Update(update) => {
            let mut recorder = LocalEffectRecorder::default();
            record_update_target(&update.arg, &mut recorder);
            recorder.member_writes
        }
        Expr::Call(call) => local_mutation_call_target(call).into_iter().collect(),
        Expr::Seq(seq) => seq
            .exprs
            .iter()
            .flat_map(|expr| local_mutation_targets(expr))
            .collect(),
        Expr::Paren(paren) => local_mutation_targets(&paren.expr),
        _ => BTreeSet::new(),
    }
}

#[derive(Default)]
struct LocalEffectRecorder {
    member_writes: BTreeSet<Id>,
}

impl TargetAccessRecorder for LocalEffectRecorder {
    fn record_binding_write(&mut self, _id: &Id) {}

    fn record_member_write(&mut self, id: &Id) {
        self.member_writes.insert(id.clone());
    }
}

fn local_mutation_call_target(call: &CallExpr) -> Option<Id> {
    let Callee::Expr(callee) = &call.callee else {
        return None;
    };
    let Expr::Member(member) = &**callee else {
        return None;
    };
    let Expr::Ident(object) = &*member.obj else {
        return None;
    };
    if object.sym.as_ref() != "Object" {
        return None;
    }
    let method = static_member_name(&member.prop)?;
    if !matches!(
        method.as_str(),
        "defineProperty" | "defineProperties" | "assign"
    ) {
        return None;
    }
    let first_arg = call.args.first()?;
    local_member_owner(&first_arg.expr)
}

fn local_member_owner(expr: &Expr) -> Option<Id> {
    match expr {
        Expr::Ident(ident) => Some(ident.to_id()),
        Expr::Member(member) => local_member_owner(&member.obj),
        Expr::Paren(paren) => local_member_owner(&paren.expr),
        _ => None,
    }
}

fn static_member_name(prop: &MemberProp) -> Option<String> {
    match prop {
        MemberProp::Ident(ident) => Some(ident.sym.to_string()),
        MemberProp::PrivateName(name) => Some(name.name.to_string()),
        MemberProp::Computed(computed) => match &*computed.expr {
            Expr::Lit(Lit::Str(value)) => Some(value.value.to_string_lossy().into_owned()),
            _ => None,
        },
    }
}

fn export_aliases_from_named(named: &NamedExport) -> BTreeSet<String> {
    named
        .specifiers
        .iter()
        .filter_map(|spec| match spec {
            ExportSpecifier::Named(named_spec) => Some(
                named_spec
                    .exported
                    .as_ref()
                    .map(module_export_name)
                    .unwrap_or_else(|| module_export_name(&named_spec.orig)),
            ),
            _ => None,
        })
        .collect()
}

fn id_name(id: &Id) -> String {
    id.0.to_string()
}

fn collect_pat_names(pat: &Pat, out: &mut Vec<String>) {
    match pat {
        Pat::Ident(b) => out.push(b.id.sym.to_string()),
        Pat::Array(arr) => {
            for elem in arr.elems.iter().flatten() {
                collect_pat_names(elem, out);
            }
        }
        Pat::Object(obj) => {
            for prop in &obj.props {
                match prop {
                    ObjectPatProp::KeyValue(kv) => collect_pat_names(&kv.value, out),
                    ObjectPatProp::Assign(a) => out.push(a.key.sym.to_string()),
                    ObjectPatProp::Rest(r) => collect_pat_names(&r.arg, out),
                }
            }
        }
        Pat::Rest(r) => collect_pat_names(&r.arg, out),
        Pat::Assign(a) => collect_pat_names(&a.left, out),
        _ => {}
    }
}

/// Pure-init shapes safe to DCE. The point isn't to be exhaustive — it
/// is to admit the common cases that account for the vast majority of
/// vendor-blob declarations (literals, function/arrow/class expressions,
/// object/array literals composed of pure parts, simple member access
/// off a pure receiver). Anything else (calls, `new`, template tags,
/// spreads, computed members on side-effecting bases) is treated as a
/// side-effect anchor and kept.
fn is_pure_expr(expr: &Expr) -> bool {
    match expr {
        Expr::Lit(_)
        | Expr::Ident(_)
        | Expr::This(_)
        | Expr::Fn(_)
        | Expr::Arrow(_)
        | Expr::Class(_)
        | Expr::Tpl(_)
        | Expr::PrivateName(_) => true,
        Expr::Paren(p) => is_pure_expr(&p.expr),
        Expr::Unary(u) => matches!(u.op, UnaryOp::Void | UnaryOp::TypeOf) || is_pure_expr(&u.arg),
        Expr::Array(arr) => arr
            .elems
            .iter()
            .flatten()
            .all(|elem| elem.spread.is_none() && is_pure_expr(&elem.expr)),
        Expr::Object(obj) => obj.props.iter().all(|prop| match prop {
            PropOrSpread::Spread(_) => false,
            PropOrSpread::Prop(p) => is_pure_prop(p),
        }),
        Expr::Member(m) => is_pure_expr(&m.obj),
        Expr::OptChain(opt) => match &*opt.base {
            OptChainBase::Member(m) => is_pure_expr(&m.obj),
            OptChainBase::Call(_) => false,
        },
        Expr::Cond(c) => is_pure_expr(&c.test) && is_pure_expr(&c.cons) && is_pure_expr(&c.alt),
        Expr::Bin(b) => is_pure_expr(&b.left) && is_pure_expr(&b.right),
        Expr::Seq(s) => s.exprs.iter().all(|e| is_pure_expr(e)),
        _ => false,
    }
}

fn is_pure_prop(prop: &Prop) -> bool {
    match prop {
        Prop::Shorthand(_) => true,
        Prop::KeyValue(kv) => is_pure_expr(&kv.value),
        Prop::Method(_) | Prop::Getter(_) | Prop::Setter(_) => true,
        Prop::Assign(a) => is_pure_expr(&a.value),
    }
}

/// Walk any AST node and collect referenced binding identities. This
/// intentionally ignores binding positions and static property keys:
/// reachability follows actual local cells, not printed names.
fn collect_refs<T>(node: &T, out: &mut BTreeSet<Id>)
where
    for<'a> T: VisitWith<RefCollector<'a>>,
{
    let mut visitor = RefCollector { out };
    node.visit_with(&mut visitor);
}

struct RefCollector<'a> {
    out: &'a mut BTreeSet<Id>,
}

impl Visit for RefCollector<'_> {
    fn visit_ident(&mut self, ident: &Ident) {
        self.out.insert(ident.to_id());
    }

    fn visit_binding_ident(&mut self, _ident: &BindingIdent) {}

    fn visit_import_decl(&mut self, _import: &ImportDecl) {}

    fn visit_var_declarator(&mut self, decl: &VarDeclarator) {
        if let Some(init) = &decl.init {
            init.visit_with(self);
        }
    }

    fn visit_member_prop(&mut self, prop: &MemberProp) {
        // `obj.x` — `x` is not a free variable reference. Only recurse
        // into computed `obj[x]`.
        if let MemberProp::Computed(c) = prop {
            c.expr.visit_with(self);
        }
    }

    fn visit_prop_name(&mut self, name: &PropName) {
        // Object literal keys: `{ x: 1 }` — `x` is a property key, not
        // a reference. Computed `{ [k]: 1 }` still reads `k`.
        if let PropName::Computed(c) = name {
            c.expr.visit_with(self);
        }
    }

    fn visit_prop(&mut self, prop: &Prop) {
        // `{ x }` shorthand reads `x` as an identifier; default Visit
        // already handles that via `Prop::Shorthand(Ident)`.
        prop.visit_children_with(self);
    }
}

fn module_export_name(name: &ModuleExportName) -> String {
    name.atom().to_string()
}

/// Subset of [`collect_exported_names`] in `vendor.rs`: returns the
/// post-mutation export surface of `module`. Local re-exports
/// (`export { x as y }`), `export const x = …`, `export function`,
/// `export class`, `export default …` all count.
fn collect_exported_names(module: &Module) -> BTreeSet<String> {
    let mut out = BTreeSet::new();
    for item in &module.body {
        match item {
            ModuleItem::ModuleDecl(ModuleDecl::ExportDefaultDecl(_))
            | ModuleItem::ModuleDecl(ModuleDecl::ExportDefaultExpr(_)) => {
                out.insert("default".to_string());
            }
            ModuleItem::ModuleDecl(ModuleDecl::ExportDecl(export_decl)) => {
                match &export_decl.decl {
                    Decl::Fn(f) => {
                        out.insert(f.ident.sym.to_string());
                    }
                    Decl::Class(c) => {
                        out.insert(c.ident.sym.to_string());
                    }
                    Decl::Var(v) => {
                        for d in &v.decls {
                            let mut names = Vec::new();
                            collect_pat_names(&d.name, &mut names);
                            out.extend(names);
                        }
                    }
                    _ => {}
                }
            }
            ModuleItem::ModuleDecl(ModuleDecl::ExportNamed(named)) => {
                for spec in &named.specifiers {
                    if let ExportSpecifier::Named(named_spec) = spec {
                        out.insert(
                            named_spec
                                .exported
                                .as_ref()
                                .map(module_export_name)
                                .unwrap_or_else(|| module_export_name(&named_spec.orig)),
                        );
                    }
                }
            }
            _ => {}
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use spec::{PartialSwapKind, PartialSwapSymbol};
    use swc_common::sync::Lrc;
    use swc_common::{FileName, SourceMap};
    use swc_ecma_ast::EsVersion;
    use swc_ecma_codegen::text_writer::JsWriter;
    use swc_ecma_codegen::{Config, Emitter};
    use swc_ecma_parser::{Parser, StringInput, Syntax, lexer::Lexer};

    use super::*;

    fn parse(source: &str) -> Module {
        let cm: Lrc<SourceMap> = Default::default();
        let fm = cm.new_source_file(Lrc::new(FileName::Anon), source.to_string());
        let lexer = Lexer::new(
            Syntax::Es(Default::default()),
            EsVersion::latest(),
            StringInput::from(&*fm),
            None,
        );
        let mut parser = Parser::new_from(lexer);
        parser.parse_module().expect("parse")
    }

    fn emit(module: &Module) -> String {
        let cm: Lrc<SourceMap> = Default::default();
        let mut buf = Vec::new();
        {
            let writer = JsWriter::new(cm.clone(), "\n", &mut buf, None);
            let mut emitter = Emitter {
                cfg: Config::default(),
                cm,
                comments: None,
                wr: writer,
            };
            emitter.emit_module(module).expect("emit");
        }
        String::from_utf8(buf).expect("utf8")
    }

    fn mk_symbols(swapped: &[&str]) -> BTreeMap<String, PartialSwapSymbol> {
        let mut symbols = BTreeMap::new();
        for s in swapped {
            symbols.insert(
                (*s).to_string(),
                PartialSwapSymbol {
                    package: "pkg".to_string(),
                    kind: PartialSwapKind::Named,
                    upstream_export: Some((*s).to_string()),
                },
            );
        }
        symbols
    }

    fn mk_symbols_with_packages(swapped: &[(&str, &str)]) -> BTreeMap<String, PartialSwapSymbol> {
        let mut symbols = BTreeMap::new();
        for (name, package) in swapped {
            symbols.insert(
                (*name).to_string(),
                PartialSwapSymbol {
                    package: (*package).to_string(),
                    kind: PartialSwapKind::Named,
                    upstream_export: Some((*name).to_string()),
                },
            );
        }
        symbols
    }

    #[test]
    fn strips_named_export_specifier() {
        let mut module = parse("const a = 1;\nconst b = 2;\nexport { a as foo, b as bar };\n");
        let stats = strip_one_chunk(&mut module, &mk_symbols(&["foo"]), "chunk.js").unwrap();
        let emitted = emit(&module);
        assert!(!emitted.contains("foo"), "stripped name leaked:\n{emitted}");
        assert!(emitted.contains("bar"), "kept name missing:\n{emitted}");
        assert_eq!(stats.stripped_export_specifiers, 1);
    }

    #[test]
    fn drops_inline_export_decl_and_dce_kills_pure_body() {
        let mut module = parse("export const e6 = () => true;\nexport const k = 7;\n");
        strip_one_chunk(&mut module, &mk_symbols(&["e6"]), "chunk.js").unwrap();
        let emitted = emit(&module);
        assert!(
            !emitted.contains("e6"),
            "swapped const should be DCE'd:\n{emitted}",
        );
        assert!(
            emitted.contains("export const k"),
            "non-swapped const dropped:\n{emitted}",
        );
    }

    #[test]
    fn bails_when_swapped_implementation_is_residually_reachable() {
        let mut module = parse(
            "class ZodObject {}\nconst object = ()=>new ZodObject();\nexport { object as o, ZodObject as Z };\n",
        );
        let err = strip_one_chunk(&mut module, &mk_symbols(&["o"]), "chunk.js")
            .expect_err("split-brain residual reachability should fail");
        assert!(
            err.to_string().contains("split-brain vendor swap"),
            "wrong error: {err}",
        );
    }

    #[test]
    fn allows_shared_pure_function_helper() {
        let mut module = parse(
            "function helper(x) { return x; }\nconst oldImpl = () => helper(\"old\");\nconst keep = () => helper(\"keep\");\nexport { oldImpl as swapped, keep };\n",
        );
        strip_one_chunk(&mut module, &mk_symbols(&["swapped"]), "chunk.js").unwrap();
        let emitted = emit(&module);
        assert!(
            emitted.contains("function helper"),
            "residual export should keep shared helper:\n{emitted}",
        );
        assert!(
            emitted.contains("keep"),
            "residual export should remain:\n{emitted}",
        );
        assert!(
            !emitted.contains("oldImpl"),
            "swapped old implementation should be removed:\n{emitted}",
        );
    }

    #[test]
    fn allows_multi_package_shared_dependency_cell() {
        let mut module = parse(
            "const shared = {};\nconst oldA = () => shared;\nconst oldB = () => shared;\nconst keep = () => shared;\nexport { oldA as swappedA, oldB as swappedB, keep };\n",
        );
        strip_one_chunk(
            &mut module,
            &mk_symbols_with_packages(&[("swappedA", "pkg-a"), ("swappedB", "pkg-b")]),
            "chunk.js",
        )
        .unwrap();
        let emitted = emit(&module);
        assert!(
            emitted.contains("shared"),
            "residual export should keep shared dependency cell:\n{emitted}",
        );
        assert!(
            !emitted.contains("oldA") && !emitted.contains("oldB"),
            "swapped package roots should be removed:\n{emitted}",
        );
    }

    #[test]
    fn retains_side_effect_init_among_swapped() {
        let mut module = parse("console.log(\"keep\");\nexport const e6 = ()=>true;\n");
        strip_one_chunk(&mut module, &mk_symbols(&["e6"]), "chunk.js").unwrap();
        let emitted = emit(&module);
        assert!(
            emitted.contains("console.log"),
            "side-effect should be retained:\n{emitted}",
        );
    }

    #[test]
    fn drops_local_member_writes_in_swapped_island() {
        let mut module = parse(
            "class Widget {}\nWidget.displayName = \"Widget\";\nconst make = () => Widget;\nexport { make as swapped };\n",
        );
        strip_one_chunk(&mut module, &mk_symbols(&["swapped"]), "chunk.js").unwrap();
        let emitted = emit(&module);
        assert!(
            !emitted.contains("Widget"),
            "swapped implementation island should be removed:\n{emitted}",
        );
        assert!(
            !emitted.contains("displayName"),
            "local class metadata write should be removed with the class:\n{emitted}",
        );
    }

    #[test]
    fn bails_when_swapped_name_not_locally_exported() {
        let mut module = parse("export { stuff } from \"./peer.js\";\n");
        let err = strip_one_chunk(&mut module, &mk_symbols(&["stuff"]), "chunk.js")
            .expect_err("should fail");
        assert!(
            err.to_string()
                .contains("not found in any chunk-local export"),
            "wrong error: {err}",
        );
    }

    #[test]
    fn call_init_classifies_as_side_effect() {
        let module = parse("const a = sideEffect();\n");
        let an = classify_item(&module.body[0]);
        assert!(
            an.side_effect == SideEffectKind::Hard,
            "call init should be a side-effect anchor"
        );
        assert_eq!(
            an.declared.iter().map(id_name).collect::<Vec<_>>(),
            vec!["a".to_string()]
        );
        assert!(an.reads.iter().any(|id| id_name(id) == "sideEffect"));
    }

    #[test]
    fn pure_object_literal_init_is_not_side_effect() {
        let module = parse("const a = { x: 1 };\n");
        let an = classify_item(&module.body[0]);
        assert!(
            an.side_effect == SideEffectKind::None,
            "object literal init should be a pure decl",
        );
    }
}
