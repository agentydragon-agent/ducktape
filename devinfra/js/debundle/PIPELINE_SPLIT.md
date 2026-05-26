# Pipeline-split proposal

## Motivation

Today the per-chunk debundle pipeline is monolithic: `materialize_logical_chunk` does parse → facts → owner_graph → atomic_units → assemble_partition → validate → lower in one shot. Editing a single line in the spec re-parses 5 MB of minified JS.

Splitting the pipeline at the owner-graph boundary unlocks:

- **Cache-friendly Stage A.** Owner graph is a function of `(chunk_bytes, ducktape_version, OwnerGraphOptions)`. Cache key independent of spec. Re-running with a new spec hits the cache.
- **Independent CLI consumers.** `peel scc`, `peel units`, `peel patch-plan`, `binding describe`, `cluster`, and the planned `module merge` (task #73) all conceptually want Stage A as input. They currently re-run the whole pipeline; with the split they could load a cached artifact.
- **Faster planning iteration.** Tools like `peel plan-work` re-derive recommendations from owner graph + spec. With a stable on-disk Stage A artifact, a planner run becomes "read artifact + apply spec + propose."
- **Cleaner test fixtures.** Stage B tests can use a hand-authored owner graph instead of round-tripping through SWC.

## Stage boundary

```
Stage A  (spec-independent; pure function of source bytes + ducktape version)
─────────────────────────────────────────────────────────────────────────────
parse chunk                       (chunk_ast.rs)
analyze per-statement facts       (chunk_analysis.rs)
build owner graph                 (graph::build_owner_graph_with)
compute atomic units              (atomic_units::compute_atomic_units)
emit chunk_analysis.<fmt>         + manifest

Stage B  (spec-dependent; takes Stage A artifact as input)
─────────────────────────────────────────────────────────────────────────────
load chunk_analysis.<fmt>
apply spec → claims               (factor_assembly::compute_owner_claims)
assemble_partition                (factor_assembly.rs)
  → AtomicUnitConflict?           bail with structural-atom blame
build module quotient             (graph::build_module_quotient)
check_realizability               (realizability.rs)
  → unrealizable SCC?             bail with binding-pair blame (now done)
lower_chunk                       (lowering/lower.rs)
emit JS                           + reports
```

The exact cut: `OwnerGraphAndUnits` is what Stage A emits and Stage B consumes. It carries everything Stage B needs:

- `OwnerGraph` (nodes, edges, statement_ordinal → owner mapping)
- `Vec<AtomicUnit>` (precomputed structural atoms)
- Per-owner anonymous-statement ordinals (needed for `compute_owner_claims`)
- Chunk metadata (chunk_id, module_path, ChunkAnalysisOptions echo for verification)

Stage B re-parses for the SWC AST. The AST is intentionally not serialized in v1; see §"What about the AST?" below.

## What to do for the artifact format

The choices boil down to: **JSON pretty + indexed**, **JSON compact + accompanying index**, or **protobuf with a query CLI**. There's also a hybrid worth considering.

### Option 1: JSON pretty (status quo, expanded)

Today `owner_graph.json` is JSON-pretty, ~3 MB for gaffer. Easy to `jq`, easy to read in editors, easy to diff.

| Pros                         | Cons                                                                |
| ---------------------------- | ------------------------------------------------------------------- |
| `jq` works out of the box    | Large on disk; bazel action cache footprint matters at gaffer scale |
| Human-readable diffs         | Re-parsing 3 MB JSON takes ~100ms; not free                         |
| No schema migration ceremony | No schema enforcement; field renames silently break consumers       |
| One-tool inspection          | Hard to load partial slices                                         |

This works fine and is the lowest-friction option. The marginal cost over what we already write is small.

### Option 2: JSON-Lines + sidecar index

Same content, NDJSON instead of one big array. Each line is `{type: "node"|"edge"|"unit", ...}`. A small `index.json` lists byte offsets per chunk_id / per section.

| Pros                                       | Cons                                   |
| ------------------------------------------ | -------------------------------------- |
| Streaming consumers can read incrementally | Still text; size similar to status quo |
| Random access via offset index             | Custom-built; not a real format        |
| `jq -c` still works per line               | Adds a second file to manage           |

Probably not worth the index machinery vs Option 1.

### Option 3: protobuf

Define a `chunk_analysis.proto` mirroring `OwnerGraphAndUnits`. Emit `chunk_analysis.pb` per chunk.

| Pros                                                 | Cons                                            |
| ---------------------------------------------------- | ----------------------------------------------- |
| Compact: 3-5× smaller than JSON pretty               | Binary; `cat` / `grep` no longer work           |
| Versioned schema; field changes are explicit         | Querying requires a dedicated tool              |
| Fast load (zero-copy with `prost` + `bytes`)         | Cross-language consumers need the same `.proto` |
| Existing rules_rust_prost + protobuf in MODULE.bazel | Build complexity (gen code, deps)               |

To preserve queryability, ship a tiny `debundle inspect` CLI:

```
debundle inspect <chunk_analysis.pb> owners --json     # dump as JSON
debundle inspect <chunk_analysis.pb> binding XOe       # find a binding
debundle inspect <chunk_analysis.pb> scc --residual    # SCC listing
```

The `--json` mode means anything `jq` can do today still works; it's one extra `debundle inspect … --json | jq` step. The default mode is structured TSV / table output, easier to scan than indented JSON for large graphs.

### Option 4: hybrid — protobuf primary, JSON debug sidecar

Stage A always writes `chunk_analysis.pb` (consumed by Stage B and tools). When `--debug` is set, it also writes `chunk_analysis.json` (or `owner_graph.json` per the existing report layout) for human inspection. CI doesn't pay for both.

This is what I'd recommend if the proto cost feels worth it. If the goal is mostly "share the parse+graph work across pipeline + CLIs without paying a second time," the marginal benefit of proto over JSON for that use is mostly load speed and schema discipline, not querying.

### Recommendation

**Start with Option 1 (JSON pretty).** The infrastructure to write/read it already exists (we write `owner_graph.json` today). Move `OwnerGraphAndUnits` into a stable JSON schema with a version field. Land the pipeline split, get the cache wins, validate the consumers all work with cached Stage A.

**Then revisit** with measurement. If load-time of the JSON becomes a hot spot in `peel`-family tools, or if the action-cache footprint balloons, migrate to Option 4 (proto primary + JSON debug). The migration is a clean swap inside `lib.rs`'s artifact-load helper; consumers don't change.

The thing I'd _not_ do is jump directly to proto. The format isn't broken — JSON has been serving us. The bottleneck is "we re-do Stage A every time," not "JSON is too slow." Fix the bottleneck first; reformat second if measurement says it's worth it.

## What about the AST?

Stage B's lowering pass needs the SWC AST to emit JS. **Decision: Stage B re-parses.** Option 1.

The originally-considered "serialize the SWC AST in Stage A" path is structurally blocked by SWC's hygiene model. `Id = (Atom, SyntaxContext)` carries a `SyntaxContext` index that is meaningful only within one SWC `Globals` instance. A separate-process Stage B would see deserialized `SyntaxContext` values that point at entries in _its own_ intern table — which were created by its own `apply_mark` calls — and the freshly-resolved `top_level_id` would not agree with the wire-loaded one. See `ARCH_REVIEW_2026_05.md` §"Pipeline-split risks" for the empirical demonstration and `stage_one_sidecars.rs` for the corresponding scope decision.

The implications:

- v1 Stage A sidecars (in `stage_one_sidecars.rs`) write `facts.json`, `atomic_units.json`, and `manifest.json`. They do **not** write `ast.json`.
- v1 sidecars are designed for **in-process inspection** (CLI tooling, human debugging) within the same materializer run that produced them, where the `Globals` is shared.
- **A separate-process materializer reader is out of scope.** Earlier drafts framed `materialize_from_analysis` as the natural next step; on closer analysis (see `WIRE_FORMAT.md`), the cache value it would deliver doesn't justify the SWC hygiene surgery required to make `Id` portable. The materializer stays in-process. See "Scope cut" below.

## Scope cut: no cross-process materializer

The original framing was "Stage A produces a cacheable artifact;
Stage B reads it as a separate Bazel action; spec edits hit only
Stage B." That part of the plan is **abandoned**.

Reason: cross-process `Id` portability is structurally hard — the
honest path is a SWC hygiene-snapshot replay (serialize the sequence
of `Mark::fresh(parent)` + `apply_mark(prev, mark)` ops, replay them
in Stage B's fresh `Globals` before deserializing any `Id`s). That
path is real (`Mark::parent()`, `SyntaxContext::outer()`,
`SyntaxContext::remove_mark()` are all public; no swc_common fork
required) but it's a non-trivial implementation, and the cache
value it delivers (~5–10s saved on gaffer-scale spec edits) doesn't
justify it. The materializer stays in-process. Bazel-level caching
at the rule's coarser granularity covers the same ground without
the surgery.

The cache value users will actually feel comes from a **different**
direction: a rich query-CLI surface that operates on the existing
Atom-only JSON reports (`owner_graph.json`, `atomic_units.json`,
`cycles.json`, `atomic_unit_conflicts.json`). That surface is
already cross-process safe today (the `peel` family proves it),
and the next step is building out `binding describe`, top-level
`scc`, `cluster`, `binding show-code` as readers of those files.

See `WIRE_FORMAT.md` §"Cross-process scope: not a goal" for the
full reasoning and the rejected-alternatives list.

## Implementation sequencing (revised)

In flight / done:

1. **`chunk_analysis/{facts.json, atomic_units.json, manifest.json}` writers** — landed (`stage_one_sidecars.rs`).
2. **`facts.json` is debug-only**: human inspection, same-process tooling. Documented in `WIRE_FORMAT.md`.
3. **Query CLIs build on the existing Atom-only reports**, not on a cross-process Stage A artifact.

Followups (separate tasks):

- `binding describe <symbol>` — reads `owner_graph.json` + spec.
- Top-level `debundle scc` — surfaces the same data as `peel scc` from the CLI's top level.
- `cluster <binding>` — quotient neighbors.
- `binding show-code <symbol>` — reads source bytes + source locations from `owner_graph.json`.
- `module merge --validate` — wires the realizability gate into the existing splice path.

The Bazel rule split into separate analyze + materialize actions is **not** on this roadmap; the materializer stays as one action.

## Resolved decisions

- **JSON first**: per-concept JSON files (the `chunk_analysis/` directory). Revisit proto only if measurement says JSON load-time is a hot spot.
- **No AST serde**: AST is not serialized. `swc_ecma_ast/serde-impl` is enabled in MODULE.bazel as plumbing but currently unused.
- **`facts.json` is debug-only**: see `WIRE_FORMAT.md` §"Cross-process scope: not a goal". The `IdReport { name, ctxt: u32 }` shape is correct for same-process consumers and is the only sound option (Atom-only would be unsound under closure shadowing).
- **Materializer stays in-process**: no `materialize_from_analysis` reader, no Bazel rule split, no cross-process Stage B.
- **Full per-statement facts** in `facts.json`: `ChunkFactsReport` carries everything `analyze_chunk` produces. Useful for debug inspection.
