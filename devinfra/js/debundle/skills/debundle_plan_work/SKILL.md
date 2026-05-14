---
name: debundle_plan_work
description: Plan and inspect generic JS debundle spec work using debundle_agent_cli. Use when an agent needs to turn owner_graph.json plus a modules tree into dispatchable module extraction work, query binding-patch status, inspect graph/source context, or decide what debundle spec edits should be made. Generic to any debundle target.
---

# Debundle Plan Work

Use this skill to plan read-only debundling work from the current
`owner_graph.json` and spec `modules/` tree. The output is evidence for
spec edits; this skill does not mutate YAML itself.

## Setup

Find the debundle output and spec modules directory for the target:

```bash
GRAPH=<debundle-output>/owner_graph.json
MODULES=<spec-root>/modules
SOURCE_ROOT=<upstream-js-root>
```

Build or run the agent CLI. In a consuming Bazel repo, use the external
`@ducktape` label; inside the debundler repo, drop the repository prefix.

```bash
bazelisk run @ducktape//devinfra/js/debundle:debundle_agent_cli -- \
  plan-work --graph "$GRAPH" --modules "$MODULES" > /tmp/debundle-plan.json
```

## Planning Loop

1. Run `plan-work` first. Treat `proposals[]` with
   `landable_today: true` as the primary dispatch surface. Each proposal
   has owner IDs, binding IDs, line span, active-module references, and
   residual-cell references.

2. For binding-patch cleanup, run `patch-status`. Use `full[]` for patch
   sets that are currently assignable as a unit, `with_companions[]` when
   companion bindings must move together, and `near[]` for blocked patch
   sets worth investigating.

3. For symbol-level candidates, run `list-candidates`. Use
   `--readable-only` when you want already-named bindings, and
   `--by-destination` when grouping by the heuristic destination helps.

4. Before assigning a proposal, run `explain` on its proposal, owner, or
   binding ID. Check graph neighbors, current spec homes, peelability
   rows, and factorizer diagnostics.

5. Read source with `source-slice` when deciding final module names,
   architecture, or whether a proposal should be split further by hand.

## Commands

```bash
# Certified module-assignment proposals and diagnostics.
bazelisk run @ducktape//devinfra/js/debundle:debundle_agent_cli -- \
  plan-work --graph "$GRAPH" --modules "$MODULES" \
  --size-cap-lines 10000

# Binding-patch coverage and near misses.
bazelisk run @ducktape//devinfra/js/debundle:debundle_agent_cli -- \
  patch-status --graph "$GRAPH" --modules "$MODULES" \
  --near-missing 2 --max-companions 16

# Candidate catalog.
bazelisk run @ducktape//devinfra/js/debundle:debundle_agent_cli -- \
  list-candidates --graph "$GRAPH" --modules "$MODULES" \
  --readable-only --by-destination

# Graph/spec explanation for one object.
bazelisk run @ducktape//devinfra/js/debundle:debundle_agent_cli -- \
  explain --graph "$GRAPH" --modules "$MODULES" \
  --proposal-id auto_partition_0000

# Source text for one object. Use --source-root when source_path is relative.
bazelisk run @ducktape//devinfra/js/debundle:debundle_agent_cli -- \
  source-slice --graph "$GRAPH" --modules "$MODULES" \
  --proposal-id auto_partition_0000 --source-root "$SOURCE_ROOT" \
  --context-lines 40
```

## Reading Results

- `plan-work` is the module-assignment proposal query.
- `patch-status` is the binding-patch coverage query.
- `list-candidates` is the symbol-level candidate catalog.
- `explain` is the graph walk primitive for owners, bindings, and
  proposals.
- `source-slice` is the source retrieval primitive for the same IDs.

Prefer these commands over grepping generated output. The owner graph is
the source of truth for cycle gates, residual dependencies, and whether a
candidate is actually assignable.
