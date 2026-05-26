# debundle CLI

Reference for the `debundle` CLI's command surface. Mix of shipped
and planned. The "Status" column marks each one:

- **shipped**: implemented and exposed today;
- **planned**: tracked as a task (number in parentheses), not yet
  implemented.

The CLI is one binary (`bazel run @ducktape_debundle_bin//file:debundle`
or built locally as `bazel-bin/devinfra/js/debundle/debundle`). All
commands share the same JSON-on-stdout / structured-diagnostic-
on-stderr convention as the rest of ducktape.

## Convention: validate-by-default for mutating commands

Every command that **modifies the spec** (`binding assign`, `binding
rename`, `module merge`) runs validation **by default** before
writing changes back to disk. For commands that affect the chunk's
factorization (anything that moves a binding between modules), that
means the full realizability gate; for renames, it means name-
collision detection. If validation fails the command refuses with a
structured diagnostic (binding-pair blame for gate rejections, name
clash for renames) and **does not modify any file**.

Two flags adjust the default on every mutating command:

| Flag | Effect |
|---|---|
| (default) | Validate; refuse the change if invalid; apply if valid. |
| `--no-verify` | Skip validation; apply the change regardless. Escape hatch for multi-step refactors where an intermediate state is intentionally invalid. Don't use casually. |
| `--dry-run` | Validate (or simulate) but do not modify any file. Print the validation result + a diff summary. |

`--dry-run` and `--no-verify` can be combined: show what would
change without validating. Mostly useful when investigating *why*
the gate would reject and you want to inspect the intermediate
state without committing to it.

Read-only commands (queries, listings, source slicing) take
neither flag — they have no side effects.

`run` is a special case: the gate is part of the pipeline contract,
not an optional pre-check. `run --dry-run` runs every pass up to
and including the gate, then stops before writing JS. There is no
`run --no-verify` — if you want the pipeline to emit JS regardless
of the gate, fix the spec first.

## Name resolution

Every command that takes a binding name (`<sym>`) accepts **either
form** wherever the lookup is unambiguous:

- The *minimized* name from the chunk (e.g. `XOe`) — the stable
  hygiene-aware identity.
- The *readable* name from the spec's `name:` field
  (e.g. `PluginSettingsAccessor`).

If both forms could match different bindings, the command refuses
with a list. Use the minified form to disambiguate.

## Command table

### Pipeline

| Command | Mutates? | Function | Status |
|---|---|---|---|
| `debundle run` | yes (emits JS + reports) | Run the full transform pipeline: parse + facts + owner_graph + atomic_units + realizability gate + lower + emit. | shipped |
| `debundle run --dry-run` | no | Run through validation only; do not emit JS. | **planned** |

### Binding-scoped (mutating)

Read-only binding queries use the top-level `describe` and
`show-source` commands (which accept any ID, including bindings).
The `binding` namespace holds only the mutating operations.

| Command | Mutates? | Function | Status |
|---|---|---|---|
| `debundle binding assign <sym>:<module>[:<readable>] …` | yes (spec) | Move one or more bindings into named logical modules **atomically**. Each positional argument is colon-separated: `<sym>:<module>` to move and keep the current name, `<sym>:<module>:<readable>` to move and rename in the same step. `<sym>` accepts minified or readable form; the optional third field always sets the new readable `name:`. `--batch <file.json>` (or `--batch -` for stdin) reads moves as a JSON array of `{sym, module, readable?}` objects. Validation runs on the *whole batch's* post-state. Default: validate + apply atomically. `--no-verify` / `--dry-run` available. See "Batch atomicity" below. | **planned** (#82) |
| `debundle binding rename <original> <readable>` | yes (spec) | Rename a binding's readable `name:` without moving it. `<original>` accepts minified or current readable form. Validation here is name-collision detection (no two bindings in the chunk get the same readable name). Mostly a convenience over `binding assign` for the rename-without-move case. `--no-verify` / `--dry-run` available. | **planned** (#82) |

### Module-scoped

| Command | Mutates? | Function | Status |
|---|---|---|---|
| `debundle module merge --target <T> <sources...>` | yes (spec) | Splice `members:` + `anonymous_statements:` from each source YAML into `<T>`; delete the sources. Default: validate + apply. `--no-verify` / `--dry-run` available. | shipped (no-validate) + **planned validation hookup** (#84) |

Renaming or disabling a module is **not** a CLI operation — it's a
plain `mv` on the YAML file. The spec compiler infers the module
path from the file location, so:

```bash
# Rename: the module path is re-derived from the new filename.
mv $MOD/runtime/plugins.yaml $MOD/runtime/plugin_settings.yaml

# Disable: any non-.yaml suffix makes the compiler skip the file.
mv $MOD/runtime/plugins.yaml $MOD/runtime/plugins.yaml.disabled
```

After the `mv`, the next `debundle run` (or any subsequent mutating
command on the spec) re-validates and surfaces any resulting atom
split as a gate diagnostic. No dedicated `module rename` /
`module disable` subcommand — the filesystem operation is already
the right primitive.

### Quotient queries

| Command | Mutates? | Function | Status |
|---|---|---|---|
| `debundle scc [--binding <sym>] [--cycles-only] [--residual-only] [--singletons-only] [--ndjson]` | no | List SCCs in the module-quotient graph. Filter to a single binding's SCC or to a specific class. | **planned** (#83) |
| `debundle cluster <sym>` | no | List the module-quotient neighbors of a binding's owner. | **planned** (#83) |

### Atomic-DAG queries

(Previously under `debundle peel <…>`; the four marked below are
moving to top level, and `peel plan-work` is being renamed to
`propose modules`.)

| Command | Mutates? | Function | Status |
|---|---|---|---|
| `debundle atoms` | no | List structural atoms (owner-level SCCs of the constraining-edge graph; per DESIGN.md §"Two classes of atom"). Was `peel units`. | shipped (as `peel units`; **planned rename**) |
| `debundle propose modules` | no | Emit factorizer proposals (binding → module assignment recommendations) + diagnostics derived from the atomic DAG. Was `peel plan-work`. | shipped (as `peel plan-work`; **planned rename**) |
| `debundle coverage` | no | Report spec coverage against atoms: which atoms are claimed, which fall through to residual. Was `peel patch-plan`. | shipped (as `peel patch-plan`; **planned rename**) |
| `debundle graph-summary` | no | High-level counts (owners, edges, atoms, residual-eligible bindings, etc.). | shipped (under `peel`; **planned rename**) |
| `debundle describe <id>` | no | Dereference any identifier with full graph + spec context. Accepted ID kinds: a binding (minified `XOe` or readable `PluginSettingsAccessor`), a module path (`runtime/plugins`), a proposal id, an atom id, an owner id (`owner:42`), a diagnostic id. The renderer dispatches on the kind it detects. Was `peel explain`. | shipped (as `peel explain`; **planned rename**) |
| `debundle show-source <id>` | no | Print the source text for any identifier. Accepted ID kinds: binding (minified or readable), module path (concatenated source of every owner statement in the module, in declaration order), proposal id, atom id, owner id, diagnostic id. Was `peel source-slice`. | shipped (as `peel source-slice`; **planned rename**) |

The `peel` namespace goes away. Existing `peel <…>` invocations
continue to work as deprecated aliases for one release with a
stderr deprecation note pointing to the top-level form.

## Argument conventions

Every command that needs an owner-graph input takes `--graph <path>`
(the `owner_graph.json` from a pipeline run). Every command that
reads or writes the spec takes `--modules <dir>` (the per-module
YAML tree root). Commands that slice source text take
`--source-root <dir>` (the upstream snapshot root containing the
original chunk bytes).

## Batch atomicity (`binding assign`)

`binding assign` takes one or more positional triples
`<sym>:<module>[:<readable>]`. Validation runs on the post-batch
spec, not after each individual assignment — so multi-binding
refactors whose intermediate (after some-but-not-all moves) states
would be invalid can land in one shot.

### Input shapes

```bash
# 1. Single move, keep current name.
debundle binding assign --modules $MOD XOe:runtime/plugins

# 2. Single move + rename.
debundle binding assign --modules $MOD XOe:runtime/plugins:PluginSettingsAccessor

# 3. Multi-move batch (positional triples).
debundle binding assign --modules $MOD \
    XOe:runtime/plugins:PluginSettingsAccessor \
    YOe:runtime/plugins \
    ZOe:runtime/widgets:WidgetRegistry

# 4. Large refactors: --batch reads JSON from a file (or `-` for stdin).
debundle binding assign --modules $MOD --batch moves.json
debundle binding assign --modules $MOD --batch -  < moves.json
```

`<sym>` accepts either the minified name (`XOe`) or the current
readable name (`PluginSettingsAccessor`). The optional third field
sets the **new** readable name; omitting it preserves whatever
readable name is currently in the spec.

### `--batch` JSON format

A top-level JSON array of move objects:

```json
[
  {"sym": "XOe", "module": "runtime/plugins", "readable": "PluginSettingsAccessor"},
  {"sym": "YOe", "module": "runtime/plugins"},
  {"sym": "ZOe", "module": "runtime/widgets", "readable": "WidgetRegistry"}
]
```

- `sym` and `module` are required.
- `readable` is optional; omitting it preserves the binding's current readable name.
- Array order is preserved for dedupe semantics (last-wins when the same `sym` appears more than once).

JSON over TSV because: schema-validated, queryable with `jq`,
composable with the other JSON outputs from the same CLI
(`scc --ndjson`, `propose modules`, etc.), and lets `--batch -`
pipe directly from those producers without a TSV conversion step
in between.

### Atomicity contract

1. Parse all moves from positional + `--batch`. Dedupe; the *last*
   assignment for a binding wins (with a stderr warning on
   conflict).
2. Read the current spec. Compute the post-batch spec in memory.
3. Run the realizability gate on the post-batch spec.
4. If invalid (or any duplicate-binding-claim from the simulated
   moves would surface): print binding-pair blame, exit non-zero,
   **do not modify any file**.
5. If valid: write every affected YAML in one pass. The output is
   atomic from the consumer's perspective — every file that
   changes does so together.

`--dry-run` runs steps 1–4 and stops; reports the validation
result + the planned diff. `--no-verify` skips step 3 (still does
duplicate-claim detection — that's a structural error, not a
validation one).

### Per-move semantics

If you want refuse-intermediate-invalid semantics, invoke
`binding assign` once per move. Per-batch is the default because
the common case for batch is "this refactor needs all-or-nothing
application." Per-move would be the surprising default.

## Out of scope

- **No cross-process materializer reader.** `debundle run` reads
  the spec and emits JS in one process. There is no
  `materialize-from-cache` mode — see `WIRE_FORMAT.md`
  §"Cross-process scope: not a goal" for the analysis.
- **`facts.json` is not a CLI input.** It's an in-process debug
  artifact at `reports/tree/<chunk>/chunk_analysis/facts.json`. See
  `facts/wire.rs` module docstring.
- **Module rename / disable** is just `mv` on the YAML file (see
  "Module-scoped" above). No dedicated subcommand.

## See also

- `AGENTS.md` — generic operator workflows that compose these
  commands.
- `DESIGN.md` — the realizability theorem the validation gate
  enforces.
- `WIRE_FORMAT.md` — JSON sidecar conventions readers of these
  commands consume.
- `PIPELINE_SPLIT.md` — how the underlying Stage A / Stage B
  composition relates to these commands' inputs and outputs.
- `FACTORIZE.md` — the factorization algorithm `propose modules`
  draws its proposals from.
