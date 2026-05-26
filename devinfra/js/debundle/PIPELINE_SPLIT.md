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

| Pros | Cons |
|---|---|
| `jq` works out of the box | Large on disk; bazel action cache footprint matters at gaffer scale |
| Human-readable diffs | Re-parsing 3 MB JSON takes ~100ms; not free |
| No schema migration ceremony | No schema enforcement; field renames silently break consumers |
| One-tool inspection | Hard to load partial slices |

This works fine and is the lowest-friction option. The marginal cost over what we already write is small.

### Option 2: JSON-Lines + sidecar index

Same content, NDJSON instead of one big array. Each line is `{type: "node"|"edge"|"unit", ...}`. A small `index.json` lists byte offsets per chunk_id / per section.

| Pros | Cons |
|---|---|
| Streaming consumers can read incrementally | Still text; size similar to status quo |
| Random access via offset index | Custom-built; not a real format |
| `jq -c` still works per line | Adds a second file to manage |

Probably not worth the index machinery vs Option 1.

### Option 3: protobuf

Define a `chunk_analysis.proto` mirroring `OwnerGraphAndUnits`. Emit `chunk_analysis.pb` per chunk.

| Pros | Cons |
|---|---|
| Compact: 3-5× smaller than JSON pretty | Binary; `cat` / `grep` no longer work |
| Versioned schema; field changes are explicit | Querying requires a dedicated tool |
| Fast load (zero-copy with `prost` + `bytes`) | Cross-language consumers need the same `.proto` |
| Existing rules_rust_prost + protobuf in MODULE.bazel | Build complexity (gen code, deps) |

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

The thing I'd *not* do is jump directly to proto. The format isn't broken — JSON has been serving us. The bottleneck is "we re-do Stage A every time," not "JSON is too slow." Fix the bottleneck first; reformat second if measurement says it's worth it.

## What about the AST?

Stage B's lowering pass needs the SWC AST to emit JS. **Decision: Stage B re-parses.** Option 1.

The originally-considered "serialize the SWC AST in Stage A" path is structurally blocked by SWC's hygiene model. `Id = (Atom, SyntaxContext)` carries a `SyntaxContext` index that is meaningful only within one SWC `Globals` instance. A separate-process Stage B would see deserialized `SyntaxContext` values that point at entries in *its own* intern table — which were created by its own `apply_mark` calls — and the freshly-resolved `top_level_id` would not agree with the wire-loaded one. See `ARCH_REVIEW_2026_05.md` §"Pipeline-split risks" for the empirical demonstration and `stage_one_sidecars.rs` for the corresponding scope decision.

The implications:

- v1 Stage A sidecars (in `stage_one_sidecars.rs`) write `facts.json`, `atomic_units.json`, and `manifest.json`. They do **not** write `ast.json`. The `swc_ecma_ast/serde-impl` feature is enabled in MODULE.bazel and ready for a future redesign, but unused in v1.
- v1 sidecars are designed for **in-process inspection** (CLI tooling, human debugging) within the same materializer run that produced them, where the `Globals` is shared.
- A separate-process `materialize_from_analysis` reader (task #78) is **blocked on a wire-format redesign** that drops `SyntaxContext::u32` and reconstructs `Id`s post-resolver in the reader. The redesign needs Stage A to serialize a scope discriminator (`TopLevel` / `Global`) per `Id` and Stage B to call `top_level_id(name, fresh_mark)` after running its own resolver. That work is deferred.

When the redesign lands, re-parse-in-Stage-B remains the recommendation: parsing minified Tana is cheap (~1-2s) and avoids parser-version coupling on the Stage A cache key. The redesign is purely about *what shape the wire format should be*, not whether the AST itself is on disk.

## Bazel action shape

Today:

```
debundle_pipeline(
  inputs: { chunk_bytes, spec_yamls, options },
  outputs: { tree, reports },
)
```

After the split:

```
chunk_analyze(
  inputs: { chunk_bytes, options },
  outputs: { chunk_analysis.json },
)

debundle_materialize(
  inputs: { chunk_analysis.json, spec_yamls, options },
  outputs: { tree, reports },
)
```

The `chunk_analyze` cache key includes the source bytes + ducktape version. Editing spec doesn't re-trigger it. RBE cache hits cleanly across spec-only edits.

## Implementation sequencing

1. **Add `chunk_analysis.json` serialization.** Extend the existing `owner_graph.json` reports infrastructure: same writer, broader content (owner graph + atomic units + chunk metadata + facts subset needed for Stage B). One schema-versioned file per chunk. Land additively — current pipeline still writes everything it does today.
2. **Add a Stage-A-only entry point.** `pipeline::analyze_chunk_only(inputs) → chunk_analysis.json`. Doesn't yet replace anything.
3. **Add a Stage B entry point that reads Stage A.** `pipeline::materialize_from_analysis(chunk_analysis.json, spec, opts)`. Behaves identically to today's `materialize_logical_modules` but takes the artifact instead of chunk bytes.
4. **Make Stage B the production path inside the Bazel rule.** `debundle` rule emits a separate `chunk_analyze` action per chunk, then `materialize` consumes it.
5. **Wire CLIs.** `peel`-family commands take `--chunk-analysis` instead of re-running analysis. Backward-compat: if `--chunk-analysis` absent, fall back to running analysis (slow path).
6. **Optional follow-up.** Add a `debundle inspect` CLI for ad-hoc queries (this is also the foundation for tasks #73 `module merge` and the planned `binding describe`/`scc`/`cluster` surface in AGENTS.md).

Steps 1–4 are the structural split. Steps 5–6 unlock the consumer ergonomics. Either can land independently after the structural split is in.

## Resolved decisions

- **JSON first**: per-concept JSON files (the `chunk_analysis/` directory). Revisit proto only if measurement says JSON load-time is a hot spot.
- **Re-parse in Stage B**: AST is not serialized in v1. The `Id` round-trip across `Globals` is structurally broken; sidestepping it by re-parsing is cleaner than threading a scope discriminator through every Stage-A consumer. See §"What about the AST?" for the full rationale.
- **Full per-statement facts**: `ChunkFactsReport` carries everything `analyze_chunk` produces (already implemented on `feat-facts-wire-format`).

## Remaining open question

- Should `materialize_from_analysis` (task #78) be implemented at all, or rolled into a future wire-format redesign that handles `Id` cross-process portability? Today's sidecars work in-process; a separate-process reader is what motivates the redesign. The structural answer is: don't build #78 on top of today's wire format — wait for the redesign so the reader operates on a structurally-portable artifact from the start.
