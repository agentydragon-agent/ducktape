# Debundle Rust Rewrite Tracker

Status: **in progress — focused planner/e2e parity green, full-corpus parity not yet proven**
Last updated: 2026-05-01 (planner closure/frontier parity repaired)
Owner: debundle maintainers

## Scope and strict parity bar

This tracker documents **material algorithmic divergences** between:

- JS source of truth pipeline (`analysis/*`, `extract/*`, `split/*`, `harness/*`), and
- Rust rewrite pipeline (`rust/pipeline.rs`, `rust/plan.rs`, `rust/emit.rs`).

Parity means **exactly the same algorithmic behavior**:

1. same semantic inputs,
2. same intermediate planner state,
3. same candidate set and blocking payloads,
4. same selected output,
5. same emitted artifacts,
6. same runtime/e2e outcomes.

---

## Current status

No active divergence is currently known in the focused mock-bundle planner/e2e
targets. The former Stage 3B frontier/component closure blocker is repaired:
`planner_internal_parity_test`, `planner_parity_test`, and `rust_e2e_test`
now pass in the focused suite.

Minimal reproducer target:

- `//devinfra/js/debundle/harness:planner_internal_tiny_repro_test`
- Uses an in-test reduced chunk (`seen` + `__vitePreload` + one `await` call).
- Emits side-by-side state rows for seed metadata, component IDs, and closure owner sets.
- Asserts exact JS/Rust frontier parity. This test now passes.

Current next work:

- expand strict parity coverage beyond the focused mock fixture,
- keep closing residual access-model exactness risks (especially local-scope and class-feature edge cases),
- rerun/repair the downstream gaffer-private reverse-engineering repin flow against the current Rust binary.

## 2026-05-01 closure parity repair checkpoint

Root cause fixed:

- Rust access analysis collapsed nested function-body reads/writes into eager top-level accesses.
- Rust staged-shell adjacency reversed only eager dependency edges, while JS reverses all write-like accesses (`write` and `member_write`, eager or lazy).
- JS computed `seedComponentDepOwnerIds` in the owner-closure plan but dropped it when materializing staged-shell batch plans, which made parity diagnostics compare a real Rust field against an absent JS field.

Changes made:

- Rust now records phase-aware access buckets: eager/lazy reads, eager/lazy binding writes, and eager/lazy member writes.
- Nested function bodies are collected as lazy accesses, matching JS `classifyNestedFunctionPhase`.
- Rust staged-shell owner adjacency now mirrors JS: forward edges come from all local-declaration accesses, reverse edges come from all write-like accesses.
- JS staged-shell batch plans now preserve `seedComponentDepOwnerIds`, so parity tests compare actual planner data instead of tolerating an absent field.
- The tiny repro has been converted from an expected-divergence test to a strict parity test.

Validated targets:

- `bazelisk --output_user_root=/tmp/bazel-user-ducktape-rust --output_base=/tmp/bazel-ducktape-rust-debundle test //devinfra/js/debundle/harness:pipeline_stage_parity_test //devinfra/js/debundle/extract:init_region_test //devinfra/js/debundle/harness:planner_internal_parity_test //devinfra/js/debundle/harness:planner_internal_tiny_repro_test --config=nolint --test_output=errors`
- `bazelisk --output_user_root=/tmp/bazel-user-ducktape-rust --output_base=/tmp/bazel-ducktape-rust-debundle test //devinfra/js/debundle/harness:planner_parity_test --config=nolint --test_output=errors`
- `bazelisk --output_user_root=/tmp/bazel-user-ducktape-rust --output_base=/tmp/bazel-ducktape-rust-debundle test //devinfra/js/debundle/harness:rust_e2e_test --config=nolint --test_output=errors`
- `bazelisk --output_user_root=/tmp/bazel-user-ducktape-rust --output_base=/tmp/bazel-ducktape-rust-debundle test //devinfra/js/debundle/harness:pipeline_e2e_test --config=nolint --test_output=errors`

All four commands passed.

## 2026-04-30 conformance run log

Attempted parity conformance targets:

- `bazelisk test //devinfra/js/debundle/harness:planner_internal_parity_test --remote_executor="" --remote_cache="" --noremote_accept_cached --noremote_upload_local_results --config=nolint --test_output=errors`

Result:

- Local-only `bazelisk` run completed build+execution without BuildBuddy remote execution, and the parity test failed at the Stage 3B frontier gate (`requiredClosureOwnerIds`).

Historical interpretation:

- This session produced a fresh local parity signal and reconfirmed the first failing seed remains `owner_component_0002` with under-expanded Rust closure owners.
- Superseded by the 2026-05-01 closure parity repair checkpoint above.

### 2026-04-30 progress update (historical)

- ✅ **Stage 1 fallback removal tightened in Rust analysis path**:
  - missing module analysis for a chunk now fails fast,
  - missing parsed AST for a chunk now fails fast,
  - missing per-owner uses/writes maps now fail fast,
  - missing owner declaration line now fails fast.
- ✅ Re-ran local parity gate with remote execution disabled; first failing frontier seed remained unchanged at the time.
- Superseded by the 2026-05-01 closure parity repair checkpoint above.

### 2026-05-01 progress update (historical pre-repair checkpoint)

- ✅ Rust component dependency seeding now includes all `local_declaration` accesses with an owner id (JS-equivalent `selectedModuleAccessView(owner).all` shape).
- ✅ Rust eager dependency owner collection now includes eager `read` accesses in addition to eager writes/member-writes (closer to JS `eagerReadLike` semantics).
- ✅ Rust owner-component SCC/dependency construction now ignores cross-module dependency edges, matching JS selected-module componentization scope (per analyzed module/chunk).
- ✅ Planner-internal parity harness gate now compares frontier values by normalized seed-owner key (not array index), eliminating false-positive order-only deltas and reporting the true first semantic mismatch seed.
- ✅ Rust owner-record dependency derivation now uses normalized `dep_edges` as the source of planner dependency seeds (instead of raw access filtering), to mirror the dependency view already materialized during analysis.
- Superseded by the closure parity repair checkpoint above.

### 2026-05-01 reanalysis checkpoint (historical pre-repair failure)

Latest local parity gate run:

- `bazelisk test //devinfra/js/debundle/harness:planner_internal_parity_test --remote_executor="" --remote_cache="" --noremote_accept_cached --noremote_upload_local_results --config=nolint --test_output=errors`

At this point the first semantic mismatch was:

- gate: `requiredClosureOwnerIds`
- seed key: `owner_00002`
- Rust: `["owner_00002"]`
- JS: `["owner_00000","owner_00001","owner_00002","owner_00003"]`

Latest trace delta context:

- Rust `requiredComponentIds`: `["owner_component_0000"]`
- JS `requiredComponentIds`: `["owner_component_0002"]`
- Rust `seedComponentDepOwnerIds`: `[]`
- JS `seedComponentDepOwnerIds`: `[]`

Historical interpretation:

- Seed-keyed comparator confirms this is not ordering noise.
- Both sides agree the seed is `seen` (`owner_00002`) but Rust still materializes a singleton closure where JS materializes a 4-owner closure.
- This divergence is now fixed by phase-aware Rust access modeling plus JS diagnostic payload propagation.

### Precise divergence point identified (JS vs Rust, parallel dive)

After instrumenting `planner_internal_parity_test` to print full trace records at the first mismatch, we confirmed:

- Rust and JS report the same `requiredComponentIds` (`["owner_component_0002"]`) at the failing index.
- But they attach different owner closures to that same component id.

This isolates a concrete algorithmic mismatch boundary:

1. **JS path** runs planner componentization per chunk (component IDs are chunk-local and restart per chunk analysis).
2. **Rust path** runs planner componentization over the aggregated multi-chunk analysis snapshot (component IDs are global in one graph).

Therefore, the current parity comparator was aligning traces by `seedComponentId` labels that are **not globally stable across JS chunk runs**, while Rust labels were global.

### Identity normalization progress (done)

- Parity frontier gate comparison now keys traces by `seedOwnerIds` (owner-closure seed scope) rather than raw `seedComponentId`.
- This makes JS/Rust frontier identity comparable before semantic comparison.

### First remaining mismatch after identity normalization (historical)

- Gate: `requiredClosureOwnerIds`
- Comparable seed key: `owner_00002`
- Rust values: `["owner_00002"]`
- JS values: `["owner_00000","owner_00001","owner_00002","owner_00003"]`

Interpretation at the time: the first red gate was a **true semantic closure-expansion divergence**, not a namespace/labeling mismatch. This was later fixed.

### Closure-propagation edge instrumentation (done, later standardized)

- Added seed-scope dependency-edge trace fields in parity plumbing:
  - JS frontier trace now carries `seedComponentDepOwnerIds` (when available from planner payload).
  - Rust frontier trace already carries `seed_component_dep_owner_ids`.
- Later fix: JS staged-shell batch plans now propagate `seedComponentDepOwnerIds`, so this payload is part of strict parity rather than an ignored diagnostic gap.

## Pipeline-ordered divergence list (start → end)

The list below is the **current exhaustive inventory of material differences** between Rust and JS, ordered by pipeline execution order.

| Order | Pipeline slice                                      | Rust path materially differs from JS by...                                                                                                                        | Impact on parity signal                                                               |
| ----- | --------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| 1     | Analysis IR/access modeling                         | Phase-aware access buckets now match the JS planner shape for the focused fixtures, but full local-scope/class-feature exactness is not yet proven across corpus. | Residual access modeling gaps can still shift dependency edges outside covered cases. |
| 2     | Ordered-init planner state                          | Dedicated ordered-init parity has passed, but broader side-effect/touched-owner edge cases still need corpus coverage.                                            | Can change attachability + blocking payloads if an uncovered edge case exists.        |
| 3     | Dependency components + closure expansion           | Former active closure under-expansion bug is fixed in the focused planner suite.                                                                                  | No known focused-suite divergence; needs full-corpus confirmation.                    |
| 4     | Contiguous envelope/barrier semantics               | Focused planner parity is green, but envelope/barrier behavior is not yet stress-tested on representative large bundles.                                          | Candidate universe can still diverge in uncovered patterns.                           |
| 5     | Candidate identity/canonicalization                 | Focused `planner_internal_parity_test` and `planner_parity_test` now pass.                                                                                        | Remaining risk is corpus breadth, not a known focused-fixture mismatch.               |
| 6     | Staged-shell lowering (`stageRuns`, `shellItemIds`) | Focused planner parity is green after aligning write-like reverse adjacency and JS diagnostic payload propagation.                                                | Needs full-corpus and devel-merge validation.                                         |
| 7     | Blocking reason payload construction                | Some class payload derivation in Rust remains a known risk area until covered by stricter fixtures.                                                               | Blocking reason payload diffs remain possible in uncovered class cases.               |
| 8     | Selection/packing tie-break + occupancy edge rules  | Focused planner parity is green.                                                                                                                                  | Remaining risk is tie-break behavior on larger/denser candidate sets.                 |
| 9     | Emitter/lowering artifact generation                | `rust_e2e_test` now passes on the focused harness.                                                                                                                | Full artifact/text parity still needs broader corpus and external-use validation.     |
| 10    | Runtime/e2e behavior parity                         | `pipeline_e2e_test` and `rust_e2e_test` passed in the focused run.                                                                                                | End-to-end parity is not yet proven for the large external use case.                  |
| 11    | Corpus + CI enforcement                             | Rust parity gates are not yet sustained across full representative corpus in CI.                                                                                  | No safe default-flip/cutover readiness until corpus/CI coverage expands.              |

## Parity test matrix (current known state)

| Test target                                                                 | Scope                                           | Current known state        | Notes                                                                                  |
| --------------------------------------------------------------------------- | ----------------------------------------------- | -------------------------- | -------------------------------------------------------------------------------------- |
| `//devinfra/js/debundle/harness:analysis_parity_test`                       | Analysis IR parity                              | 🟢 Passing (last recorded) | Mentioned green in prior local-only parity run.                                        |
| `//devinfra/js/debundle/harness:ordered_init_parity_test`                   | Ordered-init planner state parity               | 🟢 Passing (last recorded) | Dedicated ordered-init harness was green in prior update.                              |
| `//devinfra/js/debundle/harness:planner_internal_tiny_repro_test`           | Minimal closure parity reproducer               | 🟢 Passing                 | Now asserts exact JS/Rust frontier parity for the reduced `seen`/`__vitePreload` case. |
| `//devinfra/js/debundle/harness:planner_internal_parity_test`               | Planner-internal full frontier/candidate parity | 🟢 Passing                 | Focused mock-bundle planner internals are green.                                       |
| `//devinfra/js/debundle/harness:pipeline_impl_analysis_parity_fixture_test` | JS/Rust analysis pipeline fixture parity        | 🟢 Passing (last recorded) | Mentioned green in prior local-only parity run.                                        |
| `//devinfra/js/debundle/harness:js_e2e_test`                                | JS pipeline end-to-end behavior                 | 🟢 Passing (last recorded) | JS path remains green.                                                                 |
| `//devinfra/js/debundle/harness:planner_parity_test`                        | Higher-level planner/lowering parity            | 🟢 Passing                 | Focused planner/lowering parity is green.                                              |
| `//devinfra/js/debundle/harness:rust_e2e_test`                              | Rust rewrite end-to-end parity                  | 🟢 Passing                 | Focused Rust e2e harness is green.                                                     |
| `//devinfra/js/debundle/harness:pipeline_e2e_test`                          | JS pipeline end-to-end behavior                 | 🟢 Passing                 | Focused JS pipeline e2e harness is green.                                              |

## Stage 1 — Analysis IR contract parity (pipeline entry)

### Current Rust state

- Rust now carries explicit owner-access records (`kind`, `access_kind`, `phase`, `owner_id`, `name`).
- Access records are now phase-aware across eager/lazy reads, binding writes, and member writes.
- Dependency/eager/write-like seeds derive from access records rather than token-only heuristics.
- Unresolved accesses are represented as runtime-import-like accesses.

### Remaining gap to exactness

- Confirm full one-to-one parity with JS access descriptor semantics and ordinal ordering used downstream.
- Eliminate any residual fallback paths that do not originate from JS-equivalent access modeling.

### Required done condition

- Analysis parity fixtures assert exact access-record equivalence (including ordering) for JS vs Rust.

---

## Stage 2 — Ordered-init planner state parity

### Current Rust state

- Rust includes ordered-init scaffolding with replayable side-effect maps and runtime-sensitive/touched-owner fields.
- Attachability uses this state more than before.

### Remaining gap to exactness

- Replayability predicate is still not proven equivalent to JS.
- Runtime-sensitive source and touched-owner derivation still have parity risk.
- Focused planner parity now passes; remaining ordered-init risk is uncovered corpus breadth.

### Required done condition

- `replayableSideEffectIdsByOwnerId` and `replayableSideEffectStateById` deep-equal JS with no normalization exceptions.

### 2026-04-30 progress update

- Added dedicated strict ordered-init parity harness target: `//devinfra/js/debundle/harness:ordered_init_parity_test` (green).
- Rust ordered-init map builder now:
  - pre-seeds owner-key map entries for all owners,
  - sorts/dedups side-effect ids per owner for deterministic parity assertions.
- Later update: focused planner parity is now green after the 2026-05-01 closure repair.

---

## Stage 3 — Dependency component + closure formation parity

### Current Rust state

- Rust now builds owner SCC components and derives closure candidates from component-level transitive dependency closure.
- Dependency component edges now use all local-declaration accesses with an owner id, matching JS `selectedModuleAccessView(owner).all`.
- Staged-shell reverse adjacency now uses all write-like accesses, matching JS `selectedModuleAccessView(owner).writeLike`.
- Rust now performs contiguous-envelope component expansion over owner ordinals; focused planner parity is green.

### 2026-04-30 progress update (historical)

- Rust closure seeding now starts from owner **SCC components** with component-level transitive dependency closure expansion (Stage 3 kickoff implementation).
- Owner dependency edges used for component construction were initially constrained to eager local-declaration forward-dependency-like accesses (`phase: eager`, `access_kind in {read, write, member_write}`).
- Rust contiguous-envelope growth now applies explicit program-item barrier categories via ordinal map: missing program item, non-declaration program item, and missing declaration barriers all stop expansion.
- Missing-owner-to-component mapping also stops envelope expansion (JS-equivalent barrier category).
- Closure candidates are now deduped by closure owner-set signature before packing, and candidate IDs are re-numbered contiguously from surviving closure order to reduce identity drift.
- Planner-internal harness now includes explicit pre-packing candidate-universe assertions before selected/packed comparisons to isolate Stage-3 drift earlier in the pipeline.
- Later update: focused `planner_internal_parity_test` is now green after phase-aware access modeling and write-like reverse adjacency.

### Remaining gap to exactness

- No focused-fixture divergence is currently known.
- Closure identities and expansion frontier rules need representative large-bundle corpus coverage before they can be considered fully locked.

### Required done condition

- Pre-packing candidate universe parity (IDs, owner sets, closure membership/order) is exact across focused and representative corpus fixtures.

---

## Stage 4 — Staged-shell batch construction parity

### Current Rust state

- `stageRuns`/`shellItemIds` scaffolding exists and focused planner parity is green.

### Remaining gap to exactness

- Expansion/interleave/materialization rules still need broader corpus validation.

### Required done condition

- Deep-equal parity for `stageRuns`, `shellItemIds`, `semanticOwnerIds`, `semanticMemberNames`.

---

## Stage 5 — Blocking reason class + payload parity

### Current Rust state

- Class names/order are closer to JS.

### Remaining gap to exactness

- Some payload construction remains heuristic.
- Eager/shell payloads are not fully guaranteed to derive only from parity access/planner state.

### Required done condition

- Per-class payload parity (content, ordering, dedup) is exact for candidate and selected views.

---

## Stage 6 — Selection/packing parity

### Current Rust state

- Preselection and occupancy scaffolding exist.

### Remaining gap to exactness

- Edge rules for collisions, preselected interactions, and tie-break ordering are not yet guaranteed exact.

### Required done condition

- Selected IDs and full debug payload match JS exactly.

---

## Stage 7 — Emitter/lowering artifact parity

### Current Rust state

- Rust emitter path exists but is not yet validated as exact JS-equivalent lowering.

### Remaining gap to exactness

- Generated artifact trees can still diverge semantically and textually beyond allowed normalizations.

### Required done condition

- Strict artifact parity on parity corpus (with explicit, documented non-semantic exclusions only).

---

## Stage 8 — Runtime/e2e parity

### Current Rust state

- Focused JS and Rust e2e targets pass (`pipeline_e2e_test`, `rust_e2e_test`).

### Remaining gap to exactness

- Runtime behavior still needs representative corpus and external gaffer-private validation.

### Required done condition

- Rust e2e and shared JS/Rust e2e coverage pass consistently using the same fixtures and assertions across focused and representative corpus cases.

---

## Stage 9 — Corpus + CI gate parity (promotion readiness)

### Current Rust state

- Parity signal is still concentrated on mock/synthetic paths with partial non-mock coverage.

### Remaining gap to exactness

- Need sustained strict parity across mock + representative non-mock bundle fixtures.

### Required done condition

- CI enforces planner + artifact + runtime parity gates over mock and non-mock corpus before default flip.

## Consolidated forward plan (merged from plans/debundle_rust_parity_plan.md)

1. Add/identify representative non-mock bundle fixtures that stress local scopes, class features, side effects, and dense candidate packing.
2. Promote the focused green planner/e2e targets into the expected merge gate for the Rust drop.
3. Validate devel-added e2e tests against both JS and Rust binaries using the shared e2e implementation.
4. Repin/regenerate the gaffer-private reverse-engineering use case against current ducktape without overrides, then minimize any newly exposed generic debundler fixture.
5. Close any corpus-discovered blocking-reason, selection/packing, or artifact text parity gaps.
6. Enable sustained CI parity gates over focused + representative corpus before default flip.
