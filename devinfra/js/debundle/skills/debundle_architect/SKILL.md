---
name: debundle_architect
description: Audit a debundle spec's named modules for idiomatic JavaScript structure, infer project conventions from evidence, and maintain current-state architecture notes and reorganization recommendations. Use for structural review, convention discovery, module-boundary cleanup, and reorg planning in any debundle target.
---

# Debundle Architect

Use this role for structural review of an in-progress debundle spec. The
architect does not author spec edits; it turns evidence into current-state
notes and concrete reorganization tasks for workers.

Read bundled references as needed:

- `references/workflow.md` for the full multi-agent workflow
- `references/module_shape.md` for shared seam, layering, and convention
  induction guidance

## Inputs

The project adapter must provide:

- `<modules-dir>`: active `modules/**/*.yaml` tree
- `<emitted-js-root>`: generated readable JS tree
- `<graph>`: current `owner_graph.json`, when available
- `<conventions-docs>`: project-local docs such as `AGENTS.md`,
  taxonomy notes, or architecture guides
- `<architecture-notes>` and `<module-reorg>` output paths

Use `debundle_plan_work` for graph/source inspection. Route pure symbol
naming work to `debundle_mint_names`.

## Job

Audit the named active modules and emitted JS for structure that does not
look like a natural JavaScript codebase:

- modules that are too tiny to represent real seams
- modules that glue unrelated subsystems together
- helpers/config/constants separated from their only meaningful owner
- layer-direction violations under the project's architecture
- inconsistent naming/path conventions inside a directory or subsystem
- duplicated concept families spread across arbitrary homes
- extracted modules not reachable from the generated graph

Prefer project-local conventions over generic instincts. When conventions
are missing or weak, infer them from repeated evidence.

## Convention Induction

Record conventions as scoped hypotheses before treating them as rules.

1. Gather evidence from graph edges, source proximity, naming families,
   import direction, call sites, and existing well-shaped modules.
2. Write a hypothesis with scope, evidence, counterexamples, and open
   questions in `<architecture-notes>`.
3. Promote to `<module-reorg>` only when the change is concrete enough for
   a worker to apply without re-deciding the design.
4. Promote durable conventions into `<conventions-docs>` once they affect
   multiple future edits.
5. Demote or delete hypotheses when later evidence contradicts them.

Architecture notes and reorg recommendations are current-state documents,
not append-only logs. Rewrite stale sections in place; git is the history.

## Precedence Model

Co-consumption is useful evidence, but architecture ownership is stronger.
Do not co-locate an artifact with its only consumer if that would move domain,
policy, persistence, integration, or infrastructure logic into a presentation
or feature layer incorrectly.

Examples of inferable conventions, not built-in policy:

- In React-like code, component-local presentation helpers or styling
  artifacts may belong with their sole component consumer.
- Reducers, action constants, and selectors may form one state-management
  module when they share a public contract.
- A parser may own grammar tables and token predicates when they are internal
  implementation details.
- A command handler may own metadata only when the metadata has no separate
  registry or policy role.

Always state the exception boundary. For example, a view component's sole
consumer relationship does not make authorization policy presentation-owned.

## Outputs

`<architecture-notes>` contains evolving understanding:

- observations
- tentative conventions
- suspected layer boundaries
- names of subsystems that need more evidence
- questions for intake or lane workers

`<module-reorg>` contains firm worker-ready recommendations:

```md
## <one-line change>

**Files involved**:

- `<modules-dir>/path/to/module.yaml`

**Evidence**:

- ...

**Proposed change**:

- ...

**Confidence**: high | medium | low

**Blocked by**:

- ...

**Status**: proposed | dispatched | rejected
```

Delete landed recommendations on the next audit pass. Keep rejected entries
briefly only when they prevent re-proposing the same mistake.

## Boundaries

- Do not author module YAML edits.
- Do not run gates or regenerate emitted JS.
- Do not read large minified residual bodies; ask intake to ground them.
- Use the owner graph only as a constraint signal. Workers run the gate.
- Do not bake framework examples into project policy; promote discovered
  project conventions into project docs.
