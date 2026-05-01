# JS Debundler vs Rust Port Parity Checkpoint

Date: 2026-05-01

## Scope

This note records the current parity state of the Rust debundler port relative to
the JavaScript implementation. The JavaScript implementation remains the
executable specification.

The Rust implementation must stay:

- exact-parity with JavaScript
- pure Rust, with no shell-outs to JavaScript
- AST-backed for JavaScript transformations
- structurally aligned with the full JavaScript pipeline, not fixture-shaped

## Current Status

The Rust path is now a pure-Rust, SWC-backed, spec-driven pipeline. It has stage
handlers for the primary fixture and the first vendor/logical/write stages:

- `load_js_chunks`
- `compute_js_asts`
- `normalize_js_chunks`
- `apply_vendor_annotations`
- `rename_vendor_exports`
- `rewrite_chunk_entry_specifiers`
- `swap_vendor_chunks`
- `emit_browser_harness`
- `materialize_logical_modules`
- `write_js_tree`

Implemented or substantially aligned:

- JS-style `--spec` CLI dispatch in the Rust binary.
- Pure-Rust SWC parsing, AST normalization, import-specifier rewriting, and code
  emission.
- Browser harness emission and analysis/planner snapshot writing for the mock
  fixture path.
- Planner debug serialization aligned to the JS camelCase snapshot shape.
- Planner candidate generation in module-local semantic owner space.
- Ordered-init planner state merged from module-local state to match the JS
  fixture snapshot.
- Deterministic structural `estimatedSize` shared by JS and Rust.
- Tree-sitter removed from the Rust debundler implementation path.
- Rust target graph split into a shared `rust_library`, thin binary, and tests.
- Vendor annotation validation/storage for `mark_vendor` operations.
- Vendor boundary export rename over SWC AST import specifiers.
- Vendor swap resolution, package-version/subpath validation, vendor chunk
  removal, artifact manifest update, resolution manifest output, and wrapper
  generation for the covered wrapper shapes.
- Final `write_js_tree` output of JS files, root/chunk manifests, and module
  `package.json`.
- Initial logical module materialization in Rust using SWC AST operations for
  top-level declaration movement, module imports/exports, dependency closure,
  residual module output, and manifest metadata.
- Shared JS/Rust parity coverage for readable object-pattern default references
  after logical-module naturalization. The minimized `II -> constraint` hazard
  is now covered by `pipeline_stage_parity_test` and the JS guard avoids
  producing `constraint = constraint`.
- Phase-aware Rust access modeling for planner dependencies: eager/lazy reads,
  binding writes, and member writes now feed owner dependency edges.
- Staged-shell write-like reverse adjacency now matches JS, including lazy
  member writes from nested functions.
- JS staged-shell batch plans now preserve `seedComponentDepOwnerIds`, so the
  parity harness compares the same planner diagnostic payload on both sides.
- The reduced `seen`/`__vitePreload` reproducer is now a strict parity test,
  not an expected-divergence test.

Focused parity tests last known passing:

- `//devinfra/js/debundle/harness:pipeline_stage_parity_test`
- `//devinfra/js/debundle/harness:planner_internal_parity_test`
- `//devinfra/js/debundle/harness:planner_internal_tiny_repro_test`
- `//devinfra/js/debundle/harness:planner_parity_test`
- `//devinfra/js/debundle/harness:ordered_init_parity_test`
- `//devinfra/js/debundle/rust:pipeline_test`
- `//devinfra/js/debundle/harness:pipeline_e2e_test`
- `//devinfra/js/debundle/harness:pipeline_impl_golden_test`
- `//devinfra/js/debundle/harness:pipeline_impl_analysis_parity_fixture_test`
- `//devinfra/js/debundle/harness:analysis_parity_test`
- `//devinfra/js/debundle/harness:rust_e2e_test`

The newest parity target covers JS-binary vs Rust-binary execution for:

- vendor boundary rename through `write_js_tree`
- vendor swap resolution and chunk removal
- logical module materialization through `write_js_tree`
- object-pattern default-reference preservation after readable naturalization

## Remaining Divergences And Risks

### Full Stage Coverage

The Rust dispatcher still does not cover every JavaScript stage. Known missing
stage coverage:

- `extract_scrambled_identifier_frequencies`

Any new JS stage added to `transforms/runner.mjs` must be mirrored in Rust before
claiming full registry parity.

### Logical Module Materialization

Rust has an AST-backed `materialize_logical_modules` stage now, but it is not yet
a full deep port of the JavaScript `materializeLogicalModules` pipeline.

Known gaps:

- Rust does not yet port the full JS runtime boundary analysis data model.
- Rust does not yet port `planSelectedAtomicModules` and
  `buildLogicalModulePlans` exactly.
- Rust does not yet model owner fragments with JS parity.
- Rust does not yet implement the full selected owner cache semantics.
- Rust does not yet write boundary analysis cache files.
- Rust report content is structurally compatible for focused tests, but not
  byte-for-byte equivalent to JS reports.
- Rust lowering currently covers top-level function/class/variable declaration
  movement and simple dependency closure, not the full JS lowering matrix.
- The specific readable/default-reference TDZ hazard is covered and fixed in
  the JS implementation, with Rust parity asserted through the public binary
  test. Broader JS readable binding placement, destructuring naturalization,
  binding placement reports, attached side effects, and staged-shell edge cases
  still need broader parity work.

This is the largest remaining parity risk.

### Vendor Swap

Vendor swap is implemented for the covered direct-export and wrapper scenarios,
but not all error surfaces are exact yet.

Known gaps:

- Rust uses AST construction for `named-from-default`; JS currently verifies via
  AST but generates that wrapper by slicing source text after `export default `.
  Rust intentionally does not copy that text hack.
- Rust may accept some `named-from-default` upstream formatting that JS rejects
  because JS requires the source to start with the literal prefix
  `export default `.
- Rust currently rejects anonymous default function/class declarations in the
  `named-from-module-default` wrapper path. JS attempts to lower more cases.
- Wrapper emitted formatting comes from SWC, not Babel, so tests should compare
  behavior/structure rather than raw formatting unless a normalizer is used.

### Analysis Semantics

The Rust analysis matches focused fixtures better than the original rewrite, but
deep structural parity still needs broader validation for:

- owner/member discovery
- top-level side-effect classification
- eager vs lazy reads and writes
- member writes
- class fields, static blocks, computed keys, and nested function bodies
- import/export edge cases
- replayable side-effect attachment

### Emitted Runtime Behavior

The AST rewrite path is real, not text-based, and focused e2e tests pass. That
does not prove browser-visible parity over arbitrary real bundles. The golden
tests must continue comparing meaningful emitted JS, manifests, and runtime
behavior, not only shell files.

### Generality Beyond The Fixture

The current passing surface is still centered on small synthetic fixtures, the
mock browser bundle, and planner parity snapshots. It does not prove correctness
for large vendor-heavy graphs, unusual dynamic import forms, complex side-effect
ordering, or HTML/runtime asset layouts outside the current corpus.

## Validation Notes

The latest focused checks were run with local `bazelisk` using an output base in
`/tmp`:

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

Result: pass.

Final compile check:

```bash
bazelisk --output_user_root=/tmp/bazel-user-ducktape-rust \
  --output_base=/tmp/bazel-ducktape-rust-debundle \
  build //devinfra/js/debundle/rust:debundle_rust --config=nolint
```

Result: pass.

Before representing the Rust port as conformant, run the broader focused
debundler suite:

```bash
bbr test //devinfra/js/debundle/rust:pipeline_test
bbr test //devinfra/js/debundle/harness:pipeline_stage_parity_test
bbr test //devinfra/js/debundle/harness:pipeline_e2e_test
bbr test //devinfra/js/debundle/harness:pipeline_impl_golden_test
bbr test //devinfra/js/debundle/harness:pipeline_impl_analysis_parity_fixture_test
bbr test //devinfra/js/debundle/harness:analysis_parity_test
bbr test //devinfra/js/debundle/harness:planner_internal_parity_test
bbr test //devinfra/js/debundle/harness:planner_parity_test
bbr test //devinfra/js/debundle/harness:ordered_init_parity_test
bbr test //devinfra/js/debundle/harness:rust_e2e_test
```

Then run the repo-required handoff checks if this becomes more than a WIP
checkpoint:

```bash
bbr build //...
bbr test //...
```
