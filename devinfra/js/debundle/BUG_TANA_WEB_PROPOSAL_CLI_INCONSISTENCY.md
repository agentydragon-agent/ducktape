# Tana web proposal/CLI inconsistencies

Observed from `/home/agentydragon/code/gaffer-private` on 2026-05-28 while
working against `tana/re/web/78d928dca7`.

## Symptoms

- `//tana/re/web/78d928dca7:debundle` passes with the pinned debundler binary.
- `debundle coverage` from the older pinned CLI reports split atomic units for
  modules that already claim the anonymous statements with
  `anonymous_statements:` selectors.
- `debundle modules merge --dry-run` with the same pinned CLI rejects unrelated
  merges for those apparent atom splits.
- Newer local source CLI fixes the false split report when `--source-root` is
  available: coverage reports `split_patch_sets: 0`.
- `debundle modules propose` still emits merge proposals containing module names
  such as `domains/system/ids.js`, but `modules list` has no `*.js` spec module
  paths and `modules merge --target domains/system/ids domains/system/ids.js`
  fails with `No such file or directory`.
- The same proposal run emits anonymous-only `auto_partition` proposals for
  import/export statements and repeated anonymous schema constructor calls that
  are not directly representable as stable module assignments.

## Expected

All debundle CLI subcommands that validate or reason about the spec should use
the same source-root-aware spec/anonymous-statement resolution path as the
pipeline gate.

`modules propose` should only emit merge proposals that name mergeable spec
module paths, or it should mark generated target-file aliases separately so they
cannot be fed to `modules merge` as YAML sources.

Anonymous-only proposals should avoid import/export owners and should not be
marked landable when the only selector would be ambiguous by AST shape.

## Repro Sketch

From `gaffer-private`:

```bash
bazel-bin/tana/re/web/78d928dca7/debundle_cli.sh coverage --limit 10000
bazel-bin/tana/re/web/78d928dca7/debundle_cli.sh modules propose --format json
bazel-bin/tana/re/web/78d928dca7/debundle_cli.sh modules merge --dry-run --target domains/system/ids domains/system/ids.js
```

Useful contrast:

```bash
bazelisk --output_base=/tmp/codex-gaffer-private-bazel \
  run //tana/re/web/78d928dca7:debundle_cli \
  --override_module=ducktape=/home/agentydragon/code/ducktape \
  --config=source-debundler --config=nolint -- \
  coverage --limit 10000
```

With the local source override that includes `--source-root` support, coverage
reports a clean spec for the same tree.
