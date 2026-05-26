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

Stage A also emits a sidecar with the SWC AST or a serialized form for the lowering pass — *or* we re-parse in Stage B if the AST isn't worth shipping. (Open question; see "What about the AST" below.)

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

Stage B's lowering pass needs the SWC AST to emit JS. Three options:

1. **Re-parse in Stage B.** Cheap; parsing minified Tana is ~1-2s. Cache key for Stage A no longer includes parser version; cache key for Stage B does. This keeps Stage A genuinely spec-independent and small.
2. **Serialize the SWC AST in Stage A.** Bigger artifact (~6 MB pretty JSON / 1.5 MB proto for gaffer-scale chunk). Adds parser-version coupling to Stage A. Stage B becomes pure data.
3. **Sidecar `chunk.swc.bin` next to `chunk_analysis.pb`.** Compromise: artifact loader chooses to read AST or not.

Recommendation: **Option 1 (re-parse in Stage B).** The work is small and it keeps Stage A's surface tight. Stage B's bazel action key still hits the spec, so it re-runs anyway when the spec changes; one re-parse is in the noise.

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

## Open questions for the user

- Is "Option 1 first, measure, migrate to Option 4 later if needed" the right gradient, or do you want to pay the proto cost up front?
- Re-parse in Stage B vs serialize the AST — preference?
- Should `chunk_analysis.json` carry the full statement facts (`reads_at_init`, `reads_lazy`, `has_side_effect`) per statement, or only what Stage B + the CLIs need? Full facts are larger but make Stage A a more complete artifact; subset is leaner.
