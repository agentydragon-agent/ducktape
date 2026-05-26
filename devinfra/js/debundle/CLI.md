# debundle CLI

Reference for the `debundle` CLI's command surface. Mix of shipped
and planned. The "Status" column marks each one:

- **shipped**: implemented and exposed today;
- **planned**: tracked as a task (number in parentheses), not yet
  implemented.

The CLI is one binary (`bazel run @ducktape_debundle_bin//file:debundle`
or built locally as `bazel-bin/devinfra/js/debundle/debundle`).
All commands share the same JSON-on-stdout / structured-diagnostic-
on-stderr convention as the rest of ducktape.

## Convention: validate-by-default for mutating commands

Every command that **modifies the spec** (any operation that could
change the chunk's factorization — binding assignment, module
merge/rename/disable, etc.) runs the realizability gate **by
default** before writing changes back to disk. If the simulated
post-mutation spec would produce an atom split or a constraining
SCC, the command refuses with a binding-pair-blame diagnostic
(same renderer the materializer uses) and **does not modify any
file**.

Two flags adjust the default on every mutating command:

| Flag | Effect |
|---|---|
| (default) | Validate; refuse the change if invalid; apply if valid. |
| `--no-verify` | Skip validation; apply the change regardless. Escape hatch for multi-step refactors where an intermediate state is intentionally invalid. Don't use casually; the next command will surface any leftover invalidity. |
| `--dry-run` | Validate (or simulate) but do not modify any file. Print the validation result + a diff summary of what would change. |

`--dry-run` and `--no-verify` can be combined: shows what would
change without validating. Mostly useful when investigating *why*
the gate would reject and you want to inspect the intermediate
state without committing to it.

Read-only commands (queries, listings, source slicing) take
neither flag — they have no side effects.

The `run` command (full pipeline) is a special case: the gate is
part of the pipeline contract, not an optional pre-check.
`run --dry-run` runs every pass up to and including the gate, then
stops before writing JS. There is no `run --no-verify` — if you
want the pipeline to emit JS regardless of the gate, fix the spec
first.

## Command table

### Pipeline

| Command | Mutates? | Function | Status |
|---|---|---|---|
| `debundle run` | yes (emits JS tree + reports) | Run the full transform pipeline: parse + facts + owner_graph + atomic_units + realizability gate + lower + emit. | shipped |
| `debundle run --dry-run` | no | Run the pipeline through validation only; do not emit JS. | **planned** |

### Binding-scoped

| Command | Mutates? | Function | Status |
|---|---|---|---|
| `debundle binding describe <sym>` | no | Look up a binding by minimized name. Prints: home module, owner statement, declared bindings on the same owner, structural-atom membership, edges in/out at owner level, edges in/out at module-quotient level. | **planned** (#80) |
| `debundle binding show-code <sym>` | no | Print the source text for the binding's owner statement (reads `owner_graph.json` for the SourceLocation; slices the original chunk bytes). | **planned** (#81) |
| `debundle binding assign <sym> <module>` | yes (spec) | Move a binding into the named logical module. Optional `--rename <NewName>` for a readable-name change in the same operation. Default: validate + apply. `--no-verify` / `--dry-run` available. | **planned** (#82) |

### Module-scoped

| Command | Mutates? | Function | Status |
|---|---|---|---|
| `debundle module merge --target <T> <sources...>` | yes (spec) | Splice `members:` + `anonymous_statements:` from each source YAML into `<T>`; delete the sources. Default: validate + apply. `--no-verify` / `--dry-run` available. | shipped (no-validate) + **planned validation hookup** (#84) |
| `debundle module rename <old-path> <new-path>` | yes (spec) | Rename a module YAML; the compiler infers the new module path from the new filename. Default: validate + apply. `--no-verify` / `--dry-run` available. | **planned** |
| `debundle module disable <module>` | yes (spec) | Rename `<module>.yaml` to `<module>.yaml.disabled` so the compiler skips it. Bindings the module owned fall back to residual (and validation will surface any resulting atom split). Default: validate + apply. `--no-verify` / `--dry-run` available. | **planned** |

### Quotient queries

| Command | Mutates? | Function | Status |
|---|---|---|---|
| `debundle scc [--binding <sym>] [--cycles-only] [--residual-only] [--singletons-only] [--ndjson]` | no | List SCCs in the module-quotient graph. Filter to a single binding's SCC or to a specific class (cycles, residual-only, singletons). | **planned** (#83) |
| `debundle cluster <sym>` | no | List the module-quotient neighbors of a binding's owner. | **planned** (#83) |

### Atomic-DAG queries (existing `peel` family)

| Command | Mutates? | Function | Status |
|---|---|---|---|
| `debundle peel plan-work` | no | Emit factorizer proposals + diagnostics derived from the atomic DAG. Each proposal suggests a binding-to-module assignment. | shipped |
| `debundle peel units` | no | List atomic units from the owner graph. | shipped |
| `debundle peel patch-plan` | no | Coverage report: which atomic units are claimed by the spec, which are residual fallbacks. | shipped |
| `debundle peel explain <id>` | no | Dereference a proposal/unit/owner/binding/diagnostic ID with full graph + spec context. | shipped |
| `debundle peel source-slice <id>` | no | Print source text for any ID type. (For binding IDs, equivalent to `binding show-code`.) | shipped |
| `debundle peel graph-summary` | no | High-level counts (owners, edges, atoms, residual-eligible bindings, etc.). | shipped |

## Argument conventions

Every command that needs an owner-graph input takes `--graph <path>`
(the `owner_graph.json` from a pipeline run). Every command that
reads or writes the spec takes `--modules <dir>` (the per-module
YAML tree root). Commands that slice source text take
`--source-root <dir>` (the upstream snapshot root containing the
original chunk bytes).

For commands that target a specific binding, `<sym>` is the
*minimized* name (e.g. `XOe`) — the local binding identifier in
the chunk's source. To look up by readable name, use
`debundle peel explain` which accepts both.

## Out of scope

- **No cross-process materializer reader.** `debundle run` reads
  the spec and emits JS in one process. There is no
  `materialize-from-cache` mode — the materializer is fast enough
  at gaffer scale that the wire-format complexity of a separate
  Stage B action isn't worth it. See `WIRE_FORMAT.md` §"Cross-process
  scope: not a goal" for the analysis.

- **`facts.json` is not a CLI input.** It's written to
  `reports/tree/<chunk>/chunk_analysis/facts.json` as an in-process
  debug artifact. Humans inspect it; CLI tooling doesn't read it.
  See `facts/wire.rs` module docstring for why.

## See also

- `AGENTS.md` — generic operator workflows that compose these
  commands.
- `DESIGN.md` — the realizability theorem the validation gate enforces.
- `WIRE_FORMAT.md` — JSON sidecar conventions readers of these
  commands consume.
- `PIPELINE_SPLIT.md` — how the underlying Stage A / Stage B
  composition relates to these commands' inputs and outputs.
- `FACTORIZE.md` — the factorization algorithm `peel plan-work`
  draws its proposals from.
