# Debundle

`debundle` is a JavaScript bundle restructuring tool. It reads a transform
spec, emits a decomposed module tree, and writes analysis artifacts that help
drive later module peel and naming work.

The command surfaces:

- `debundle run`: execute the transform pipeline.
- `debundle peel <…>`: query generated owner graphs and spec modules for
  planning module extraction work. (Being lifted to top-level
  `debundle atoms` / `coverage` / `describe` / `show-source` /
  `graph-summary` / `modules propose` — see `docs/cli.md`.)
- `debundle module merge`: splice module YAMLs (will become
  `modules merge`).
- `debundle bindings comment <sym>` / `debundle modules comment <module>`:
  set, read, or clear the `comment:` field on a binding or module — see
  "Comments" below.

For the full command surface (shipped + planned), see `docs/cli.md`.

## CLI

Run a flat spec:

```sh
debundle run --spec transform-spec.yaml
```

Run a tree-shaped authoring spec:

```sh
debundle run \
  --tree-config spec/spec_config.yaml \
  --tree-modules spec/modules \
  --tree-vendor-marks spec/sources/vendor/vendor_marks.yaml \
  --tree-source-root . \
  --out-root bazel-bin/example/debundle.out
```

Vendor-package source lookup can be supplied either as repeated explicit roots:

```sh
debundle run ... \
  --package-root react=/path/to/node_modules/react \
  --package-root zod=/path/to/node_modules/zod
```

or as a package tree:

```sh
debundle run ... --packages-root /path/to/node_modules
```

The package-tree form resolves package names as paths under `node_modules`,
including scoped names such as `@scope/pkg`.

## Bazel Integration

`pipeline.bzl` provides a Bazel rule for running `debundle run` as a normal
build action:

```python
load("@ducktape//devinfra/js/debundle:pipeline.bzl", "debundle_pipeline")

debundle_pipeline(
    name = "debundle",
    input_data = [
        "//path/to:bundle_inputs",
    ],
    package_roots = {
        "//:node_modules/react/dir": "react",
        "//:node_modules/zod/dir": "zod",
    },
    spec_tree_inputs = [":spec_data"],
    tree_config = "spec/spec_config.yaml",
    tree_modules = "spec/modules",
    tree_vendor_marks = "spec/sources/vendor/vendor_marks.yaml",
)
```

The rule writes a tree artifact named `<target>.out` under `bazel-bin`. It
declares the spec, input data, package roots, and debundler binary as Bazel
inputs/tools, then runs the debundler from `BAZEL_BINDIR` so source-relative
spec paths resolve the same way they do in ordinary builds. By default the rule
uses `@ducktape//devinfra/js/debundle:debundle`; consumers can select a
different binary at repo or command-line scope with:

```sh
bazel build //path/to:debundle \
  --@ducktape//devinfra/js/debundle:debundler=@my_debundle_bin//file
```

## Profiling Actions

For recurring performance work, prefer `debundle_pipeline_with_profiles`.
It creates the normal pipeline target plus local profiling sibling targets that
reuse the exact same action command, inputs, package roots, working directory,
and debundler binary.

```python
load(
    "@ducktape//devinfra/js/debundle:pipeline.bzl",
    "debundle_pipeline_with_profiles",
)

debundle_pipeline_with_profiles(
    name = "debundle",
    # Same attrs as debundle_pipeline.
)
```

Generated targets:

- `:debundle`
- `:debundle_profile_time`
- `:debundle_profile_perf`
- `:debundle_profile_massif_heap`
- `:debundle_profile_heaptrack`

Profile actions are tagged `manual` and use local/no-remote/no-cache/no-sandbox
execution requirements. Build them with full output downloads when remote
execution is configured:

```sh
nix develop --command bazelisk build //path/to:debundle_profile_perf \
  --config=nolint \
  --remote_download_outputs=all
```

Each profile target writes a `<target>.profile` tree artifact. Common files:

- `command.sh`: replayable command with the Bazel action cwd and argv.
- `stdout.txt`: debundler stage timings.
- `debundle.out/`: the debundle output tree produced by the profiled run.

Mode-specific files:

- `time`: `stderr_time.txt` from `/usr/bin/time -v`.
- `perf`: `perf.data`, `perf_report_children.txt`,
  `perf_report_no_children.txt`, `perf_script_stacks.txt`, `perf_header.txt`,
  and `perf_evlist.txt`.
- `massif_heap`: `massif_heap.out`, `massif_heap_stderr.txt`, and
  `ms_print_heap.txt` when `ms_print` is available.
- `heaptrack`: `heaptrack*`, `heaptrack_stderr.txt`, and
  `heaptrack_print.txt` when `heaptrack_print` is available.

Save important runs before cleaning Bazel outputs:

```sh
mkdir -p debug/perf/YYYY-MM-DD-<short-name>
cp -a bazel-bin/path/to/debundle_profile_perf.profile/. \
  debug/perf/YYYY-MM-DD-<short-name>/
```

If `perf` is blocked by host kernel settings, use `time`, `massif_heap`, or
`heaptrack` first and rerun `perf` on a host where userspace sampling is
available.

## Peel Queries

Generated owner graphs can be queried with `debundle peel`:

```sh
debundle peel plan-work --graph "$GRAPH" --modules "$MODULES" --limit 25
debundle peel patch-plan --graph "$GRAPH" --modules "$MODULES" --limit 50
debundle peel units --graph "$GRAPH" --modules "$MODULES" --readable-only --limit 100
debundle peel graph-summary --graph "$GRAPH" --modules "$MODULES" --limit 25
debundle peel explain --graph "$GRAPH" --modules "$MODULES" --proposal-id <id>
debundle peel explain --graph "$GRAPH" --modules "$MODULES" --unit-id <id>
debundle peel explain --graph "$GRAPH" --modules "$MODULES" --binding-id <binding>
debundle peel explain --graph "$GRAPH" --modules "$MODULES" --owner-id <owner>
debundle peel source-slice --graph "$GRAPH" --modules "$MODULES" \
  --proposal-id <id> --source-root "$SOURCE_ROOT" --context-lines 40
```

`explain` and `source-slice` select exactly one object with `--proposal-id`,
`--unit-id`, `--diagnostic-id`, `--owner-id`, or `--binding-id`; there is no
`--binding` shorthand.

Typical adapter bindings:

```sh
GRAPH=<debundle-output>/reports/tree/<chunk-id>/owner_graph.json
MODULES=<spec-root>/modules
SOURCE_ROOT=<debundle-output>/app
DEBUNDLE_OUT=<debundle-output-root>
```

## Comments

Both members and module YAMLs may carry an optional `comment:`
field for reverse-engineering annotations. The fields are authored
once and propagate to the emitted JS on every rebuild, so RE notes
survive `debundle run` invocations.

```yaml
# Module YAML
comment: |
  Plugin settings registry. Top-level home for state related to the
  plugin extension surface.

members:
  - name: PluginSettingsAccessor
    selector:
      binding: { name: XOe, kind: variable_declarator }
    comment: |
      Accessor for plugin settings registered via the plugin
      system's register() hook. Side-effect free.
```

Edit them via the CLI:

```sh
# Set a member's comment from a positional arg.
debundle bindings comment XOe "Accessor for plugin settings..." \
  --modules "$MODULES"

# Open $EDITOR pre-populated with the current comment.
debundle bindings comment XOe --edit --modules "$MODULES"

# Remove the comment entirely.
debundle bindings comment XOe --clear --modules "$MODULES"

# Read the current comment (plain text on tty, JSON on pipe).
debundle bindings comment XOe --modules "$MODULES"

# Same three modes for module-level comments.
debundle modules comment runtime/plugins --edit --modules "$MODULES"
```

`bindings comment` accepts minified (`XOe`) or readable
(`PluginSettingsAccessor`) names. `modules comment` takes the
module path (`runtime/plugins`) relative to `$MODULES`.

JS emission of these comments is on the roadmap (#88); CLI editing
is live today (#89).

## Conditionally-correct optimizations

Some analyses in this crate are **conditionally correct**: they are sound
only when the input bundle avoids a small set of dynamic-dispatch shapes
that defeat static reasoning. Each such pass checks the precondition on
the statements it would fire on and falls back to a strictly-conservative
path when the check fails — see AGENTS.md → "Conditionally-correct
optimizations" for the soundness rule.

The first such pass is the dataflow-aware S-chain in `graph.rs`, opted
into per chunk via
`chunk_analysis_options.<chunk_id>.dataflow_aware_s_chain` in the spec.
It is sound when no top-level statement contains:

- direct `eval(...)` / `(0, eval)(...)`
- `with (obj) { ... }`
- `new Function(...)` / `Function(...)`
- computed-key `globalThis[<expr>]` / `window[<expr>]` / `self[<expr>]`
- `Object.defineProperty` / `Reflect.defineProperty` on a global
- `new Proxy(<global>, ...)`
- dynamic member-key reads/writes on outer-scope bindings the pass
  would otherwise track

Each impure top-level statement carries a `dataflow_summarizable` bit
(`facts/wire.rs`). Statements that fail the check fall back to the
strictly-conservative S-chain (every adjacent impure pair gets an
edge), so the optimization is safe to enable even on bundles that
mix audited and unaudited code — only the unsummarizable statements
pay the conservative cost.

See `DESIGN.md` → "Emission modes" for the precise dataflow-aware
emission rule.
