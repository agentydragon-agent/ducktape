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
- CLI tooling (top-level `debundle modules propose` / `atoms` /
  `coverage` / `describe` / `show-source` / `scc` / `cluster` /
  `graph-summary` — the legacy `debundle peel <…>` spellings still
  work as deprecated aliases);
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

| File                               | Field carrying binding identity                                                                              |
| ---------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| `owner_graph.json`                 | `nodes[].declared_bindings[].binding: Atom`, `edges[].binding: Option<Atom>`                                 |
| `cycles.json`                      | `evidence[].binding: Option<Atom>`, `evidence[].from_binding: Option<Atom>`, `cut[].{binding, from_binding}` |
| `atomic_unit_conflicts.json`       | `claims[].binding_names: Vec<Atom>`                                                                          |
| `chunk_analysis/atomic_units.json` | members are `OwnerId` integers, not `Id`s — no `Atom` and no `SyntaxContext`                                 |
| `chunk_analysis/manifest.json`     | no binding identities                                                                                        |

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
the time we serialize them, the `ctxt` is _redundant_ — it's the same
for every binding in the file — so dropping it loses no information.

A consumer reconstructing an `Id` from `Atom` does:

```rust
top_level_id(name, fresh_top_level_mark)
```

i.e. pairs the name with whatever `top_level_mark` the consumer's own
resolver assigned to the chunk. This works because both sides agree
that _every name in this file is a chunk-top-level binding_ — the
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
_every_ `Ident::to_id()` the visitor encounters, including reads
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
are silently dropped. The filter happens _between_ `facts.json` and
`owner_graph.json`.

### Why "drop ctxt, reconstruct via top_level_id" is unsound for facts.json

If `facts.json` were Atom-only and a consumer reconstructed `Id`s
via `top_level_id(name, fresh_mark)`, **shadowing produces false
positives**. Worked example:

```js
const counter = 0; // top-level binding (top_level_ctxt)
function increment() {
  let counter = 1; // inner binding (inner_ctxt)
  return counter; // lazy_read records (counter, inner_ctxt)
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

## Cross-process scope: not a goal

Earlier drafts of `PIPELINE_SPLIT.md` and `ARCH_REVIEW_2026_05.md`
treated cross-process Stage B (a separate Bazel action consuming
Stage A's cached output for the materializer) as the load-bearing
motivation for the Stage A on-disk artifact. **It is no longer.**

The reasoning: every realistic Stage B reader either (a) doesn't
need `facts.json` (the query-CLI surface — see "Reader audiences"
below — reads only the Atom-only files and is already cross-process
safe today) or (b) needs the full SWC AST + hygiene state (the
materializer lowering pass), which requires either re-parsing or a
SWC-internal hygiene snapshot replay (substantially more
implementation surface than the cache is worth at gaffer scale).

So the design splits into two scopes:

- The **query surface** (top-level `scc`, `atoms`, `coverage`,
  `graph-summary`, `describe`, `show-source`, `cluster`, `modules
  propose`) reads the existing Atom-only files. Already works
  cross-process; the surface is the working proof. No `SyntaxContext`
  ever leaves a process boundary.
- The **materializer** stays in-process. Editing a spec re-runs the
  full pipeline (parse → facts → owner_graph → assemble → validate →
  lower). At gaffer scale that's ~5–10s; most of it is parse, which
  Bazel can cache at coarser granularity if it ever becomes a hot
  spot.
- `facts.json` stays as an **in-process debug artifact** — humans
  inspecting it during a materializer run, CLI tools that share the
  same `Globals` (none today). **Not** for separate-process consumers.

If a future use case ever demands a cross-process materializer
reader, the structurally honest path is a SWC hygiene replay
snapshot (serialize the sequence of `Mark::fresh(parent)` and
`apply_mark(prev, mark)` ops, replay them in Stage B's fresh
`Globals` before deserializing any `Id`s). That requires no fork of
swc_common — `Mark::parent()`, `SyntaxContext::outer()`,
`SyntaxContext::remove_mark()` are all public — but it's substantial
implementation. Defer until there's a concrete use case that
justifies it.

The alternatives that came up in earlier drafts are documented as
rejected:

- **Drop ctxt, reconstruct via `top_level_id`**: **unsound** on
  shadowing — produces spurious at-init edges when a closure-local
  shadows a top-level binding name. See the `let counter = 1`
  worked example above.
- **Pre-filter `facts.json`** (drop inner-scope Ids before
  serialization): would keep the Atom-only convention pure but lose
  the closure-local read records humans inspecting the artifact may
  want. Not worth the loss when nothing else needs the change.
- **Rely on SWC resolver determinism + re-parse in Stage B**: Stage
  A's cache becomes value-less to Stage B (Stage B re-parses,
  re-runs `analyze_chunk`, throws away the cached facts). At that
  point Stage A cache only proves "did Stage A succeed", which is
  not why we'd build it.

For the empirical demonstration that the cross-process round-trip
breaks under non-trivial `Globals` state, see
`ARCH_REVIEW_2026_05.md` §"Pipeline-split risks" — the
two-`Globals` test where Stage A produces `SyntaxContext(1)` and a
prior-`apply_mark`-warmed Stage B produces `SyntaxContext(2)` for
the same conceptual binding.

## Reader audiences

| Consumer                                                                                                              | Reads                                                           | Cross-process?          |
| --------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------- | ----------------------- |
| Spec author with `jq`                                                                                                 | `owner_graph.json`, `cycles.json`, `atomic_unit_conflicts.json` | yes (Atom-only)         |
| `debundle atoms` / `coverage` / `graph-summary` / `scc` / `cluster` / `describe` / `show-source` / `modules propose`  | `owner_graph.json`, `atomic_units.json`, source bytes + spec    | yes (Atom-only)         |
| `debundle bindings assign` / `bindings rename` / `modules merge`                                                      | spec YAMLs + `owner_graph.json` (gate)                          | yes                     |
| Debugging human inspecting `facts.json`                                                                               | `facts.json`                                                    | NO — same-process only  |
| Materializer (`debundle run`)                                                                                         | spec + chunk bytes + everything in-process                      | N/A — always in-process |

## Status of related tasks

- ~~Task #78 (`materialize_from_analysis` read-from-disk entry
  point)~~ — **dropped**. The use case it served (cross-process
  Stage B for the materializer) is no longer a goal. The cache
  value users will actually feel comes from the query CLIs, not
  from caching Stage B's inputs.
- ~~Task #79 (Wire format redesign: drop SyntaxContext)~~ —
  **dropped**. The redesign was a prerequisite for #78; with #78
  dropped, the `IdReport { name, ctxt: u32 }` shape stays as the
  debug-only artifact format it is today.
- New work tracked as separate tasks: `binding describe`,
  top-level `scc`, `cluster`, `binding show-code` — all readers of
  the existing Atom-only artifacts.

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
