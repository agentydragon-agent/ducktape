# Rust Debundler Devel Merge Plan

Date: 2026-05-01

## Objective

Merge the Rust debundler work onto current `devel` as an atomic Rust
implementation drop, while preserving the JavaScript implementation as the
executable spec and keeping both implementations wired into the same black-box
e2e assertions.

The result should be:

- current `devel` JavaScript behavior preserved, plus the deterministic JS
  behavior change needed for Rust reproducibility
- Rust binary with the same CLI contract as the JS `run_transform` binary
- one shared e2e test implementation with JS and Rust targets
- Rust/JS parity over all devel-promoted e2e tests
- Tana reverse-engineering specs in `../gaffer-private` migrated or adjusted so
  the current Tana web snapshot runs with both JS and Rust

## Recon Snapshot

Refs inspected:

- Current Rust branch HEAD after committing the port work:
  `ab5d95462 Implement Rust debundler parity stages`
- Current `origin/devel`: `ff677df0d36742c6f5d6fe3e0077b24374879149`
- Branch/devel merge-base:
  `8cfbbb469a3efe47185e564e46d10bb48f505972`
- `../gaffer-private` currently pins ducktape:
  `26407e26162ce6604f09fa0ef8e758ee61bc06e6`

Dry-run merge result:

- `git merge-tree HEAD origin/devel` reports only two debundler conflicts:
  `devinfra/js/debundle/harness/BUILD.bazel` and
  `devinfra/js/debundle/harness/pipeline_e2e_test.mjs`.
- The conflict shape is expected: devel modified the existing JS browser e2e
  test, while this branch replaced it with implementation-parameterized harness
  tests.

Devel debundler changes since the fork point include:

- new black-box e2e tests under `devinfra/js/debundle/e2e/`
- generated syntax / binding / module-resolution validation
- large logical-module pipeline changes around selected atomic modules,
  fragments, naturalization, URL rebasing, side-effect handling, and export
  minimization
- vendor-swap structural verification and wrapper support
- mock browser bundle test-data flattening and pipeline e2e promotion

Rust branch changes relevant to devel:

- pure-Rust `//devinfra/js/debundle/rust:debundle_rust`
- JS-compatible `--spec`, `--package-root`, `--packages-root` CLI
- Rust stages for load/parse/normalize/rewrite/vendor/materialize/write/harness
- Rust parity tests for planner, analysis snapshots, browser harness, vendor
  stages, and initial logical materialization
- deterministic JS planner heuristic change:
  `estimatedRegionSize` should use ordinal span instead of line span
- shared JS/Rust parity regression for readable object-pattern default
  references after logical-module naturalization
- JS materializer guard fix for the minimized `II -> constraint` TDZ case:
  reject an outer readable rename when a descendant binding is also planned to
  naturalize to the same target name
- phase-aware Rust access modeling and staged-shell write-like reverse
  adjacency, matching the JS planner on the focused mock bundle

## Current Checkpoint

As of 2026-05-01, this branch has a minimal end-to-end regression for the Tana
live-proxy failure class:

- target: `//devinfra/js/debundle/harness:pipeline_stage_parity_test`
- fixture shape: top-level `II`, nested object-pattern param
  `{ constraint: t = II }`, and an extracted logical module
- assertion: both JS and Rust binaries execute the generated entry
  successfully, and neither emits `constraint = constraint`

The test initially failed in the JS implementation with the same TDZ shape seen
in Tana. It now passes after the JS naturalization guard was made aware of
pending descendant-scope renames.

Focused checks last run and passing:

```bash
bazelisk --output_user_root=/tmp/bazel-user-ducktape-rust \
  --output_base=/tmp/bazel-ducktape-rust-debundle \
  test \
  //devinfra/js/debundle/harness:pipeline_stage_parity_test \
  //devinfra/js/debundle/extract:init_region_test \
  //devinfra/js/debundle/harness:planner_internal_parity_test \
  //devinfra/js/debundle/harness:planner_internal_tiny_repro_test \
  --config=nolint --test_output=errors

bazelisk --output_user_root=/tmp/bazel-user-ducktape-rust \
  --output_base=/tmp/bazel-ducktape-rust-debundle \
  test //devinfra/js/debundle/harness:planner_parity_test \
  --config=nolint --test_output=errors

bazelisk --output_user_root=/tmp/bazel-user-ducktape-rust \
  --output_base=/tmp/bazel-ducktape-rust-debundle \
  test //devinfra/js/debundle/harness:rust_e2e_test \
  --config=nolint --test_output=errors

bazelisk --output_user_root=/tmp/bazel-user-ducktape-rust \
  --output_base=/tmp/bazel-ducktape-rust-debundle \
  test //devinfra/js/debundle/harness:pipeline_e2e_test \
  --config=nolint --test_output=errors
```

For local follow-up runs that should not require approval prompts, prefer a
temporary output base:

```bash
bazelisk --output_base=/tmp/bazel-ducktape-rust-debundle \
  test //devinfra/js/debundle/harness:pipeline_stage_parity_test \
  --config=nolint --test_output=errors
```

## Tana Recon

`../gaffer-private` is not currently on devel-compatible debundler specs. It
pins a ducktape commit before the public stage registry was refactored.

Generated current Tana specs into `/tmp` with alternate output roots:

- canonical: 25,478 lines
- guided selected owner: 24,554 lines
- split owner closure: 1,053 lines

Current generated stage/operation use:

- canonical spec: `load_js_tree`, `compute_js_asts`,
  `split_scope_hoisted_js_tree`, `apply_vendor_annotations`,
  `rename_vendor_exports`, `rename_bindings`,
  `extract_runtime_boundary_metadata`, `swap_vendor_chunks`,
  `extract_scrambled_identifier_frequencies`, `emit_browser_harness`,
  plus 30 `mark_vendor` ops and 1,182 `rename_binding` ops.
- split-owner spec: same old load/split/vendor stages plus
  `extract_ordered_init_owner_closure_pass` and `extract_ordered_init_regions`.
- guided spec: old load/split/rename stages plus
  `extract_guided_selected_owner_modules` and `write_js_tree`.

Baseline run:

- Ran current pinned JS Tana canonical spec through
  `//tana/re/web/transforms:run_transform` with `/tmp` output root.
- It passed in about 45 seconds.
- The large stages were split (~26.5s), rename (~7.7s), boundary analysis
  (~6.0s), scrambled identifier analysis (~1.2s), and harness emit (~0.9s).

Implication: current Tana works with the old JS implementation, but it will not
run on current ducktape `devel` unchanged. The Tana work is a real spec
migration, not only a ducktape pin bump.

Additional current finding:

- The migrated current-stage Tana candidate materializes four logical modules
  and serves the app/vendor/module files through live-proxy, but browser boot
  failed on `ReferenceError: Cannot access 'constraint' before initialization`.
- The root cause is readable naturalization turning upstream `II` into
  `constraint` while a nested object-pattern default also naturalizes
  `{ constraint: t = II }` to `constraint = constraint`.
- This branch now has a shared JS/Rust parity regression and a JS guard fix for
  that shape. Tana still needs to be regenerated and live-proxy validated
  against a ducktape pin containing that fix before generated outputs are
  commit-ready.

## Merge Strategy

Do not directly merge this branch into `devel` and resolve conflicts in-place.
That would make it too easy to accidentally carry old harness layout or stale JS
assumptions forward.

Preferred strategy:

1. Create a fresh integration branch from `origin/devel`.
2. Keep devel JS as authoritative.
3. Apply only the intentional JS behavior change from this Rust branch:
   `estimatedRegionSize(region) = ordinalSpanForRegion(region) * 1000 + ownerIds.length`.
4. Add the Rust implementation files and Bazel targets.
5. Reconcile test wiring on top of devel's e2e layout, not this branch's older
   harness layout.
6. Squash the ducktape side into one commit once parity and Tana validation pass.

Expected ducktape commit shape:

- add `devinfra/js/debundle/rust/**`
- add `devinfra/js/debundle/rust/AGENTS.md`
- update Rust deps / SWC versions only as needed
- update `devinfra/js/debundle/defs.bzl` to expose both JS and Rust transform
  binary macro support
- update e2e macros/tests so each black-box test implementation can run against
  JS and Rust
- keep devel's existing JS tests and e2e files
- add parity tests only where they compare behavior through the public CLI or
  stable structural reports
- update divergence docs to reflect remaining risks honestly

## Devel E2E Integration

Devel already has the right black-box test direction under
`devinfra/js/debundle/e2e/`: the shared `support.mjs` drives a binary via
`DUCKTAPE_RUN_TRANSFORM_BIN`.

Plan:

- Keep the JS targets' current names so devel users and CI do not lose test
  labels.
- Extend `e2e/defs.bzl` so the same source file can be instantiated against a
  binary label.
- Add Rust sibling targets, for example `lowering_rust_test`,
  `cross_module_rust_test`, `naturalization_rust_test`, and
  `url_rebase_rust_test`.
- Ensure every devel e2e assertion runs against both implementations.
- Keep `harness:pipeline_e2e_test` from devel and either add a Rust sibling or
  fold it into the same binary-parameterized pattern.
- Do not compare raw emitted JS formatting unless the output is normalized; use
  runtime behavior, exported names, manifests, and targeted structural regexes.

This resolves the current merge conflict by preserving devel's
`pipeline_e2e_test.mjs` intent and adding the Rust target wiring on top.

## Rust Parity Work Needed Before Merge

The current Rust port is not yet sufficient to call the devel merge conformant.
The biggest gaps are in exactly the areas devel recently promoted to e2e.

Required Rust work:

- Port devel's current logical materialization pipeline deeply, not fixture-by
  fixture: boundary analysis model, selected atomic module planner, owner
  fragments, side-effect attachment, binding placement, naturalization, URL
  rebasing, import/export generation, residual modules, and report metadata.
- Preserve the devel fixes now covered by e2e: split declarator evaluation
  order, function declaration hoisting, readable/default-reference
  naturalization, class extraction, TS-enum-style var lowering, plain import vs
  init-wrapper decisions, top-level effect init wrappers, collision rejection,
  cross-module dependency wiring, shared bootstrap dependency behavior, renamed
  dependency imports, object/constructor naturalization, worker URL rebasing,
  and dynamic import rebasing.
- Keep the newly added object-pattern default-reference naturalization parity
  case green in both JS and Rust while deepening the materializer.
- Implement `extract_scrambled_identifier_frequencies` in Rust, because devel JS
  registers it and Tana canonical uses it.
- Re-add or replace `extract_runtime_boundary_metadata` as a public stage if
  Tana still needs standalone boundary reports. The JS function still exists in
  `analysis/boundary.mjs`; if the stage is restored, Rust must implement the
  same report contract.
- Keep vendor swap parity for direct exports and wrapper shapes. Wrapper
  codegen formatting may differ, but export semantics and manifests must match.
- Keep all JS rewrites AST-backed in Rust. No text rewrite shortcuts.

Do not claim full parity until the devel e2e set passes for both JS and Rust and
Tana's generated spec passes both implementations.

## Tana Migration Plan

Treat the Tana migration as a coordinated follow-up commit in
`../gaffer-private`, validated before the ducktape Rust commit is merged.
Cross-repo atomicity may require two commits: one ducktape commit exposing the
new dual implementation, then one gaffer-private commit updating the ducktape
pin and specs.

Recommended spec migration:

- Replace `load_js_tree` with `load_js_chunks`.
- Replace `split_scope_hoisted_js_tree` with the current devel pipeline shape:
  `normalize_js_chunks` plus `rewrite_chunk_entry_specifiers` where needed.
- Keep `apply_vendor_annotations`, `rename_vendor_exports`,
  `swap_vendor_chunks`, `emit_browser_harness`, and `write_js_tree`, but verify
  their argument names against devel.
- Replace `extract_ordered_init_regions` and
  `extract_guided_selected_owner_modules` with
  `materialize_logical_modules`.
- Convert `extract_ordered_init_owner_closure_pass` usage into the current
  selected-owner/materialization model, likely by relying on default selected
  owners first and only adding explicit selected-owner caches if the generated
  output is unstable or too broad.
- Decide what to do with the 1,182 `rename_binding` operations. Current devel
  intentionally removed the public `rename_bindings` stage. Preferred path is
  to migrate high-value readable outputs into `define_logical_module` operations
  and generated materialized modules. If broad in-place rename is still a hard
  requirement for Tana, that must become an explicit new/returned stage and must
  be implemented in both JS and Rust with AST operations before the Rust merge
  can be called conformant.
- Re-run boundary analysis on devel and update any owner IDs, selected-owner
  caches, or fingerprints that shifted. Old Tana operations reference IDs like
  `owner_00113`; these may renumber after devel's normalization/materialization
  changes.

Recommended gaffer-private target shape:

- Keep the existing JS target names initially, or add `_js` aliases if labels
  need to be explicit.
- Add Rust sibling targets using a ducktape macro that points at
  `@ducktape//devinfra/js/debundle/rust:debundle_rust`.
- For each Tana spec variant, generate/run both JS and Rust with the same spec
  inputs and compare normalized outputs.
- Update committed `tana/re/web/out/v-78d928dca7/**` only after JS and Rust both
  generate accepted output.

Tana validation gates:

- Generate canonical, split-owner, and guided specs with `/tmp` output roots.
- Run each spec with JS.
- Run each spec with Rust.
- Compare vendor manifest, app manifest, chunk manifest, boundary summary, and
  scrambled identifier report after normalizing fields where ordering or codegen
  formatting is intentionally non-semantic.
- Run the Tana live proxy/load test against the generated browser harness for
  the JS output and Rust output.

Preferred local command style for recon that writes Bazel state outside the
workspace:

```bash
bazelisk --output_base=/tmp/bazel-gaffer-tana test \
  //tana/re/web/transforms:all \
  --config=nolint --test_output=errors
```

- If the old broad readable rename workflow is replaced by materialized modules,
  update Tana docs to point at the new generated module outputs rather than old
  in-place renamed chunk output.

## Validation Plan

Ducktape-side focused gates:

```bash
bbr test //devinfra/js/debundle/e2e/...
bbr test //devinfra/js/debundle/harness:...
bbr test //devinfra/js/debundle/rust:...
```

Then broader handoff gates:

```bash
bbr build //...
bbr test //...
```

Gaffer-private gates after pin/spec migration:

```bash
bazelisk run //tana/re/web/transforms:generate_transform_spec -- --variant canonical --out /tmp/tana-canonical.spec.jsonc --out-root /tmp/tana-canonical-js
bazelisk run //tana/re/web/transforms:run_transform_js -- --spec /tmp/tana-canonical.spec.jsonc
bazelisk run //tana/re/web/transforms:run_transform_rust -- --spec /tmp/tana-canonical.spec.jsonc
bazelisk test //tana/re/web/live_proxy:load_v_78d928dca7 --test_output=errors
```

Mirror those for split-owner and guided-selected-owner variants once their spec
migration is complete.

## Risks And Decisions

- Rust logical materialization is the main blocker. The current Rust code is
  AST-backed and useful, but it is not yet a deep devel-equivalent port.
- Tana's old `rename_bindings` use is not compatible with current devel. Decide
  explicitly whether to migrate to materialized readable modules or restore a
  standalone rename stage in both JS and Rust.
- If `extract_runtime_boundary_metadata` remains a Tana requirement, restore it
  deliberately as a supported stage rather than relying on private JS exports.
- Codegen formatting differences between Babel and SWC are expected. Tests
  should compare semantic structure unless the format is part of the contract.
- Cross-repo atomicity is not fully possible with a public ducktape commit and a
  private gaffer-private pin update. The practical atomic boundary is: validate
  the gaffer-private commit against a local ducktape override before landing the
  ducktape commit, then immediately update the gaffer-private pin.

## Immediate Next Steps

1. Start a clean integration branch from `origin/devel`.
2. Apply the deterministic `estimatedRegionSize` change and run the JS planner
   tests.
3. Bring over Rust files and Bazel targets without replacing devel JS/harness
   files.
4. Rework devel e2e macros to emit JS and Rust targets from one test source.
5. Port the remaining devel logical-materialization and analysis stages to
   Rust.
6. Run devel e2e and parity tests for both implementations.
7. Migrate Tana specs in `../gaffer-private` against a local ducktape override.
8. Validate Tana canonical/split/guided outputs with JS and Rust before
   squashing the ducktape merge commit.
