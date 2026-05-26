# Debundle User Guide

Step-by-step workflows for the `debundle` CLI. The command surface
itself is in `docs/cli.md`; this document is the operational companion.

## Setting common env vars once

Every read-only and mutating command accepts `--graph`, `--modules`,
and (for source-reading commands) `--source-root`. Export the
corresponding env vars once per shell session and subsequent commands
run without repeating the flags:

```bash
export DEBUNDLE_GRAPH=<debundle-output>/reports/tree/<chunk-id>/owner_graph.json
export DEBUNDLE_MODULES=<spec-root>/<version>/modules
export DEBUNDLE_SOURCE_ROOT=<debundle-output>/app
export DEBUNDLE_OUT=<debundle-output-root>
```

Flags win when both are set. Use this for one-off overrides.

If remote execution downloads only minimal outputs, request full outputs
so side files are local:

```bash
--remote_download_outputs=all
```

## Output formats

Read-only commands accept `--format text|json|ndjson`:

- `text` — interactive default, scannable on a terminal.
- `json` — single JSON document, parseable with `jq`.
- `ndjson` — one JSON value per line, for streaming consumers.

If `--format` isn't passed and stdout is **not** a tty, the default
flips to `json`. So `debundle modules propose | jq ...` works without
an explicit `--format json`.

Reach for `ndjson` on streaming queries with many rows
(`debundle scc --format ndjson` over a large graph), or when piping
into `jq -c` / `xargs`.

Mutating commands (`bindings assign`, `bindings rename`, `modules
merge`) print a one-line verdict (`ok`, `would change N files`,
`rejected ...`). `--dry-run` adds the planned diff summary; a
structured YAML diff is not yet in v1.

## Running the pipeline

Run the transform pipeline:

```bash
debundle run --spec <transform-spec.yaml>

debundle run \
  --tree-config <spec-config.yaml> \
  --tree-modules <modules-dir> \
  --tree-vendor-marks <vendor-marks.yaml> \
  --out-root <out-dir>
```

The gate is part of the pipeline contract: if the spec is
unrealizable, `debundle run` rejects and emits structured side outputs
(`cycles.json`, `atomic_unit_conflicts.json`) under
`reports/tree/<chunk-id>/`. There is no `run --no-verify` — fix the
spec first.

## Workflow: investigating a binding end-to-end

When a binding's role is unclear or a proposal is suspicious:

1. **`debundle describe <sym>`** — graph + spec context. `<sym>` is
   either the minified name (`XOe`) or the readable name
   (`PluginSettingsAccessor`). Output includes the binding's owner,
   home module, atom membership, and incoming/outgoing edges.
2. **`debundle show-source <sym>`** — print the original source span
   for the owner. Use `--context-lines 40` to widen the view.
3. **`debundle cluster <sym>`** — list the module-quotient neighbors
   of the binding's owner. Useful for "what does this module touch?"
   questions before deciding a destination.

`describe` and `show-source` accept any ID kind: bindings, module
paths (`runtime/plugins`), owner IDs (`owner:42`), atom IDs, proposal
IDs, diagnostic IDs. The renderer dispatches on the kind it detects.

## Workflow: proposing new modules

Use the factorizer to surface what's currently extractable:

1. **`debundle modules propose --format json > moves.json`** —
   factorizer proposals + diagnostics derived from the atomic DAG.
   The JSON shape is one of the input shapes `bindings assign --batch`
   accepts; the two commands compose without a TSV step.
2. **Skim the diagnostics.** Each diagnostic explains why a closed
   atomic-DAG set could not become a `peelable_now` proposal
   (oversized, blocked by an active module, residual-dependency
   leak).
3. **Apply with `debundle bindings assign --batch moves.json`** (see
   the move workflow below).

For aggregate counts before drilling in:

```bash
debundle graph-summary --format text
```

For a focused look at one proposal before applying:

```bash
debundle describe <proposal-id>
debundle show-source <proposal-id> --context-lines 40
```

## Workflow: moving a binding from one module to another

`debundle bindings assign` is the move primitive. Each positional
argument is colon-separated: `<sym>:<module>[:<readable>]`.

### Single move, keep current name

```bash
debundle bindings assign XOe:runtime/plugins
```

`<sym>` accepts minified (`XOe`) or readable
(`PluginSettingsAccessor`) form. The destination module is
auto-created if it doesn't yet exist; the source module is auto-deleted
when its `members:` becomes empty **and** its top-level `comment:` is
empty/absent (modules with a comment are kept as `members: []`
shells).

### Move + rename in one step

```bash
debundle bindings assign XOe:runtime/plugins:PluginSettingsAccessor
```

The optional third field sets the new readable `name:`. Validation
includes name-collision detection.

### Batch move

Multi-binding refactors run as one atomic operation: validation is
checked on the post-batch spec, not after each individual move. This
lets the intermediate state be "invalid" (e.g. half-moved atom) so
long as the final state is valid.

```bash
debundle bindings assign \
    XOe:runtime/plugins:PluginSettingsAccessor \
    YOe:runtime/plugins \
    ZOe:runtime/widgets:WidgetRegistry
```

For large refactors, pipe JSON:

```bash
debundle bindings assign --batch moves.json
debundle bindings assign --batch - < moves.json
# Direct from the factorizer:
debundle modules propose | debundle bindings assign --batch -
```

JSON shape:

```json
[
  { "sym": "XOe", "module": "runtime/plugins", "readable": "PluginSettingsAccessor" },
  { "sym": "YOe", "module": "runtime/plugins" },
  { "sym": "ZOe", "module": "runtime/widgets", "readable": "WidgetRegistry" }
]
```

`sym` and `module` are required; `readable` is optional. Array order
controls dedupe (last-wins on duplicate `sym`).

### Default validation, `--dry-run`, `--no-verify`

```bash
# Default: validate the post-batch spec; refuse if invalid; apply if valid.
debundle bindings assign XOe:runtime/plugins

# Preview only: run validation, print verdict, don't modify any file.
debundle bindings assign --dry-run XOe:runtime/plugins

# Apply without validating. Escape hatch for intentional intermediate states.
debundle bindings assign --no-verify XOe:runtime/plugins
```

`--dry-run` + `--no-verify` together: show what would change without
validating. Useful for inspecting an intermediate that you know
violates the gate.

## Workflow: renaming a binding without moving

```bash
debundle bindings rename XOe PluginSettingsAccessor
```

`<original>` accepts minified or current readable form. Validation is
name-collision detection (no two bindings share the same readable name
within the chunk). Mostly a convenience over `bindings assign` for the
rename-only case. `--no-verify` / `--dry-run` available.

## Workflow: fixing an atom-split rejection

When `bindings assign` rejects with an "atom split" diagnostic, the
realizability gate found that the requested move would split an
indivisible owner set. The diagnostic names the split atom, its owners,
and the destinations each member would land in.

1. **Read the diagnostic.** It names the atom, lists each owner's
   current and proposed module, and the `DepKind` causes (eager_use,
   rebind, sequenced, ...).
2. **Inspect the atom.** Run `debundle describe <atom-id>` for graph
   context (which owners are in it, why they're co-bound), then
   `debundle show-source <atom-id>` to read the source.
3. **List atoms broadly** if you need to triangulate:
   ```bash
   debundle atoms --format json | jq '.[] | select(...)'
   ```
   `debundle coverage` reports per-atom spec coverage; rows tagged
   "split" by current YAML are not landable until the partition agrees.
4. **Either expand the move set or revisit the partition.** The
   diagnostic does not auto-compute the minimal completion ("also move
   `rRe` and `MRe`"); read the printed atom membership and add the
   missing moves to your batch.
5. **Re-run** with the expanded batch.

The gate refuses; nothing on disk has changed.

## Workflow: merging two modules

```bash
debundle modules merge --target <T> <source1> [<source2> ...]
```

Splices `members:` + `anonymous_statements:` from each source YAML
into `<T>`; deletes the source YAML files.

```bash
# Preview only — print verdict and planned diff summary.
debundle modules merge --dry-run --target runtime/plugins runtime/widgets

# Apply.
debundle modules merge --target runtime/plugins runtime/widgets
```

Source-module `comment:` content is concatenated into the target's
module-level `comment:` with a `--- from <source>:` divider when
sources have non-empty comments.

The realizability gate runs against the post-merge partition before
the YAML splice fires — pass `--graph <owner_graph.json>` so the
gate has the chunk's edge topology. The gate rejects merges that
would create cross-module cycles; `--dry-run` runs the gate without
writing. Use `--no-verify` to skip the gate (e.g. during multi-step
refactors where an intermediate state is intentionally invalid).

## Workflow: authoring `comment:` fields

```bash
# Set a member's comment from a positional arg.
debundle bindings comment XOe "Accessor for plugin settings ..."

# Open $EDITOR (fallback $VISUAL, then vi) pre-populated with the current comment.
debundle bindings comment XOe --edit

# Read the current comment (plain text on tty, JSON on pipe).
debundle bindings comment XOe

# Remove the comment entirely.
debundle bindings comment XOe --clear

# Same three modes for module-level comments.
debundle modules comment runtime/plugins --edit
```

`<sym>` accepts minified or readable; `<module>` is the module path
relative to `$DEBUNDLE_MODULES`.

Move semantics (CLI surface, not a separate feature):

- `bindings assign` carries a member's `comment:` with the member as
  it moves between modules.
- `bindings assign` auto-deletes a drained source module only when its
  module-level `comment:` is empty/absent.
- `modules merge` concatenates source-module comments into the target.

JS emission of comments lands with #88; CLI editing is live (#89).

## Renaming or disabling a module

Not a CLI operation — plain `mv` on the YAML file:

```bash
# Rename: the module path is re-derived from the new filename.
mv $DEBUNDLE_MODULES/runtime/plugins.yaml $DEBUNDLE_MODULES/runtime/plugin_settings.yaml

# Disable: any non-.yaml suffix makes the spec compiler skip the file.
mv $DEBUNDLE_MODULES/runtime/plugins.yaml $DEBUNDLE_MODULES/runtime/plugins.yaml.disabled
```

The next mutating command (or `debundle run`) re-validates and
surfaces any resulting atom split as a gate diagnostic.

## Evidence files

Typical debundle outputs include:

- executable JS under `app/`
- root reports under `reports/`: `output.json`, `chunks.json`,
  `runtime.json`, `source_assets.json`, `provenance.json`,
  `rename_queue.json`, `vendor_swaps.json` when those stages run
- per-chunk reports under `reports/tree/<chunk-id>/`: `chunk.json`,
  `modules.json`, `owner_graph.json`
- `reports/tree/<chunk-id>/cycles.json` or
  `reports/tree/<chunk-id>/atomic_unit_conflicts.json` only when
  validation rejects
- mirrored per-directory and per-file dependency reports under
  `reports/tree/**/index.json` and `reports/tree/**/*.js.json`

Use manifests for progress reporting rather than rescanning generated
JS by hand. Use tree reports for hierarchy-health evidence:
incoming/outgoing semantic dependency counts by kind, and full
symbol/file attribution for boundary crossings that make a directory
leaky or well-encapsulated. Treat them as graph evidence to pair with
source reading, not as a substitute for understanding the
implementation.

## Gate discipline

The adapter-provided gate is authoritative. For suspicious green
builds, force a fresh execution using whatever mechanism the project
build supports. Do not trust cache-only success when validating new
module boundaries.

Generated JS conflicts should be resolved by the adapter regen
command, not by hand-editing generated output.

## See also

- `cli.md` — full command surface (shipped + planned).
- `README.md` — crate pitch, Bazel integration, `comment:` schema.
- `design.md` — the realizability theorem the gate enforces.
- `FACTORIZE.md` (legacy; folded into `design.md`) — owner / atomic /
  module graph vocabulary.
