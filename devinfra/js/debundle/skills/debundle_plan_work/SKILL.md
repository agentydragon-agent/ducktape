---
name: debundle_plan_work
description: Plan and inspect generic JS debundle spec work using `debundle peel`. Use when an agent needs to turn owner_graph.json plus a modules tree into dispatchable module extraction work, query atomic-DAG and patch-plan status, inspect graph/source context, or decide what debundle spec edits should be made. Generic to any debundle target.
---

# Debundle Plan Work

Use this skill to plan read-only debundling work from the current
`owner_graph.json` and spec `modules/` tree. The output is evidence for
spec edits; this skill does not mutate YAML itself.

## Setup

Find the debundle output and spec modules directory for the target:

```bash
GRAPH=<debundle-output>/reports/tree/<chunk-id>/owner_graph.json
MODULES=<spec-root>/modules
SOURCE_ROOT=<debundle-output>/app
```

Build or run the debundle CLI. In a consuming Bazel repo, use the external
`@ducktape` label; inside the debundler repo, drop the repository prefix.

```bash
bazelisk run @ducktape//devinfra/js/debundle:debundle -- \
  peel plan-work --graph "$GRAPH" --modules "$MODULES" --limit 25 \
  >/tmp/debundle-plan.json
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

1. Run `graph-summary --limit 25` first when orientation is needed. It
   reports owner, atomic-unit, atomic-edge, proposal, and diagnostic counts
   plus the largest residual atomic units.

2. Run `plan-work --limit 25` for dispatchable work. Treat `proposals[]`
   with `landable_today: true` as the primary module-assignment surface.
   Each proposal has owner IDs, binding IDs, line span, active-module
   references, and residual-cell references. Limited output preserves
   planner order: residual-edge topo-depth, then source start line.

3. For current YAML coverage, run `patch-plan`. Rows describe whether a
   module or binding-patch set covers complete atomic units, splits atomic
   units, or mentions unknown bindings. Split-unit rows are not directly
   landable; inspect the unit and adjust the module boundary.

4. For atomic-DAG inspection, run `units`. Use `--residual-only` for
   remaining work, `--readable-only` when you want named bindings, and
   `--by-destination` when grouping by current destination helps.

5. Before assigning a proposal, run `explain` on its proposal, unit, owner,
   binding, or diagnostic ID. Check graph neighbors, current spec homes,
   atomic-unit closure, and factorizer diagnostics.

6. Read source with `source-slice` when deciding final module names,
   architecture, or whether a proposal should be split further by hand.

## Commands

```bash
# Aggregate graph/proposal overview.
bazelisk run @ducktape//devinfra/js/debundle:debundle -- \
  peel graph-summary --graph "$GRAPH" --modules "$MODULES" --limit 25

# Module-assignment proposals and diagnostics derived from the atomic DAG.
bazelisk run @ducktape//devinfra/js/debundle:debundle -- \
  peel plan-work --graph "$GRAPH" --modules "$MODULES" \
  --size-cap-lines 10000 --limit 25

# Current YAML coverage against atomic units.
bazelisk run @ducktape//devinfra/js/debundle:debundle -- \
  peel patch-plan --graph "$GRAPH" --modules "$MODULES" --limit 50

# Atomic unit catalog.
bazelisk run @ducktape//devinfra/js/debundle:debundle -- \
  peel units --graph "$GRAPH" --modules "$MODULES" \
  --residual-only --readable-only --by-destination --limit 100

# Graph/spec explanation for one object.
bazelisk run @ducktape//devinfra/js/debundle:debundle -- \
  peel explain --graph "$GRAPH" --modules "$MODULES" \
  --proposal-id auto_partition_0000 --limit 25

# The selector can instead be --unit-id <unit>, --diagnostic-id <diagnostic>,
# --owner-id <owner>, or --binding-id <binding>. There is no --binding shorthand.

# Source text for one object. Use --source-root when source_path is relative.
bazelisk run @ducktape//devinfra/js/debundle:debundle -- \
  peel source-slice --graph "$GRAPH" --modules "$MODULES" \
  --proposal-id auto_partition_0000 --source-root "$SOURCE_ROOT" \
  --context-lines 40
```

## Reading Results

- `plan-work` is the module-assignment proposal query.
- `patch-plan` is the current YAML coverage query against atomic units.
- `units` is the atomic-DAG catalog.
- `graph-summary` is the quick aggregate overview.
- `explain` is the graph walk primitive for owners, bindings, units,
  diagnostics, and proposals. Select exactly one object with `--owner-id`,
  `--binding-id`, `--unit-id`, `--diagnostic-id`, or `--proposal-id`.
- `source-slice` is the source retrieval primitive for the same IDs.

Prefer these commands over grepping generated output. The owner graph is
the source of truth for cycle gates and residual dependencies; the embedded
atomic DAG is the source of truth for indivisible peel units. The proposal
queue is a heuristic projection from that DAG, not a serialized fact from
`debundle run`.
