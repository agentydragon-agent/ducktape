# Debundle CLI Dogfood Backlog

Current open CLI usability and scripting-safety findings from exercising
the documented workflows against a real spec. Resolved items are deleted;
this file is not a changelog.

Each item: severity, command, expected behavior, observed behavior, and a
fix idea where one is obvious.

## 🟡 Confusing (UX, not soundness)

### 1. `--dry-run` reports "would change all 2230 files"

A no-op `bindings assign --dry-run` (moving a binding to its current
home) lists `files_written: [2230 paths]`. The whole spec gets
prettier-canonicalized on rewrite, and `--dry-run` enumerates every file
that would be touched — drowning the actual semantic delta.

**Fix idea**: dry-run output should list only files where `members:` /
`anonymous_statements:` content semantically changes, not files merely
re-formatted by canonicalization.

### 2. `cluster --binding <sym>` documented but rejected

`tana/re/web/AGENTS.md` shows `$BIN cluster --binding XOe --format
ndjson`. The CLI actually wants a positional `<SYM>`: `error: unexpected
argument '--binding' found`.

**Fix idea**: either drop the `--binding` flag form from AGENTS.md or
add it as an alias in the CLI parser.

### 3. `cluster` output uses opaque `logical:N` ids without labels

`debundle cluster XOe` returns:

```json
"home_module": "logical:2009",
"outgoing_modules": ["logical:1031", "logical:1046", ...]
```

`describe` happily prints labels like `static/index-DI2GynTv::app/locale/locale_settings`.

**Fix idea**: include `"label"` / `"path"` alongside the `logical:N` id
in cluster output, matching describe's shape.

### 4. `modules delete` requires `.yaml` suffix; the error message hides it

`debundle modules delete --dry-run auto_partition/auto_partition_0004`
errors with `module path does not exist:
…/spec/modules/auto_partition/auto_partition_0004`. Add `.yaml` and it
works.

`modules comment` and `bindings assign` both accept the bare module
path; only `modules delete` requires the suffix. Inconsistent.

**Fix idea**: accept the bare path (consistent with siblings) or change
the error to "expected `.yaml` suffix".

### 5. `modules merge --dry-run` silent on success

`debundle modules merge --dry-run --target T S1` prints only `reading
T.yaml` to stderr and exits 0. Per `cli.md`, mutating commands should
print a one-line verdict (`ok` / `would change N files` / `rejected
...`).

**Fix idea**: emit the verdict line; cite the prior-art behavior of
`bindings assign --dry-run`.

### 6. `gate list` silent when `cycles.json` missing

`debundle gate list` with no current cycles emits a single `reading
…/cycles.json` to stderr and exits 0 (no body). Indistinguishable from
"file missing" vs "no rejections".

**Fix idea**: emit `[]` (json) or `no blocking SCCs` (text). When the
file is missing, error explicitly.

## 🔵 Minor doc inconsistencies

### 7. `tana/re/web/AGENTS.md` BIN path stale

The doc says `BIN=bazel-bin/external/ducktape_debundle_bin/file/debundle`.
The actual path now has a `+_repo_rules+` prefix:
`bazel-bin/external/+_repo_rules+ducktape_debundle_bin/file/debundle`.

**Fix**: update gaffer-private's AGENTS.md.

### 8. `describe` text format missing home-module path

JSON output includes `binding_homes[].path`. Text output shows owners,
bindings, atom membership, edge counts — but no module path. Either the
text output should include the path, or the docs should reflect text's
narrower surface.

### 9. `bindings comment` read with empty comment returns empty string

Reading an unset comment returns `{"sym": "...", "comment": "",
"action": "read"}`. Indistinguishable from an explicit `comment: ""` in
the spec. Docs say "empty if none."

**Fix idea**: return `"comment": null` or omit the field when unset.

### 10. `describe <sym>` text format hangs on repeat invocations

First invocation returned a 5-line summary; second invocation of the
same command hung indefinitely. `--format json` consistently completes
in ~30s. May indicate a stale cache or non-idempotent text renderer.
