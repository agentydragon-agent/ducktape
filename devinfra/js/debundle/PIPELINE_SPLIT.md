# Pipeline-split residuals

The original Stage A / Stage B split proposal has largely landed. This
doc tracks the **residual** concerns — things left open after the
basic split shipped. For the live correctness backlog (`Id`
round-trip, in-process side effects) see
`ARCH_REVIEW_2026_05.md` §"Pipeline-split residuals".

## What landed

The pieces motivating the original split are all in place:

- **Stage A composer** (`stage_one.rs::compute_stage_one_analysis`):
  a clean composer that runs parse + facts + owner_graph +
  atomic_units, with explicit input/output types.
- **Stage A sidecars** (`stage_one_sidecars.rs`): per-concept JSON
  files written under `reports/tree/<chunk_id>/chunk_analysis/`:
  `facts.json`, `atomic_units.json`, `manifest.json`. No `ast.json`
  — see §"AST: not serialized" below.
- **`StatementFacts` wire-format serialization** (`facts/wire.rs`):
  `IdReport { name: Atom, ctxt: u32 }` for every binding identity,
  serialized via standard serde. `facts_round_trip_unit` covers
  same-process round-trip.
- **`swc_ecma_ast` serde**: `MODULE.bazel` enables
  `swc_ecma_ast/serde-impl` so the AST type tree is `Serialize +
  Deserialize`. **Currently unused** — see §"AST: not serialized".

## Stage boundary (recap)

```
Stage A  (spec-independent; pure function of source bytes + ducktape version)
─────────────────────────────────────────────────────────────────────────────
parse chunk                       (chunk_ast.rs)
analyze per-statement facts       (chunk_analysis.rs)
build owner graph                 (graph::build_owner_graph_with)
compute atomic units              (atomic_units::compute_atomic_units)
emit chunk_analysis/*.json        + manifest

Stage B  (spec-dependent; takes Stage A artifact as input)
─────────────────────────────────────────────────────────────────────────────
load chunk_analysis/*.json
apply spec → claims               (factor_assembly::compute_owner_claims)
assemble_partition                (factor_assembly.rs)
build module quotient             (graph::build_module_quotient)
check_realizability               (realizability.rs)
lower_chunk                       (lowering/lower.rs)
emit JS                           + reports
```

`OwnerGraphAndUnits` is the typed cut. Stage B re-parses to obtain the
SWC AST for the lowering pass; serializing the AST is not on the
roadmap (see below).

## AST: not serialized

Stage B's lowering pass needs the SWC AST to emit JS. Stage B
**re-parses** rather than reading a serialized AST.

The originally-considered "serialize the SWC AST in Stage A" path is
structurally blocked by SWC's hygiene model. `Id = (Atom,
SyntaxContext)` carries a `SyntaxContext` index that is meaningful
only within one SWC `Globals` instance. A separate-process Stage B
would see deserialized `SyntaxContext` values that point at entries in
_its own_ intern table — created by its own `apply_mark` calls — and
the freshly-resolved `top_level_id` would not agree with the
wire-loaded one. See `ARCH_REVIEW_2026_05.md` §"Pipeline-split
residuals" for the empirical demonstration.

Consequence: v1 sidecars (`stage_one_sidecars.rs`) write `facts.json`,
`atomic_units.json`, `manifest.json`. They **do not** write
`ast.json`. `swc_ecma_ast/serde-impl` stays as plumbing.

## No cross-process materializer

The original framing was "Stage A produces a cacheable artifact; Stage
B reads it as a separate Bazel action; spec edits hit only Stage B."
**That part of the plan is abandoned.**

The honest path to cross-process Stage B is a SWC hygiene-snapshot
replay: serialize the sequence of `Mark::fresh(parent)` and
`apply_mark(prev, mark)` ops, replay them in Stage B's fresh
`Globals` before deserializing any `Id`s. That path is real
(`Mark::parent()`, `SyntaxContext::outer()`,
`SyntaxContext::remove_mark()` are all public; no swc_common fork
required) but it's a non-trivial implementation, and the cache
value it delivers (~5–10s saved on gaffer-scale spec edits) doesn't
justify it. The materializer stays in-process. Bazel-level caching
at the rule's coarser granularity covers the same ground without
the surgery.

The cache value users actually feel comes from a **different**
direction: a rich query-CLI surface that operates on the existing
Atom-only JSON reports (`owner_graph.json`, `atomic_units.json`,
`cycles.json`, `atomic_unit_conflicts.json`). That surface is already
cross-process safe today (the top-level `atoms` / `coverage` /
`describe` / `show-source` / `scc` / `cluster` / `modules propose`
commands prove it), and is the active development direction.

See `WIRE_FORMAT.md` §"Cross-process scope: not a goal" for the full
reasoning and the rejected-alternatives list.

## Open residuals

These are tracked here so they aren't lost; the live concerns are in
`ARCH_REVIEW_2026_05.md` §"Pipeline-split residuals".

### `Id` round-trip is `Globals`-bound

`facts/wire.rs::IdReport` serializes `(name: Atom, ctxt: u32)`. The
`u32` is the `SyntaxContext`'s internal index. **`SyntaxContext`
values are meaningful only within the same SWC `Globals` instance.**
The `facts_round_trip_unit` test covers same-process round-trip; the
**cross-`Globals`** test (parse → serialize → drop `Globals` →
re-parse in fresh `Globals` → deserialize → assert `top_level_id`
matches) does not exist. Until that test exists and passes,
cross-process Stage B is unsound.

Until then, `facts.json` is documented as an **in-process debug
artifact**: human inspection, CLI tools that share the same `Globals`
(none today). Not for separate-process consumers. See `WIRE_FORMAT.md`
for the convention.

### Stage A side effects still run in the materializer's process

The materializer pipeline runs everything inline in
`materialize_logical_chunk`, including side-effecting actions
(top-level-await `bail!`, redundant-hint stderr). When Stage A
becomes its own Bazel action, those side effects need to move out of
the materializer's process: produce a Stage A artifact + log warnings
as part of that action; the materializer loads the artifact and
doesn't re-emit. This is queued for `stage_one.rs` and is the next
step beyond the composer extraction.

### Stage A artifact size / format

The Stage A sidecars are JSON pretty today. If load-time of the JSON
becomes a hot spot in the query-CLI surface, or if the action-cache
footprint balloons, migrate to protobuf primary + JSON debug. The
migration is a clean swap inside the artifact-load helpers; consumers
don't change. **Not on the roadmap yet** — measurement-driven.

## Related documents

- `WIRE_FORMAT.md` — the on-the-wire convention for each per-chunk
  JSON sidecar and the cross-process scope rationale.
- `ARCH_REVIEW_2026_05.md` §"Pipeline-split residuals" — the live
  correctness backlog.
- `DESIGN.md` §"Two classes of atom" — the realizability theorem the
  wire formats serialize evidence for.
