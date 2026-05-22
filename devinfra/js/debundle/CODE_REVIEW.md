# Debundle Code Review

Full-package review of `devinfra/js/debundle/` (~47K lines). Findings prioritized by impact.

---

## P0 — God Modules

### `vendor.rs` (3297 lines, 6 concerns)

Mixes manifest types (~500 lines), AST synthesis helpers, import construction, and four distinct vendor operations (rename, full swap, partial swap, bundled partial swap).

- Manifest types (`VendorAnnotationsManifest`, `RenameVendorExportsManifest`, `VendorResolutionManifest`, `PartialSwapResolutionManifest`, `BundledPartialSwapResolutionManifest`) should live in `vendor/manifests.rs`.
- AST helpers (`export_default_ident`, `export_const_member`, `make_namespace_import`, `make_default_import`, `make_named_import`) duplicate patterns from `js_ast.rs` and the lowering subsystem. Extract to a shared `ast_helpers.rs`.
- `apply_partial_vendor_swaps` and `apply_bundled_partial_vendor_swaps` are near-identical dispatchers (build job vec, rayon `into_par_iter`, collect results, aggregate counts, write manifest). Unify with a generic helper or trait-based dispatch.
- `build_named_from_module_default_spec` and `build_named_from_default_spec` differ in exactly one key (`wrapper_shape`). Single function parameterized by the shape.

### `purity.rs` (2671 lines, 5 concerns)

Mixes graph construction (`ChunkCodeGraph`), whitelist constant tables (~400 lines of static data), expression classification, PlainData write scanning, and TS enum IIFE recognition.

- Whitelist tables (`PURE_STATIC_PROPS` through `PLAIN_DATA_HOSTILE_BUILTINS`, lines ~1600–1750) should be in `purity/whitelists.rs` or a data file.
- `classify_fresh_array_spread_source_purity` and `classify_fresh_array_spread_source_for_iterable` are near-identical recursive classifiers differing only in the result interpretation. Unify with a parameterized return.
- ~80-line doc comment on `PURE_OBJECT_CALLS_ON_PLAIN_DATA` (lines 1657–1741) and ~55-line PlainData soundness comment (lines 37–91) are design-doc material. Keep 3–5 line summaries in code.
- `ChunkCodeGraph` mixes SCC computation with classification state. The SCC computation could be a standalone function.

### `analysis_tests.rs` (4095 lines, 8+ subsystems)

Tests 8+ distinct subsystems in one file: fact analysis, decorate helpers, cycle detection, atomic unit conflicts, purity classification, plain-data tracking, redundant hints, statement splitting, factor assembly. A test for purity must scroll past 600 lines of fact-analysis tests to find helpers.

Split into topic-aligned modules: `tests/facts.rs`, `tests/purity.rs`, `tests/plain_data.rs`, `tests/cycles.rs`, `tests/atomic_units.rs`, `tests/statement_splitting.rs`.

### `facts.rs` (2228 lines, 3 concerns)

~1000 lines of vendor-prune-specific local effect analysis (lines 533–1583) embedded in general statement-fact collection. The `vendor_prune_*` functions are a self-contained concern. Extract to `facts/vendor_prune.rs` or behind a feature flag. The vendor-prune analysis should accept `StatementFacts` as input rather than being embedded in the collection pass.

---

## P1 — Major Duplication

### Test fixture builders in peel/ (2 copies) — **Partially done** (`f576e543c`)

Extracted `binding()`, `member()`, `module_ref()` to `peel/test_utils.rs`. The `owner()`, `atomic_unit()`, `atomic_edge()`, `graph_fixture()` helpers have different signatures/semantics between the two test modules and remain local.

### Line-range accumulation (3 copies)

`start_line.min(...)` / `end_line.max(...)` / `size_lines_estimate += end - start + 1` duplicated in `reports.rs:169–179`, `factorize.rs:636–639`, `plan.rs:1361–365`. Extract as a method on `SourceLocation` or a free function.

### Vendor swap test workspace setup (4 copies)

`vendor_swap_test.rs` has four near-identical fixture constructors (`run_named_from_module_default_fixture`, `run_named_from_default_fixture`, `run_partial_swap_fixture`, `run_partial_swap_kind_fixture`) that all create TempDir, workspace/extracted/snapshot/out/wrapper directories, write snapshot files, write package.json, write spec YAML, run debundler. Extract a `VendorSwapWorkspace` builder.

---

## P2 — Structural Issues

### `lowering/util.rs` is a grab-bag module

Violates STYLE.md "No grab-bag modules" rule. Contains ordinal arithmetic, var-decl splitting, scope name collection, import disambiguation, import-decl construction, I/O helpers, and error rendering. Split into `lowering/scope_names.rs`, `lowering/import_emit.rs`, `lowering/ordinal.rs`, `lowering/io.rs`.

### `lowering/materialize.rs` (1026 lines) mixes 4 concerns

Orchestration/plan resolution (lines 39–342), factorization wiring (344–579), rebind folding (914–1026), and artifact assembly (787–912) are unrelated. Extract `fold_rebind_atomic_units` into its own file and factor out the `analysis_hints` collection (lines 359–405 — two near-identical loops for `explicit_requests` and `chunk_renames`).

### `lower/lower.rs` — monolithic function (partially extracted)

`lower_chunk` had 8 sequential phases inline. Four have been extracted into named functions (`compute_selected_ordinals`, `plan_selected_exports`, `split_entry_body`, `build_module_output`). Remaining inline phases (naturalization, disambiguation, import planning, the per-module loop) could be further extracted, though each requires substantial captured state from `LowerChunkInputs` (15–20 fields).

### `lowering/mod.rs` — 45-line import block

Consequence of wildcard `use super::*` in every sub-module. A more targeted import strategy would reduce this. `LOWERING_FILE_PRAGMA` and `LOWERING_GENERATOR_HEADER` are used only in `lower.rs` — move them there.

### `peel/plan.rs:run_explain_report` — 181 lines

63 lines (630–692) are near-identical `apply_limit_with_metadata` calls. A helper that takes a list of `(section_name, &mut Vec<T>)` pairs and applies limits in bulk would collapse to ~10 lines. `query_report` and `resolve_owner_ids` each do a 5-way match on `SelectionKind` — a `SelectionKind::query_kind()` method would eliminate the duplication.

### `emit_harness.rs` — repeated JSON-write pattern

`serde_json::to_writer_pretty(&fs::File::create(path)?, &data)?` appears 7 times (lines 115–162). Extract `fn write_json(path: &Path, data: &impl Serialize) -> Result<()>`. Same pattern in `write_tree.rs` (3 occurrences).

### `emit_harness.rs:536–593` — 57-line embedded JS string

`harness_monitor_script` is an inline JS blob that can't be linted or tested independently. Use `include_str!("harness_monitor.js")` and keep the JS in a separate file.

### `output_layout.rs` — 12 identical accessor methods

Each returns `self.root.join(CONSTANT)`. Replace with a data-driven approach: `report_path(name: &str) -> PathBuf` plus constants, or a const array + index.

---

## P3 — Encapsulation & Type Design

### `ModuleQuotient` Deref/DerefMut leak (`graph.rs`)

Newtype over `DiGraphMap` with `Deref`/`DerefMut` to inner type. Exposes full petgraph mutation API, defeating the newtype. `DerefMut` lets anyone add arbitrary edges. Expose only intended operations via explicit methods.

### `OwnerGraph` exposes internal CSR structures (`graph.rs`)

`flat_edges`, `nodes`, `edges`, `out_edges`, `in_edges` all `pub(crate)`. Any module can corrupt graph invariants. Reduce to explicit query methods.

### `RealizabilityIndex` — raw `push`/`undo` should be private (`realizability.rs`)

The `scoped` guard API is good, but `push` and `undo` are also `pub(crate)`, allowing callers to bypass the guard and corrupt the journal. Make them private unless a specific caller needs manual control (documented).

### `BTreeMap`/`BTreeSet` as default collection in hot-path graph structures

`rollback_graph.rs`, `artifact.rs`, `realizability.rs` all use BTree collections exclusively. For structures with many lookups, `HashMap`/`HashSet` would be faster. If deterministic iteration is needed, document it at the struct level. `RollbackDiGraph` in particular does many lookups per operation where hash-based would be measurably faster.

### Hand-rolled Tarjan SCC (`rollback_graph.rs:119–191`)

The file already depends on petgraph (used in tests). Implement petgraph's `GraphProp`/`IntoNeighbors` traits for `RollbackDiGraph` and use `petgraph::algo::tarjan_scc` instead of ~70 lines of hand-rolled Tarjan.

### `RollbackDiGraph` allocates Vec per adjacency query

`successors` and `predecessors` return `Vec<N>`, allocating on every call. Hot paths (SCC computation) call these in a loop. Return an iterator borrowing from the BTreeSet.

### `StatementFacts` (facts.rs) — 14 BTreeSet<Id> fields

reads, eager_reads, writes, eager_writes, rebinds, eager_rebinds, lazy_reads, lazy_writes, lazy_rebinds, calls, at_init_calls, dynamic_imports, side_effects, local_effects. Many are derivable (eager + lazy = total). Every construction site must keep 14 sets mutually consistent. Consider computing derived sets on demand or using a builder that enforces invariants.

### `DepKind` 6-way split vs primary constraining/non-constraining axis

Callers in realizability.rs, validation.rs, facts.rs frequently partition into constraining vs non-constraining via `constrains_init_order()`. Make this a first-class type distinction.

### Three-layer edge representation

Domain graph (`graph.rs`) → rollback graph (`rollback_graph.rs`) → realizability index (`realizability.rs`) all represent "edges between things" at different granularities with different semantics. The bridging code is fragile. Consider a unified edge model or explicit conversion layers.

### `pub(super)` everywhere in lowering/

Nearly every struct field and function is `pub(super)`. This is "module-private exposed to the entire parent module" — everything accessible everywhere within `lowering/`. Fields should be `pub(super)` only on structs that are actually constructed/destructured across file boundaries.

### Vendor manifest struct proliferation

~15 manifest/counts/detail structs with similar shapes in `vendor.rs`. `PartialSwapResolutionManifest` and `BundledPartialSwapResolutionManifest` are nearly structurally identical. Consider a parameterized base type.

### `SourceImportResolution = Option<(String, String, String)>` (`plan_references.rs:41`)

Unclear what the three strings mean. A named struct or comment would help.

---

## P5 — Test-Specific Issues

### Cycle-forcing fixture pattern (~20 repetitions across 4 files)

Every test in `purity_test.rs`, `object_plain_data_calls_test.rs`, `pure_members_test.rs`, and `at_init_s_chain_dataflow_test.rs` follows: create source with SE anchor + target binding + reader → run fixture → assert module source and entry output. A shared `assert_pure_cycle_break(source, logical_modules, module_path, contains, not_contains, expected_stdout)` in support.rs would eliminate ~300 lines.

### `NodeOutput` struct is dead (`support.rs:484`)

Identical to `CommandResult` (line 660). Only used in `assert_node_output` which internally converts to `CommandResult`. Remove and use `CommandResult` directly.

### `accepted_spec_runs_under_node_test.rs` — `★ RED test` markers

Uses inline comment markers instead of `#[ignore]` with reason strings (like `purity_test.rs` does). Inconsistent.

### `realizability_test.rs` — inconsistent JSON construction

Some tests use `logical_module()` helper, others use raw JSON for identical structures (`cyclic_spec_is_rejected_with_clear_error` has no non-standard fields that would justify raw JSON).

### `realizability_test.rs:assert_fraction_metric` — float equality via `assert_eq!`

Fragile for computed fractions. Use `assert!((a - b).abs() < 1e-10)` or approx comparison.

### `vendor_swap_test.rs` — 4 bundled_partial_swap tests duplicate inline fixture setup

Lines 1030–1617 are four tests each manually creating the entire fixture inline (155 lines per test). Extract `run_bundled_partial_swap_fixture`.

### `chunk_renames_test.rs` — verbose `FixtureOpts` construction repeated 4x

8-field struct literal repeated. Add `FixtureOpts::new(...).with_chunk_renames(renames)` builder.

### `pure_members_test.rs` — 3 identical fixture shapes with different `pure_members` values

Table-driven test candidate.

### BUILD.bazel — all e2e tests depend on `:analysis` unconditionally

Most tests don't need it. Split into two list comprehensions: one with standard deps, one for tests needing `:analysis`.

---

## Live Proxy

The old JS live proxy findings were resolved by replacing the Node
implementation with Python modules split by concern: config/HTML/asset mapping,
vendor package resolution, mitmproxy response serving, and browser smoke
diagnostics.

---

## SWC Ecosystem — Reuse Opportunities

Currently pinned: `swc_common` 21.0.1, `swc_ecma_ast` 23.0.0, `swc_ecma_codegen` 26.0.1, `swc_ecma_parser` 39.0.2, `swc_ecma_utils` 29.1.1 (only `find_pat_ids` used), `swc_ecma_transforms_base` (resolver only), `swc_ecma_visit` 23.0.0, `swc_atoms` 9.0.0. SWC source cloned at `~/code/swc` for reference.

### `swc_ecma_utils` underutilized

The crate (at pinned 29.1.1) provides more than just `find_pat_ids`. Additional functions worth investigating:

| Utility                                   | Location in `swc_ecma_utils` | Debundle use case                                                                                                                                                                                                                                      |
| ----------------------------------------- | ---------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `IdentRenamer`                            | line 2377                    | Bulk `Id`→`Id` rename handling export specifiers, shorthand props, object patterns. More correct than custom `IdentifierRenamer` for hygiene-aware renames, but the debundler's string-keyed renames are post-hygiene so the abstraction doesn't match |
| `RefRewriter<T: QueryRef>`                | line 2494                    | Advanced reference rewriting — can replace an identifier with an arbitrary expression (e.g., `foo` → `bar.baz`). Could simplify cross-module import rewriting                                                                                          |
| `contains_ident_ref(ident, node)`         | line 126                     | Hygiene-aware "is this identifier referenced?" check. Could replace some manual visitor walks in fact collection                                                                                                                                       |
| `may_have_side_effects(ExprCtx)`          | trait method line 724        | Side-effect analysis on expressions. Could supplement purity classification for simple cases                                                                                                                                                           |
| `is_pure_callee(ExprCtx)`                 | trait method                 | Checks if calling an expression is safe. Could supplement purity classification                                                                                                                                                                        |
| `is_simple_pure_expr(expr, pure_getters)` | line 1260                    | Simple purity check. Could replace some inline purity checks in vendor stripping                                                                                                                                                                       |
| `replace_ident(node, from, to)`           | line 2070                    | Single-identifier replacement handling shorthand props. Lighter than full `IdentRenamer`                                                                                                                                                               |
| `collect_decls_with_ctxt`                 | line 2256                    | Like `collect_decls` but filters to a specific `SyntaxContext`. Could be useful for scope-aware binding collection                                                                                                                                     |

### `swc_ecma_transforms_optimization::simplify::dce` — Potential DCE replacement

The DCE pass that `swc_ecma_minifier` uses actually lives in `swc_ecma_transforms_optimization` (a separate, lighter crate). It is **public and standalone-usable**:

```rust
use swc_ecma_transforms_optimization::simplify::dce;

let mut shaker = dce(
    dce::Config {
        module_mark: None,
        top_level: true,
        top_retain: vec!["keep_me".into()],
        preserve_imports_with_side_effects: true,
    },
    unresolved_mark,
);
module.visit_mut_with(&mut shaker);
```

**Algorithm**: Two-phase fixed-point — `Analyzer` builds a `petgraph` dependency graph of variable references, tracks entry points, subtracts SCC-internal usage via Tarjan, then `TreeShaker` removes zero-usage bindings. Handles eval/arguments conservatively, self-references in fn/class bodies, IIFE unfolding.

**Adaptation path for partial-swap**: The DCE removes what's _unreferenced_. For "strip these specific exports":

1. Preparatory pass removes target export specifiers from the module
2. Run DCE with `top_level = true` and `top_retain` listing the residual symbols to keep
3. DCE transitively drops bindings that only the removed exports used

This would replace the custom `sweep_unreachable_top_level` in `strip_swapped_vendor_exports.rs` (~300 lines). The debundle's split-brain detection (checking that dropped items aren't read by kept items) would still need a custom validation pass after DCE runs. Worth investigating whether the DCE's own `can_drop_binding` logic covers this or whether a post-DCE validation scan is sufficient.

### `swc_ecma_usage_analyzer` — Dead end

No longer a standalone crate — absorbed into `swc_ecma_minifier` as `pub(crate)` module (`~/code/swc/crates/swc_ecma_minifier/src/usage_analyzer/mod.rs`). The "do not use directly" warning is **architectural**, not just semver: it depends on the minifier's internal `Marks` system (`const_ann`, `noinline`, `pure`, `fake_block`, `top_level_ctxt`, `unresolved_mark`) and a `Storage` trait requiring ~20 minifier-specific methods (`prevent_inline`, `mark_as_exported`, `mark_used_as_callee`, `store_param_count`, `add_infects_to`, etc.). Cannot be used outside `swc_ecma_minifier` without forking.

### Not worth replacing (domain-specific or unavailable)

| What                                        | SWC Equivalent                                                             | Why not                                                                                                                         |
| ------------------------------------------- | -------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| Scope analysis (eager/lazy, TDZ, at-init)   | None available externally — usage_analyzer is `pub(crate)` in the minifier | No SWC crate models the eager/lazy distinction or call-promotion semantics                                                      |
| Purity analysis (call-graph SCC, PlainData) | None                                                                       | Entirely domain-specific to bundle deconstruction                                                                               |
| Realizability checking                      | None                                                                       | Incremental quotient maintenance is unique to this codebase                                                                     |
| Identifier renaming (flat string-keyed)     | `swc_ecma_utils::IdentRenamer` is `Id`→`Id`, not `String`→`String`         | Debundler needs flat textual rename on already-resolved hygiene contexts with string keys from spec YAML                        |
| `strip_parens`                              | None at pinned 29.1.1                                                      | Comment in source confirms: "swc's pinned swc_ecma_utils doesn't ship a stable equivalent"                                      |
| `SourceLineIndex`                           | `SourceMap::lookup_char_pos` available at 21.0.1                           | Local version is a legitimate perf optimization (pre-computed binary search); could simplify to direct calls if perf acceptable |
| `member_root_id`/`member_root_sym`          | None                                                                       | No SWC utility for extracting root of member expression chains                                                                  |
| Import declaration construction             | `ExprFactory` trait (partial) — individual node construction only          | Debundle-specific relative-path logic has no SWC equivalent; keep but consolidate 3 copies                                      |

---

## Summary Statistics

| Category                         | Count                              |
| -------------------------------- | ---------------------------------- |
| God modules (P0)                 | 4 files totaling ~12K lines        |
| Major duplication sites (P1)     | 3 patterns remaining               |
| Structural issues (P2)           | 8 findings                         |
| Encapsulation / type design (P3) | 13 findings                        |
| Test-specific (P5)               | 9 findings                         |
| SWC reuse opportunities          | 8 underutilized utils, 1 DCE candidate |

## Top 5 Highest-Impact Actions

1. **Split `vendor.rs`** into `vendor/{manifests,ast_helpers,rename,full_swap,partial_swap,bundled_partial_swap}.rs`. Addresses the worst god module and much of the duplication in one change.

2. **Split `analysis_tests.rs`** into 6–8 topic-aligned test modules. Largest test file at 4095 lines.

3. **Extract vendor-prune from `facts.rs`** into `facts/vendor_prune.rs`. Separates a 1000-line self-contained concern from general fact collection.

4. **Extract `write_json` helper** from `emit_harness.rs` (7 copies) and `write_tree.rs` (3 copies). Use `include_str!` for the embedded JS monitor script.

5. **Split `lowering/util.rs`** grab-bag into focused modules (`scope_names.rs`, `import_emit.rs`, `ordinal.rs`, `io.rs`).
