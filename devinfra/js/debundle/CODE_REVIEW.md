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

### Pattern binding name extraction (3+ implementations)

`binding_names` / `pat_names` / `collect_pat_names` / `top_level_binding_names` / `binding_ids` — all walk SWC `Pat` variants to extract names.

| Location                               | Function                   | Returns                     |
| -------------------------------------- | -------------------------- | --------------------------- |
| `lowering/chunk_ast.rs:220`            | `binding_names`            | `Vec<String>`               |
| `lowering/chunk_ast.rs:244`            | `binding_ids`              | `Vec<Id>`                   |
| `strip_swapped_vendor_exports.rs:1079` | `collect_pat_names`        | `Vec<String>` via out-param |
| `vendor.rs` (~992)                     | `binding_names`            | `Vec<String>`               |
| `identifier_rename_queue.rs`           | `pat_names`                | `Vec<String>`               |
| `validate_emitted_exports.rs:237`      | inline `collect_pat_names` | `Vec<String>`               |

The crate already uses `swc_ecma_utils::find_pat_ids` via `binding_targets::binding_names()`. Two of the above reimpls produce `Vec<String>` instead of `Vec<Id>` — add a `binding_name_strings()` wrapper and eliminate all custom walkers.

### Declaration name extraction (2+ implementations) — **Done** (`0dc93325e`)

Consolidated into `binding_targets::declaration_ids` and `binding_targets::declaration_name_strings`. `chunk_ast.rs` has thin wrappers for `pub(super)` re-export.

### `module_export_name` (triplicated) — **Done** (`0dc93325e`)

Consolidated into `binding_targets::module_export_name`. Also found and replaced `module_export_atom` in `validate_emitted_exports.rs`.

### Import-decl construction (3 sites) — **Done** (`f576e543c`)

`util.rs:import_decl_for_plan` and `imports_cross.rs:phantom_side_effect_imports` now delegate to the existing `imports_runtime.rs:import_decl_module_item`. Only one `ImportDecl` construction site remains.

### Visitor method duplication (`lowering/visitors.rs`) — **Done** (`f576e543c`)

Extracted the 6 shared `VisitMut` methods into `impl_rename_visit_mut!()` macro. `RenameAndShorthandNaturalizer` uses the macro and adds its 2 extra methods.

### `read_json<T>` in e2e tests (6 copies)

Copy-pasted into `realizability_test.rs`, `at_init_s_chain_dataflow_test.rs`, `owner_graph_purity_reason_test.rs`, `at_init_promotion_fndecl_direct_read_test.rs`, `peel_factorize_landability_test.rs`, and `purity_test.rs`. Move to `support.rs`.

### Suffix-minting logic (2 implementations)

`exports.rs:mint_unique_public_name` and `util.rs:mint_fresh_local_name` both implement suffix-appending name uniquification with slightly different collision-check semantics. Share a core function.

### Identifier validation (2 near-identical functions)

`lowering/util.rs:is_valid_js_identifier` (line 15) and `is_identifier_like` (line 87) check the same `[A-Za-z_$]` first char, `[A-Za-z0-9_$]` rest pattern. The only difference is empty-string handling. Merge.

### Test fixture builders in peel/ (2 copies) — **Partially done** (`f576e543c`)

Extracted `binding()`, `member()`, `module_ref()` to `peel/test_utils.rs`. The `owner()`, `atomic_unit()`, `atomic_edge()`, `graph_fixture()` helpers have different signatures/semantics between the two test modules and remain local.

### Line-range accumulation (3 copies)

`start_line.min(...)` / `end_line.max(...)` / `size_lines_estimate += end - start + 1` duplicated in `reports.rs:169–179`, `factorize.rs:636–639`, `plan.rs:1361–365`. Extract as a method on `SourceLocation` or a free function.

### Vendor swap test workspace setup (4 copies)

`vendor_swap_test.rs` has four near-identical fixture constructors (`run_named_from_module_default_fixture`, `run_named_from_default_fixture`, `run_partial_swap_fixture`, `run_partial_swap_kind_fixture`) that all create TempDir, workspace/extracted/snapshot/out/wrapper directories, write snapshot files, write package.json, write spec YAML, run debundler. Extract a `VendorSwapWorkspace` builder.

---

## P2 — Structural Issues

### `lowering/util.rs` is a grab-bag module

Violates STYLE.md "No grab-bag modules" rule. Contains identifier validation, ordinal arithmetic, var-decl splitting, scope name collection, import disambiguation, import-decl construction, I/O helpers, and error rendering. Split into `lowering/identifiers.rs`, `lowering/scope_names.rs`, `lowering/import_emit.rs`, `lowering/ordinal.rs`, `lowering/io.rs`.

### `lowering/materialize.rs` (1026 lines) mixes 4 concerns

Orchestration/plan resolution (lines 39–342), factorization wiring (344–579), rebind folding (914–1026), and artifact assembly (787–912) are unrelated. Extract `fold_rebind_atomic_units` into its own file and factor out the `analysis_hints` collection (lines 359–405 — two near-identical loops for `explicit_requests` and `chunk_renames`).

### `lower/lower.rs` — 600-line monolithic function

`lower_chunk` is a single function performing 8 sequential phases, each gated by `time_phase!`. Extract into named phase functions, each with a smaller input struct. The `LowerChunkInputs` parameter struct has 15–20 fields — a code smell confirming the function does too much.

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

### `chunk_ast.rs:TopLevelDecl` — parallel vectors smell

Carries `names: Vec<String>` and `ids: Vec<Id>` which are always parallel vectors of the same length. A `Vec<(String, Id)>` or a small struct would make the invariant explicit and prevent misalignment.

### `exports.rs` — duplicate rejection functions

`reject_duplicate_export_names` and `reject_duplicate_member_bindings` are structurally identical (iterate members, collect seen names, report duplicates). Only differ in which field they check. A single generic function parameterized by the extraction closure.

### `naturalize.rs:81–117` — duplicated `Decl::Var` handling

The `Decl::Var` handling is identical in both the `Stmt::Decl` arm (line 92) and the `ExportDecl` arm (line 106). Extract a helper.

### `lowering/util.rs:77–86` — copy-pasted doc comment

The doc comment for `is_identifier_like` was copy-pasted from an unrelated function (references `MiniFactors` mode and plan synthesis). Fix it.

### `ids.rs:8–18` — historical changelog comment

17-line comment about the historical `BindingName` / `BindingTable` removal. Per STYLE.md, historical comments should be deleted.

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

## P4 — Rust Idioms & Minor Issues

### `should_rewrite_file` (rewrite_specifiers.rs:160)

Uses early returns for boolean: `if !X { return false; } if Y { return false; } true`. More idiomatic as a single expression.

### Unnecessary type alias (`chunk_factorization.rs:202`)

`type StatementFactsInput = crate::StatementFacts` adds indirection without value. Use the concrete type directly.

### `plan_references.rs:230–270` — phantom side-effect block bolted on

Conceptually independent concern at the end of `plan_module_reference_needs`. Extract to a separate function.

### `member_bucket` / `line_bucket` (`factorize.rs:782–814`)

Identical functions with identical match arms. Collapse to one `size_bucket`.

### `SwapVendorChunksConfig` destructuring (`pipeline.rs:176` and `260`)

Repeated verbatim. Extract a local variable.

### `lower.rs:398–404` vs `183–188` — duplicated filter

`!binding_assignment.contains_key(&top_level_id(binding, chunk_top_level_mark))` appears three times. The `top_level_id(binding, chunk_top_level_mark)` pattern appears ~30 times across the codebase — could be a method on a context struct carrying the mark.

### `body_facts.rs:33–36` — "mostly redundant" shadowing

Comment says sym-based shadowing is "mostly redundant" with hygiene-correct contexts and exists only for backwards compatibility. Either commit to hygiene and remove, or document the concrete invariant that requires it.

### `pipeline.rs` vendor block (135 lines)

The vendor-swap section in `run_transform_cli` (lines 161–296) should be extracted into `run_vendor_stages`.

### Redundant `chunk_top_level_mark` shadowing (`materialize.rs:493`)

Rebinds a variable already in scope from line 88. The second binding shadows the first unnecessarily.

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

### Immediately actionable

| What                                                                                    | Where                                                                                                           | SWC Equivalent                                                                                                                                             | Effort                                                                                                |
| --------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| `collect_pat_names` / `pat_names` / `binding_names` (4 custom String-returning walkers) | `strip_swapped_vendor_exports.rs:1079`, `validate_emitted_exports.rs:237`, `vendor.rs:~992`, `chunk_ast.rs:220` | `find_pat_ids` + `.map(\|id\| id.0.to_string())` or `for_each_binding_ident` (allocation-free callback version) — at pinned 29.1.1                         | Medium — add `binding_name_strings()` wrapper in `binding_targets`                                    |
| `declared_names` / `declaration_names` / `declaration_ids` (4 copies)                   | `vendor.rs:979`, `chunk_ast.rs:194,207`, `facts.rs:1726`                                                        | `collect_decls` (returns `FxHashSet<Id>`) + `find_pat_ids` — at pinned 29.1.1                                                                              | Medium — consolidate into one backed by `collect_decls`                                               |
| Identifier validation (3 near-identical ASCII checks)                                   | `vendor.rs:3048`, `lowering/util.rs:15,87`                                                                      | `is_valid_ident` from `swc_ecma_utils:1700` (full ES grammar + reserved word rejection) or `Ident::is_valid_start`/`is_valid_continue` for char-level only | Low — SWC's is stricter (rejects reserved words, accepts Unicode); local code deliberately skips this |
| `export_decl_declared_names`                                                            | `strip_swapped_vendor_exports.rs:353`                                                                           | Use consolidated `declaration_names` from `chunk_ast.rs`                                                                                                   | Low                                                                                                   |

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
| Export name collection                      | None                                                                       | No public SWC utility; consolidate the two local copies instead                                                                 |
| Import declaration construction             | `ExprFactory` trait (partial) — individual node construction only          | Debundle-specific relative-path logic has no SWC equivalent; keep but consolidate 3 copies                                      |

---

## Summary Statistics

| Category                         | Count                                                                                   |
| -------------------------------- | --------------------------------------------------------------------------------------- |
| God modules (P0)                 | 4 files totaling ~12K lines                                                             |
| Major duplication sites (P1)     | 11 patterns across ~30+ call sites                                                      |
| Structural issues (P2)           | 13 findings                                                                             |
| Encapsulation / type design (P3) | 13 findings                                                                             |
| Rust idioms / minor (P4)         | 9 findings                                                                              |
| Test-specific (P5)               | 9 findings                                                                              |
| JS live proxy                    | 5 findings                                                                              |
| SWC reuse opportunities          | 4 actionable, 1 potential DCE replacement, 8 underutilized utils, 9 not-worth-replacing |

## Top 5 Highest-Impact Actions

1. **Split `vendor.rs`** into `vendor/{manifests,ast_helpers,rename,full_swap,partial_swap,bundled_partial_swap}.rs`. Addresses the worst god module and much of the duplication in one change.

2. ~~**Unify all `collect_pat_names`/`binding_names`/`pat_names` reimplementations** to use `swc_ecma_utils::find_pat_ids` via a shared `binding_name_strings()` wrapper. Eliminates ~200 lines of duplicated AST walking.~~ **Done** (`0dc93325e`): added `binding_name_strings`, `declaration_ids`, `declaration_name_strings`, `module_export_name` to `binding_targets.rs`; removed 6 reimplementations across `chunk_ast`, `vendor`, `strip_swapped_vendor_exports`, `identifier_rename_queue`, `validate_emitted_exports`, `facts`, `program_analysis`. Net -185 lines.

3. **Split `analysis_tests.rs`** into 6–8 topic-aligned test modules. Largest test file at 4095 lines.

4. **Extract vendor-prune from `facts.rs`** into `facts/vendor_prune.rs`. Separates a 1000-line self-contained concern from general fact collection.

5. **Consolidate the 6 copies of `read_json<T>`** into `support.rs` and extract the cycle-forcing fixture pattern (~20 repetitions across 4 files) into a shared helper. Eliminates ~300 lines of test boilerplate.
