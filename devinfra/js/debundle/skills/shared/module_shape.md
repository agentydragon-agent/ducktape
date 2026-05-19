# Debundle Module Shape

The goal is a generated tree that reads like a natural JavaScript codebase, not
a mechanically split bundle.

## Seams

A good module seam has at least one of:

- stable public surface
- internal references dominating external references
- multiple meaningful consumers
- clear layer or subsystem ownership
- substantial standalone behavior

Member count is not the rule. A single substantial service, state machine, or
component can be a module. A one-line constant with one consumer usually is
not.

## Locality vs Layer Ownership

Co-consumption is evidence, but architecture ownership is stronger. Do not
co-locate an artifact with its only consumer if that moves domain, policy,
persistence, integration, or infrastructure logic into the wrong layer.

Examples of conventions an architect may infer, not global policy:

- React-like component-local presentation helpers or styling artifacts may
  belong with their sole component consumer.
- Reducers, action constants, and selectors may form a state-management module
  when they share a public contract.
- Parser tables and token predicates may belong with a parser when they are
  internal implementation details.
- Command metadata may belong with a command handler unless it has an
  independent registry or policy role.

Record the scope and exceptions for every inferred convention.

## Convention Induction

Architects should promote understanding through this ladder:

1. Evidence: graph/source facts.
2. Hypothesis: likely convention with scope and counterexamples.
3. Recommendation: concrete worker-ready reorg task.
4. Durable convention: project-local docs updated so future agents and humans
   do not re-litigate it.

Current-state notes should be rewritten in place. Git is the history.

## Anti-Patterns

- grab-bag paths like `utils`, `misc`, `core`, or `helpers` without a project
  convention that makes them meaningful
- standalone primitive constants with one consumer
- style/config/data fragments orphaned from the only code that gives them
  meaning
- preserving chunker accidents as if they were source architecture
- moving lower-layer semantics into a presenter just because the presenter is
  currently the only caller
