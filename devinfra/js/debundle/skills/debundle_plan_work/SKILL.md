---
name: debundle_plan_work
description: Plan and inspect generic JS debundle spec work using read-only `debundle` queries. Use when an agent needs to turn owner_graph.json plus a modules tree into dispatchable module extraction work, query atomic-DAG and coverage status, inspect graph/source context, or decide what debundle spec edits should be made. Generic to any debundle target.
---

# Debundle Plan Work

Use this skill to plan read-only debundling work from the current
`owner_graph.json` and spec `modules/` tree. The output is evidence for
spec edits; this skill does not mutate YAML itself.

## Setup

Find the debundle output and spec modules directory for the target.
Export the standard env vars once so subsequent commands don't need to
repeat the flags:

```bash
export DEBUNDLE_GRAPH=<debundle-output>/reports/tree/<chunk-id>/owner_graph.json
export DEBUNDLE_MODULES=<spec-root>/modules
export DEBUNDLE_SOURCE_ROOT=<debundle-output>/app
```

Build or run the debundle CLI. In a consuming Bazel repo, use the external
`@ducktape` label; inside the debundler repo, drop the repository prefix.

```bash
bazelisk run @ducktape//devinfra/js/debundle:debundle -- \
  modules propose --limit 25 --format json \
  >/tmp/debundle-proposals.json
```

If `bazelisk run @ducktape//...` has Bazel server or output-download
trouble in a consuming repo, build the CLI with an isolated output base
and run the built binary directly:

```bash
bazelisk --output_base=/tmp/debundle-cli-bazel \
  build @ducktape//devinfra/js/debundle:debundle \
  --remote_download_outputs=all
```

## Planning Loop

1. Run `debundle graph-summary --limit 25` first when orientation is
   needed. It reports owner, atomic-unit, and atomic-edge counts plus
   the largest residual atomic units. Add `--include-proposals` only
   when proposal and diagnostic counts are worth running the factorizer.

2. Run `debundle modules propose --limit 25` for dispatchable work.
   Treat `proposals[]` with `landable_today: true` as the primary
   module-assignment surface. Each proposal has owner IDs, binding IDs,
   line span, active-module references, and residual-cell references.
   Limited output preserves planner order: residual-edge topo-depth,
   then source start line. The JSON shape is directly accepted by
   `debundle bindings assign --batch -` for downstream application.

3. For current YAML coverage, run `debundle coverage`. Rows describe
   whether a module or binding-patch set covers complete atomic units,
   splits atomic units, or mentions unknown bindings. Split-unit rows
   are not directly landable; inspect the unit and adjust the module
   boundary.

4. For atomic-DAG inspection, run `debundle atoms`. Use `--residual-only`
   for remaining work, `--readable-only` when you want named bindings,
   and `--by-destination` when grouping by current destination helps.

5. Before assigning a proposal, run `debundle describe <id>` on its
   proposal, atom, owner, binding, or diagnostic ID. Check graph
   neighbors, current spec homes, and atomic-unit closure. Add
   `--include-proposals` for factorizer diagnostics when the extra
   context is needed.

6. Read source with `debundle show-source <id>` when deciding final
   module names, architecture, or whether a proposal should be split
   further by hand.

7. For module-quotient SCC inspection, run `debundle scc` (or
   `debundle scc --binding <sym>` to find one binding's SCC). On large
   graphs use `--format ndjson` for streaming. `debundle cluster <sym>`
   lists the module-quotient neighbors of a binding's owner.

## Commands

```bash
# Aggregate graph/proposal overview.
bazelisk run @ducktape//devinfra/js/debundle:debundle -- \
  graph-summary --limit 25

# Module-assignment proposals derived from the atomic DAG.
bazelisk run @ducktape//devinfra/js/debundle:debundle -- \
  modules propose --size-cap-lines 10000 --limit 25 --format json

# Current YAML coverage against atomic units.
bazelisk run @ducktape//devinfra/js/debundle:debundle -- \
  coverage --limit 50

# Atomic unit catalog.
bazelisk run @ducktape//devinfra/js/debundle:debundle -- \
  atoms --residual-only --readable-only --by-destination --limit 100

# Graph/spec explanation for one object (binding, module path, atom,
# proposal id, owner id, diagnostic id — the renderer dispatches on
# kind).
bazelisk run @ducktape//devinfra/js/debundle:debundle -- \
  describe auto_partition_0000

# Source text for one object. --source-root needed when the binding's
# source_path is relative.
bazelisk run @ducktape//devinfra/js/debundle:debundle -- \
  show-source auto_partition_0000 --context-lines 40

# SCC inspection over the module quotient.
bazelisk run @ducktape//devinfra/js/debundle:debundle -- \
  scc --binding XOe

# Module-quotient neighbors of a binding's owner.
bazelisk run @ducktape//devinfra/js/debundle:debundle -- \
  cluster XOe
```

## Reading Results

- `modules propose` is the module-assignment proposal query. Output is
  a JSON shape accepted directly by `bindings assign --batch`.
- `coverage` is the current YAML coverage query against atomic units.
- `atoms` is the atomic-DAG catalog.
- `graph-summary` is the quick aggregate overview.
- `describe` is the graph walk primitive for owners, bindings, atoms,
  diagnostics, modules, and proposals. Pass the ID as a positional;
  the renderer dispatches on the kind it detects.
- `show-source` is the source retrieval primitive for the same IDs.
- `scc` / `cluster` are module-quotient queries.

Prefer these commands over grepping generated output. The owner graph is
the source of truth for cycle gates and residual dependencies; the embedded
atomic DAG is the source of truth for indivisible move units. The proposal
queue is a heuristic projection from that DAG, not a serialized fact from
`debundle run`.

`peel <...>` invocations are deprecated aliases. Prefer the top-level
commands in all new docs, scripts, and reports.
