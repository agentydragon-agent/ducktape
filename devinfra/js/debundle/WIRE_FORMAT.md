# Wire format conventions (per-chunk JSON sidecars)

Verified at HEAD `ecef8acf5` (integration of `feat-facts-wire-format`,
`drop-ast-sidecar`, etc. into `devel`). Section "Open: cross-process
Stage A artifact" tracks a known unresolved question and the empirical
work needed to settle it.

## What this doc covers

The per-chunk JSON files debundle writes under
`reports/tree/<chunk_id>/` (and the new `chunk_analysis/` subdirectory)
are consumed by:

- spec authors with `jq` poking at cycle / owner-graph / atomic-unit reports;
- CLI tooling (`debundle peel`, future `binding describe` / `scc` /
  `cluster` / etc.);
- a planned cross-process Stage B reader (`materialize_from_analysis`,
  task #78) that re-runs the materializer from a cached Stage A
  artifact;
- humans reading the files during debugging.

This doc states the convention these files follow, **and the one
exception** (`facts.json`) that breaks the convention.

## Convention: `Atom`-only on the wire

Every JSON file in the existing report set carries binding identities
as `Atom`s (interned strings), **not** as SWC `Id = (Atom,
SyntaxContext)`. The `SyntaxContext` half is dropped at serialization.

Files following the convention:

| File | Field carrying binding identity |
|---|---|
| `owner_graph.json` | `nodes[].declared_bindings[].binding: Atom`, `edges[].binding: Option<Atom>` |
| `cycles.json` | `evidence[].binding: Option<Atom>`, `evidence[].from_binding: Option<Atom>`, `cut[].{binding, from_binding}` |
| `atomic_unit_conflicts.json` | `claims[].binding_names: Vec<Atom>` |
| `chunk_analysis/atomic_units.json` | members are `OwnerId` integers, not `Id`s — no `Atom` and no `SyntaxContext` |
| `chunk_analysis/manifest.json` | no binding identities |

`Atom` serializes as a plain JSON string via `swc_atoms`'s own
`Serialize` impl. That impl writes the **string content** — interned
in memory, but the wire form is the string itself, which is portable.

### Why the convention works for these files

These files all carry **post-filter** data — data that has already
passed through `binding_owner.get(binding)` at `graph.rs:598`. That
lookup is keyed by the full `Id`. Anything whose `SyntaxContext` does
not match a chunk-top-level binding (closure-local reads with inner-
scope marks, globals with `SyntaxContext::empty()`, etc.) **misses the
lookup and never becomes an edge**.

Consequence: the only `Id`s that survive into the owner graph have
`ctxt = top_level_mark.apply_to(empty)`, i.e. they're the chunk-top-
level bindings the resolver assigned that single shared context to. By
the time we serialize them, the `ctxt` is *redundant* — it's the same
for every binding in the file — so dropping it loses no information.

A consumer reconstructing an `Id` from `Atom` does:

```rust
top_level_id(name, fresh_top_level_mark)
```

i.e. pairs the name with whatever `top_level_mark` the consumer's own
resolver assigned to the chunk. This works because both sides agree
that *every name in this file is a chunk-top-level binding* — the
ctxt is determined by that role, not by the wire data.

## The exception: `facts.json` carries `SyntaxContext`

`facts.json` (the `ChunkFactsReport` written by Stage A, see
`facts/wire.rs`) is the one file in the set that breaks the convention.
It serializes binding identities as `IdReport { name: Atom, ctxt: u32 }`
across every `StatementFactsReport` field
(`declared`, `eager_reads`, `lazy_reads`, `eager_rebinds`,
`lazy_rebinds`, `first_order_lazy_reads`, `first_order_lazy_rebinds`,
`local_effects`, `at_init_calls`, `body_calls`,
`first_order_body_calls`, and `effects.{reads, writes}` via
`EffectCellReport`).

### Why facts.json is different

`StatementFacts` is **pre-filter** raw analyzer output.
`StatementFactsCollector::visit_ident` (`facts/mod.rs:900`) records
*every* `Ident::to_id()` the visitor encounters, including reads
inside nested function bodies (the visitor descends into them via
`lazy_visit_function` / `lazy_visit_arrow_expr` / etc., bumping
`lazy_depth` but not skipping the subtree).

Closure-local declarations have **inner-scope marks** assigned by
the resolver, not the chunk's `top_level_mark`. So
`StatementFacts.lazy_reads` for a top-level statement that contains a
nested function will include `Id`s with inner-scope contexts
alongside chunk-top-level reads and globals (`SyntaxContext::empty()`).

The downstream owner-graph build at `graph.rs:608` walks these and
looks each one up in `binding_owner`. Inner-scope `Id`s miss the
lookup (their `ctxt` doesn't match any chunk-top-level binding) and
are silently dropped. The filter happens *between* `facts.json` and
`owner_graph.json`.

### Why "drop ctxt, reconstruct via top_level_id" is unsound for facts.json

If `facts.json` were Atom-only and a consumer reconstructed `Id`s
via `top_level_id(name, fresh_mark)`, **shadowing produces false
positives**. Worked example:

```js
const counter = 0;                  // top-level binding (top_level_ctxt)
function increment() {
  let counter = 1;                  // inner binding (inner_ctxt)
  return counter;                   // lazy_read records (counter, inner_ctxt)
}
```

`StatementFactsCollector` for the `function increment` statement
records `lazy_reads = {("counter", inner_ctxt)}`. The owner-graph
build looks up `("counter", inner_ctxt)` in `binding_owner` → not
there (only `("counter", top_level_ctxt)` is keyed) → no edge. **No
false positive at runtime.**

But if the wire format dropped the ctxt: deserialize `name="counter"`,
reconstruct as `top_level_id("counter", mark_b) = ("counter",
top_level_ctxt)`, look up in `binding_owner` → **hits** the top-level
`counter`, emits a spurious `LazyUse` edge from `increment`'s
statement to the top-level `counter`. The realizability gate would
then see at-init/lazy edges that aren't actually there.

So the simple "drop ctxt" approach **is the hacky one**: it'd be
sound only under the assumption that no closure ever shadows a
chunk-top-level binding name — an assumption we cannot verify
statically and that real JS bundles violate (e.g. `function init({
state }) { state.foo }` shadows a top-level `state` symbol all the
time).

`facts.json` carries `IdReport` precisely so the owner-graph build
can do its `SyntaxContext`-aware filter correctly downstream.

## Open: cross-process Stage A artifact

The cost: `IdReport.ctxt` is a `u32` that's only meaningful within
the SWC `Globals` instance that allocated it (per
`swc_common::syntax_pos::hygiene::apply_mark_internal` — interns
`(prev_ctxt, mark)` into a `Vec<SyntaxContextData>` and returns
`SyntaxContext(vec.len())`). Across processes, the indices align only
if both `Globals` allocated marks in exactly the same order.

Empirical demonstration (test on branch `test-id-cross-globals`, now
discarded but reproducible from `ARCH_REVIEW_2026_05.md` §"Pipeline-
split risks"):

```rust
// Globals A, fresh:    Mark::new() → mark_a (#1); top_level_id("foo", mark_a) → ctxt=#1
// Globals B, fresh:    Mark::new() → mark_b (#1); top_level_id("foo", mark_b) → ctxt=#1
//   → ctxts agree (both at SyntaxContext(1)).
// Globals B', primed with one apply_mark before mark_b:
//                       intern table is non-empty; top_level_id("foo", new_mark) → ctxt=#2
//   → ctxts disagree (#1 from A, #2 from B').
```

So whether `facts.json` is cross-process-portable reduces to whether
the SWC resolver is *deterministic enough* that a Stage B process,
starting from a fresh `Globals` with no prior `apply_mark` activity
and running the same resolver on the same chunk in the same SWC
version, produces an intern table identical to Stage A's.

### Conditions for cross-process portability

If Stage B honors these contracts, the `IdReport.ctxt` u32 in
`facts.json` deserializes into an `Id` that compares equal to the
`Id`s Stage B's own resolver pass produces, and `binding_owner`
lookups succeed:

1. **Fresh `Globals` per chunk.** Stage B opens a new
   `swc_common::Globals` for each chunk it materializes. It runs
   `GLOBALS.set(&globals, …)` once, around all chunk-related work,
   without sharing or reusing the `Globals` across chunks.

2. **No prior `apply_mark` / `Mark::new` calls.** Stage B does not
   resolve any other AST, allocate any marks, or apply any marks
   *before* re-parsing and re-resolving the chunk under study. In
   particular: no shared resolver workspace, no warm-up pass.

3. **Same SWC version, same chunk source bytes.** The resolver
   algorithm and its visit order must match what Stage A used. Cache
   key for the Stage A artifact must include the ducktape (and
   thereby SWC) version.

4. **The resolver's per-Globals state is deterministic.** This is the
   open one. SWC's resolver is a sequential `Visit` over the AST;
   `Mark::new()` is a counter, `apply_mark` interns into a `Vec` in
   call order. None of this is overtly nondeterministic. But the
   resolver is implemented in `swc_ecma_transforms_base::resolver`
   and could in principle introduce thread-local randomness,
   parallelism, or HashMap iteration order in some future version.
   We haven't pinned a regression test that catches such a change.

### What needs to land before relying on this

Before building `materialize_from_analysis` (task #78) — the
cross-process Stage B reader — on top of the current wire format:

1. **A determinism regression test.** Round-trip an `Id` through
   `facts.json` across two fresh `Globals` (in the same process, sequenced)
   and assert equality. Repeat across a non-trivial fixture (every
   `StatementFacts` field, every `IdReport`-bearing position, both the
   chunk-top-level case and the shadowed-closure-local case described
   above). If this passes, point future readers at the test as the
   load-bearing contract.

2. **A doc-comment in `facts/wire.rs`** stating the four conditions
   above as the Stage B reader's contract.

3. **A `swc` version pin** in the Stage A manifest. The current
   `manifest.json` already carries `schema_version`; add a
   `swc_ecma_ast_version` (or `ducktape_version`) field so a reader
   refusing to honor it fails fast rather than silently corrupting.

If the determinism test fails (or proves too brittle to commit to), the
alternatives are:

- **Pre-filter facts.json**: drop any `Id` from `StatementFacts`
  whose ctxt isn't in `{empty, top_level_ctxt}` before serialization.
  Then the Atom-only convention applies, downstream sees no semantic
  difference (owner-graph build already drops these), and the wire
  format becomes portable. **Cost**: facts.json stops being a faithful
  mirror of `StatementFacts` — closure-local reads silently disappear.
  Inspection tooling that wants closure-local detail (does any exist?)
  would need a separate raw artifact.

- **Don't put facts.json on the cross-process path**: keep it as an
  in-process inspection artifact (CLI tooling, debugging humans),
  have cross-process Stage B re-run `analyze_chunk` from its own
  re-parsed AST. Parsing is cheap (~1-2s for the gaffer chunk);
  re-running analyze_chunk on a parsed module is cheaper still. Stage
  A's cacheable value shrinks accordingly.

The right choice depends on what value Stage B actually extracts from
a cached `facts.json`. If it's only the structural conclusions
(atomic units, owner graph), Stage A's cache could omit the facts
entirely. If Stage B uses facts.json to skip `analyze_chunk` itself,
the determinism path is the only one that preserves that benefit.

## Reconstruction recipe (current state)

For files that already use the Atom-only convention, a reader does:

```rust
let mark_b = /* the chunk's top_level_mark, set by the reader's own resolver pass */;
let global = (atom_from_wire, SyntaxContext::empty());
let top_level = top_level_id(atom_from_wire, mark_b);
```

For `facts.json`, today, a reader does:

```rust
let id = report.to_id();   // (report.name, SyntaxContext::from_u32(report.ctxt))
```

— and trusts the four-condition contract above. Until the
determinism test lands, this is **not** a contract that has been
verified to hold; treat it as best-effort and prefer in-process
consumption.

## Related documents

- `DESIGN.md` §"Two classes of atom" — the realizability theorem
  these wire formats serialize evidence for.
- `PIPELINE_SPLIT.md` — the broader design of the Stage A / Stage B
  split this wire-format work supports.
- `ARCH_REVIEW_2026_05.md` §"Pipeline-split risks" — the original
  flag of the cross-process problem.
