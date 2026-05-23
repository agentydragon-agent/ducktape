# Factorization And Atomic DAG

This note describes the current owner-partition model used by debundle.

There are two separate concepts that older docs sometimes both called
"factorize":

- **Factor assembly** is part of `debundle run`. It takes the owner graph and
  the author's YAML claims, validates them against atomic owner units, and
  produces the authoritative per-owner partition consumed by materialization.
- **Peel factorization** is part of `debundle peel`. It reads the serialized
  `owner_graph.json`, especially `atomic_graph`, and computes advisory module
  proposals for the next authoring step. These recommendations are not emitted
  by ordinary `debundle run`.

## Owner Graph

The owner graph `G = (V, E)` has one vertex per top-level owner: declarations,
anonymous side-effect statements, and other statement-level units tracked by
the analyzer.

Edges record concrete program relationships:

- `EagerUse`: the source owner reads the target during module initialization.
- `LazyUse`: the source owner reads the target later, for example inside a
  function body.
- `EagerRebind` / `LazyRebind`: an owner writes a binding declared by another
  owner.
- `Sequenced`: source-order side-effect ordering evidence.

Each edge records whether it constrains initialization/materialization order.
Lazy reads are still useful graph evidence, but they do not become atomic-DAG
edges unless the analyzer marks them as constraining.

## Atomic Units

`debundle run` computes atomic units from the owner graph before materializing.
Conceptually:

1. Build the constraining-edge subgraph of `G`.
2. Compute SCCs of that subgraph.
3. Treat each SCC as an atomic unit: a valid module assignment may not split it.
4. Condense the SCCs into `atomic_graph`, a DAG of atomic units.

Atomic-unit causes come from the owner-edge kinds that forced owners together.
The emitted unit shape intentionally includes owner arrays, not duplicate
owner counts; callers can derive counts from `owner_ids.length`.

`owner_graph.json` now carries this directly:

```json
{
  "nodes": ["owner graph nodes..."],
  "edges": ["owner graph edges..."],
  "module_graph": "current module quotient",
  "atomic_graph": {
    "nodes": [
      {
        "id": "atomic:0",
        "owner_ids": ["owner:0"],
        "members": [{ "binding": "x", "export_name": "ReadableX" }],
        "destinations": ["..."],
        "causes": [],
        "size_lines_estimate": 3,
        "source_line_range": [10, 12],
        "ordinal_span": 0
      }
    ],
    "edges": [
      {
        "id": "atomic_edge:0",
        "source": "atomic:0",
        "target": "atomic:1",
        "edge_kinds": ["eager_use"],
        "owner_edge_ids": ["owner_edge:7"],
        "constrains_init_order": true
      }
    ]
  }
}
```

The atomic graph is the stable fact. Larger "good module" suggestions are a
planner projection over that DAG.

## Factor Assembly In `debundle run`

The author's YAML files explicitly claim bindings and anonymous statements for
logical modules. Factor assembly resolves those claims to owners, then to
atomic units.

The rules are deliberately strict:

- Two different logical modules may not claim owners from the same atomic unit.
- A module claim that only covers part of an atomic unit is a conflict, not an
  implicit request to move the rest.
- Unclaimed owners remain in the synthesized residual module.
- The materializer consumes only the final explicit partition; it does not
  silently co-move extra owners on behalf of the author.

If the explicit partition is inconsistent, `debundle run` rejects and emits
diagnostic side outputs such as `cycles.json` or
`atomic_unit_conflicts.json`.

## Planner Proposals In `debundle peel`

`debundle peel plan-work` computes advisory proposals from `atomic_graph` and
the current spec tree.

The current proposal pass:

1. Starts from residual atomic units.
2. Follows outgoing constraining edges to residual atomic units, forming closed
   owner sets that can move together without leaving a required residual
   dependency behind.
3. Coalesces overlapping closures.
4. Emits proposals under the size cap, and diagnostics for oversized or
   conflicting closures.
5. Promotes orphaned anonymous-only cells into extensions of an active module
   when every outgoing cross-module constraining edge points at exactly one
   active module, the cell declares no named bindings, and there are no
   outgoing edges to other residual cells. The cell's owners surface in
   `extension_owner_ids` so a downstream consumer can write the
   `anonymous_statements:` entries into the extended module's yaml. This
   catches the canonical "decorator applications and `register(...)` calls
   that the author left in residual when peeling the class they apply to."

These proposals are useful work queues, not authoritative schema. Agents should
still read source and choose honest module names and paths.

Related commands:

- `debundle peel graph-summary`: aggregate owner/atomic/proposal counts and the
  largest residual atomic units.
- `debundle peel units`: inspect atomic units directly.
- `debundle peel patch-plan`: compare existing module YAML and
  `binding_patches.yaml` entries against atomic-unit coverage.
- `debundle peel explain`: inspect owners, bindings, units, proposals, or
  diagnostics with graph/spec context.
- `debundle peel source-slice`: read the selected owners' source span.

## Mental Model

The dependency layers are:

1. **Owner graph**: fine-grained program facts.
2. **Atomic graph**: SCC condensation of constraining owner edges; a DAG.
3. **Spec partition**: the author's current assignment of owners to modules.
4. **Module quotient**: the spec partition projected onto the owner graph for
   validation and report output.
5. **Peel proposals**: optional DAG-derived recommendations computed by
   `debundle peel`, not by `debundle run`.

When debugging planner output, start with the atomic unit. If an assignment
would split a unit, the assignment is wrong regardless of how plausible the
binding names look. If a proposal is too broad, inspect the atomic-DAG edges
that close it and decide whether the edge classification is too conservative
or whether the larger module is genuinely required.
