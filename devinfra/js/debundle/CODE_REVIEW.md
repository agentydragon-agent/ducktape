# Debundle Code Review

Full-package review of `devinfra/js/debundle/` (~47K lines). Findings prioritized by impact.

---

## P0 — God Modules

### `vendor/mod.rs` (3052 lines) — **Partially done**

Manifest types extracted to `vendor/manifests.rs`. Strip logic extracted to `vendor/strip.rs`. Remaining work:

- `apply_partial_vendor_swaps` and `apply_bundled_partial_vendor_swaps` are near-identical dispatchers (build job vec, rayon `into_par_iter`, collect results, aggregate counts, write manifest). Unify with a generic helper or trait-based dispatch.

### `purity.rs` (2671 lines, 5 concerns)

Mixes graph construction (`ChunkCodeGraph`), whitelist constant tables (~400 lines of static data), expression classification, PlainData write scanning, and TS enum IIFE recognition.

- Whitelist tables (`PURE_STATIC_PROPS` through `PLAIN_DATA_HOSTILE_BUILTINS`, lines ~1600–1750) should be in `purity/whitelists.rs` or a data file.
- `classify_fresh_array_spread_source_purity` and `classify_fresh_array_spread_source_for_iterable` are near-identical recursive classifiers differing only in the result interpretation. Unify with a parameterized return.
- ~80-line doc comment on `PURE_OBJECT_CALLS_ON_PLAIN_DATA` (lines 1657–1741) and ~55-line PlainData soundness comment (lines 37–91) are design-doc material. Keep 3–5 line summaries in code.
- `ChunkCodeGraph` mixes SCC computation with classification state. The SCC computation could be a standalone function.

### `analysis_tests.rs` (4095 lines, 8+ subsystems)

Tests 8+ distinct subsystems in one file: fact analysis, decorate helpers, cycle detection, atomic unit conflicts, purity classification, plain-data tracking, redundant hints, statement splitting, factor assembly. A test for purity must scroll past 600 lines of fact-analysis tests to find helpers.

Split into topic-aligned modules: `tests/facts.rs`, `tests/purity.rs`, `tests/plain_data.rs`, `tests/cycles.rs`, `tests/atomic_units.rs`, `tests/statement_splitting.rs`.

### `facts.rs` (2219 lines, 3 concerns)

~1000 lines of vendor-prune-specific local effect analysis (lines 533–1583) embedded in general statement-fact collection. The `vendor_prune_*` functions are a self-contained concern. Extract to `facts/vendor_prune.rs` or behind a feature flag. The vendor-prune analysis should accept `StatementFacts` as input rather than being embedded in the collection pass.

---

## P1 — Major Duplication

### Test fixture builders in peel/ (2 copies) — **Partially done** (`f576e543c`)

Extracted `binding()`, `member()`, `module_ref()` to `peel/test_utils.rs`. The `owner()`, `atomic_unit()`, `atomic_edge()`, `graph_fixture()` helpers have different signatures/semantics between the two test modules and remain local.

### Line-range accumulation (3 copies) — **Done** (`0cbe93546`)

Deduplicated into a shared helper.

### Vendor swap test workspace setup — **Partially done**

`VendorTestWorkspace` builder extracted but only adopted by 2 of 4 fixture constructors (`run_partial_swap_fixture`, `run_partial_swap_kind_fixture`). `run_named_from_module_default_fixture` and `run_named_from_default_fixture` still construct workspaces inline.

---

## P2 — Structural Issues

### `lowering/util.rs` is a grab-bag module — **Done** (`0cbe93546`)

Split into `lowering/scope_names.rs`, `lowering/import_emit.rs`, `lowering/ordinal.rs`, `lowering/io.rs`.

### `lowering/materialize.rs` (1026 lines) mixes 4 concerns

Orchestration/plan resolution (lines 39–342), factorization wiring (344–579), rebind folding (914–1026), and artifact assembly (787–912) are unrelated. Extract `fold_rebind_atomic_units` into its own file and factor out the `analysis_hints` collection (lines 359–405 — two near-identical loops for `explicit_requests` and `chunk_renames`).

### `lower/lower.rs` — monolithic function (partially extracted)

`lower_chunk` had 8 sequential phases inline. Four have been extracted into named functions (`compute_selected_ordinals`, `plan_selected_exports`, `split_entry_body`, `build_module_output`). Remaining inline phases (naturalization, disambiguation, import planning, the per-module loop) could be further extracted, though each requires substantial captured state from `LowerChunkInputs` (15–20 fields).

### `lowering/mod.rs` — 266-line import block

Consequence of wildcard `use super::*` in every sub-module. A more targeted import strategy would reduce this.

### `emit_harness.rs` — repeated JSON-write pattern

`serde_json::to_writer_pretty` calls scattered across emit_harness.rs, write_tree.rs, artifact.rs, identifier_rename_queue.rs, pipeline.rs. Extract a shared `write_json` helper.

### `output_layout.rs` — 10 identical accessor methods

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

## Data Shape Smells

Audit of data structures and data flow in the debundle pipeline.

### Root cause

The pipeline used a single mutable artifact passed through every stage, with fields stamped as stages run. The fix was not splitting types while keeping the mutation pattern — it's making each stage a pure function that takes inputs and returns outputs, with no shared mutable state.

### Fixed (Phases 1-7)

| #   | Smell                                                                                   | Fix                                                                                                                                                              |
| --- | --------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------- | ----------------------------------- |
| 1   | `JsPipelineArtifact` was a mutable pipeline envelope with misleading name               | Renamed to `ChunkBundle`                                                                                                                                         |
| 6   | `ChunkManifest` mixed analysis, decomposition, and write-time data                      | Split into `ChunkAnalysis` (analysis), `ChunkDecompositionOutput` (decomposition), `ChunkManifest` (write-time assembly via `from_analysis`)                     |
| 7   | `ArtifactManifest` was a grab-bag accumulator with `empty()`                            | Constructed once in `write_tree.rs` with all data explicit; `empty()` deleted                                                                                    |
| 8   | `ArtifactCounts.selected_module_lowerings` was redundant                                | Removed                                                                                                                                                          |
| 9   | `FileMetadata` was all-optional grab-bag                                                | Required fields (`chunk_id`, `chunk_file`, `role`, `source_path`); dead `output_path` removed; `generated_stage` → `generated_by_selected_module_lowering: bool` |
| 11  | Imperative `try_fold` in `prepare_chunks`                                               | Replaced with validation loop + `map`/`collect`                                                                                                                  |
| 12  | Imperative loop in `swap_vendor_chunks`                                                 | Replaced with `collect::<Result<_>>() + retain_chunks()`                                                                                                         |
| 14  | `update_root_manifest` / `prune_artifact_to_chunk_ids` were stamp functions             | Deleted / simplified                                                                                                                                             |
| 15  | `write_tree` clone-then-stamp                                                           | `ArtifactManifest` constructed from explicit args; `WriteTreeInput` struct replaces 7 params; return type simplified to `Result<()>`                             |
| 16  | `emit_harness` read from `root_manifest.chunks`                                         | Takes `chunk_records` as explicit arg                                                                                                                            |
| 17  | `pipeline.rs` read `selected_module_lowerings` from root manifest                       | Reads from `materialize_result.selected_lowerings` directly                                                                                                      |
| 19  | `MaterializeLogicalModulesResult` carried artifact back with stamped decomposition data | `selected_lowerings` and `module_count` flow through result struct                                                                                               |
| 21  | Forged `Default` impls on metrics types                                                 | `Default` removed from `OutputMetrics`, `DecompositionMetrics`, etc.                                                                                             |
| 22  | Serialization via intermediate string allocation                                        | All manifest sites use `serde_json::to_writer_pretty`                                                                                                            |
| 23  | `.map(                                                                                  | \_                                                                                                                                                               | ())`discarded`WriteJsTreeManifest` return | Return type changed to `Result<()>` |
| 24  | `too_many_arguments` suppression on `write_js_tree`                                     | `WriteTreeInput` struct bundles parameters                                                                                                                       |
| 25  | Type names didn't match semantics after refactor                                        | `ChunkManifest` → `ChunkAnalysis`, `WrittenChunkManifest` → `ChunkManifest`, field `manifest` → `analysis`                                                       |

### Fixed (Phases A-E)

| Smell                                                                 | Fix                                                                                                                                           |
| --------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| `ChunkArtifact.decomposition: Option<ChunkDecompositionOutput>` stamp | Field removed; decomposition flows as `HashMap<ChunkId, ChunkDecompositionOutput>` via `MaterializeLogicalModulesResult` and `WriteTreeInput` |
| `artifact.chunks` — `mem::take` and reassign                          | `materialize_logical_modules` takes `ChunkBundle` by value, returns new `ChunkBundle`; no `mem::take`                                         |
| `ChunkMetadata.module_extraction_state: None` → `Some(...)`           | Field and `ModuleExtractionState` struct removed entirely (dead code)                                                                         |
| `ChunkAnalysis` post-creation mutation (`entry_file`, `files`)        | Struct update syntax (`..base_analysis.unwrap_or_else(...)`) replaces `let mut` + overwrite                                                   |
| `JsFile.body` in-place mutation                                       | `JsFile::into_rendered_source()` consuming transformation; `prepare_chunks` uses remove/render/insert                                         |

### Acceptable patterns (not stamp-driven)

#### `JsChunk` file bag: `remove_file` + `insert_file` in `rewrite_specifiers.rs` and `vendor.rs`

Both stages extract files for rayon parallel processing, then re-insert results. This is driven by parallelism requirements, not by a stamp pattern — the remove/insert is a consequence of needing to move file data into parallel tasks. No fix needed.

### Remaining TODO

#### TODO: `ChunkBundle` ownership ping-pong

Ownership still passes through every stage via return: `artifact = result.artifact`. Could be cleaner with a builder or consuming pipeline, but each stage is now a pure function so the remaining smell is cosmetic.

#### TODO: Pipeline ordering — `generated_by_selected_module_lowering` flag

`generated_by_selected_module_lowering` exists solely so `rewrite_chunk_entry_specifiers` can skip specifier rewriting on files synthesized by the lowering stage. This flag wouldn't be needed if specifier rewriting ran _before_ lowering. Investigate whether reordering the pipeline stages eliminates the need for the flag entirely.

#### DEFERRED: `ChunkTable` / `ChunkId(usize)` interned IDs

`ChunkId(usize)` is an interned identifier: 8 bytes, `Copy`, cheap to hash. Replacing with `String` would mean 24-byte heap-allocated keys, string comparison on every HashMap lookup, and `BTreeMap` O(log n) vs `Vec` O(1). The interned-ID pattern is standard in compilers/analyzers and arguably correct here. Revisit only if the duplication becomes actively harmful.

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

| Category                         | Count                                  |
| -------------------------------- | -------------------------------------- |
| God modules (P0)                 | 4 files totaling ~12K lines            |
| Major duplication sites (P1)     | 3 patterns remaining                   |
| Structural issues (P2)           | 4 findings                             |
| Encapsulation / type design (P3) | 13 findings                            |
| Test-specific (P5)               | 9 findings                             |
| SWC reuse opportunities          | 8 underutilized utils, 1 DCE candidate |

## Top 5 Highest-Impact Actions

1. **Continue splitting `vendor/mod.rs`** — manifests and strip extracted; remaining: unify partial-swap dispatchers into generic helper.

2. **Split `analysis_tests.rs`** into 6–8 topic-aligned test modules. Largest test file at 4095 lines.

3. **Extract vendor-prune from `facts.rs`** into `facts/vendor_prune.rs`. Separates a 1000-line self-contained concern from general fact collection.

4. **Extract `write_json` helper** from emit_harness.rs and write_tree.rs (2 identical copies), deduplicate direct `serde_json::to_writer_pretty` calls in artifact.rs, identifier_rename_queue.rs, pipeline.rs.

5. **Split `lowering/materialize.rs`** — extract `fold_rebind_atomic_units` and deduplicate the `analysis_hints` collection loops.
