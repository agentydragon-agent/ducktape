# `bb remote` Internals

How `bb remote` works end-to-end, from CLI invocation to Bazel execution on the
runner. Based on reading the BuildBuddy source at
`/code/github.com/buildbuddy-io/buildbuddy`.

## End-to-end flow

### 1. CLI arg processing (local, no rc expansion)

Source: `cli/cmd/bb/bb.go`, `cli/remotebazel/remotebazel.go`

`bb remote` is a **bb CLI command**, dispatched at `bb.go:137`
(`interpretAsBBCliCommand`) _before_ the `ResolveArgs` path (line 172) that
reads rc files and expands `--config` flags. This means:

- **`bb remote` does NOT read `.bazelrc`, `~/.bazelrc`, or
  `/etc/bazel.bazelrc` locally.**
- **`bb remote` does NOT expand `--config=X` flags locally.**
- `--config=rbe` in `~/.config/bazel/buildbuddy.bazelrc` has **no effect** on
  `bb remote` invocations.

The only local processing is `CanonicalizeArgs` (flag format normalization,
e.g., `--flag value` → `--flag=value`). All `--config` flags are passed
through literally to the runner.

> **Contrast with `bb build`/`bb test`** (direct local Bazel): These go through
> `ResolveArgs`, which reads all rc files locally, expands configs, and appends
> `--nohome_rc --noworkspace_rc --nosystem_rc`. The "no longer being read"
> warning from Bazel is triggered by these `--no*_rc` flags — Bazel's legacy
> transition check (`option_processor.cc`) sees that `.bazelrc` exists but isn't
> in the read set and warns. Harmless — `bb` already consumed those files.

**bb remote flags** (partial list): `--runner_exec_properties`,
`--run_from_commit`, `--run_from_branch`, `--remote_run_header`,
`--container_image`, `--os`, `--arch`, `--timeout`, `--script`, `--env`.

**NOT a bb flag**: `--remote_header` is a Bazel flag. It must go after the
subcommand, otherwise bb puts it in Bazel startup options and Bazel rejects it.

### 2. `RunRequest` construction

Source: `cli/remotebazel/remotebazel.go`, `parseArgs()` ~line 1298

bb builds a `RunRequest` protobuf and sends it to the runner service via gRPC:

```
RunRequest {
  repo: { url, commit_sha, patches[] }
  exec_properties: [from --runner_exec_properties]
  remote_headers: [from --remote_run_header]
  steps: [{
    run: "bazel <subcommand> <user-flags-as-is> <targets> <auto-configs>"
  }]
}
```

`<user-flags-as-is>` includes literal `--config=X` flags — they are NOT
expanded. The runner's Bazel will expand them against the workspace `.bazelrc`.

**Auto-configs** (hardcoded in `parseArgs`): bb strips any user-supplied
`--bes_backend` and `--remote_cache`, then appends:

- `--config=buildbuddy_bes_backend`
- `--config=buildbuddy_bes_results_url`
- `--config=buildbuddy_remote_cache`
- `--remote_upload_local_results` (for `build` and non-remote `run`)

### 3. Runner bootstrap

Source: `enterprise/server/cmd/ci_runner/main.go`

The runner VM receives the `RunRequest` and:

1. **Git checkout**: fetches the commit, applies patches (local diffs).
2. **Writes `buildbuddy.bazelrc`** to the workspace root (`writeBazelrc`,
   ~line 2201). This file defines the auto-config values:
   ```
   common:buildbuddy_bes_backend --bes_backend=<runner's BES endpoint>
   common:buildbuddy_bes_results_url --bes_results_url=<runner's results URL>
   common:buildbuddy_remote_cache --remote_cache=<runner's cache endpoint>
   common:buildbuddy_remote_executor --remote_executor=<runner's RBE endpoint>
   ```
   Values are dynamic — they point to the same BB environment that triggered
   the run.
3. **Invokes Bazel** with startup flags (`customBazelrcOptions`, line ~1625):
   ```
   --bazelrc=buildbuddy.bazelrc --noworkspace_rc --bazelrc=.bazelrc
   ```
   This ensures `buildbuddy.bazelrc` has highest priority, then the workspace
   `.bazelrc` is loaded explicitly (via `--bazelrc`) while suppressing the
   default workspace rc loading (`--noworkspace_rc`) to avoid double-loading.

### 4. Bazel execution on the runner

Bazel on the runner reads `buildbuddy.bazelrc` and `.bazelrc` (in that
priority order), and expands all `--config` flags. For example,
`--config=rbe` expands using the workspace `.bazelrc` definitions
(`--remote_executor`, `--remote_header`, `--extra_execution_platforms`, etc.).
`--config=buildbuddy_*` expands using `buildbuddy.bazelrc` definitions.

**If you don't pass `--config=rbe` explicitly, RBE is not enabled.** The
runner builds everything locally in linux-sandbox on the runner VM.

### Verified by experiment (2026-04-08)

```
# No --config=rbe → runner builds locally (57 linux-sandbox actions)
bb remote build //devinfra:gazelle --config=nolint

# Explicit --config=rbe → runner fans out to RBE (64 remote cache hits)
bb remote build //devinfra:gazelle --config=nolint --config=rbe
```

## `--run_from_commit` footgun

When `--run_from_commit` is set, local diffs are **NOT synced**. The runner
checks out exactly that commit with no patches. Patches are only generated when
BOTH `--run_from_branch` and `--run_from_commit` are empty (auto-detect mode):

```go
if *runFromBranch == "" && *runFromCommit == "" {
    patches, err := generatePatches(commit)
}
```

Do NOT use `--run_from_commit` in wrapper scripts — it silently drops all
uncommitted local changes.

## Flag taxonomy

| Flag                           | Owned by | Where it goes                 | Purpose                                                             |
| ------------------------------ | -------- | ----------------------------- | ------------------------------------------------------------------- |
| `--runner_exec_properties=K=V` | bb CLI   | `RunRequest.ExecProperties`   | Runner VM platform (disk, recycling)                                |
| `--remote_run_header=K=V`      | bb CLI   | `RunRequest.RemoteHeaders`    | gRPC metadata for the runner execution request                      |
| `--remote_header=K=V`          | Bazel    | Bazel args (after subcommand) | gRPC metadata for RBE actions (API keys, container image overrides) |

## Bazel linux-sandbox and Docker

Bazel's linux-sandbox (non-hermetic mode, the default) creates a new mount
namespace but **inherits the entire host filesystem read-only**. It then
selectively makes output paths writable. It does NOT hide host paths.

Source: [`src/main/tools/linux-sandbox-pid1.cc`](https://github.com/bazelbuild/bazel/blob/master/src/main/tools/linux-sandbox-pid1.cc) — `MakeFilesystemMostlyReadOnly()`
iterates `/proc/self/mounts` and remounts everything `MS_RDONLY` except
whitelisted writable paths.

**Docker socket access**: `/var/run/docker.sock` is always accessible inside the
sandbox because Unix socket `connect()` works through read-only mounts (read-only
blocks file creation/modification, not socket operations).
`--sandbox_add_mount_pair` is only needed in hermetic mode (`-h` flag with
`pivot_root`), not the default non-hermetic mode.

**Docker load gotcha**: `tarfile.TarFile.add()` on symlinks (like Bazel runfiles)
records them as symlink entries with absolute target paths. Docker extracts the
tarball and tries to follow the symlinks, which fail when the targets are
sandbox-internal paths. Fix: `tarfile.open(..., dereference=True)` to store file
content instead of symlinks.

## Key source files

All paths relative to <https://github.com/buildbuddy-io/buildbuddy>.

| File                                                                                                                                                       | Purpose                                                                           |
| ---------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------- |
| [`cli/cmd/bb/bb.go`](https://github.com/buildbuddy-io/buildbuddy/blob/master/cli/cmd/bb/bb.go)                                                             | Entry point; dispatches bb CLI commands before `ResolveArgs`                      |
| [`cli/parser/parser.go`](https://github.com/buildbuddy-io/buildbuddy/blob/master/cli/parser/parser.go)                                                     | `ResolveArgs` (rc reading + config expansion) vs `CanonicalizeArgs` (format only) |
| [`cli/remotebazel/remotebazel.go`](https://github.com/buildbuddy-io/buildbuddy/blob/master/cli/remotebazel/remotebazel.go)                                 | `bb remote` flag parsing, `RunRequest` construction, auto-config injection        |
| [`enterprise/server/cmd/ci_runner/main.go`](https://github.com/buildbuddy-io/buildbuddy/blob/master/enterprise/server/cmd/ci_runner/main.go)               | Runner bootstrap, `buildbuddy.bazelrc` generation, Bazel invocation               |
| [`enterprise/server/hostedrunner/hostedrunner.go`](https://github.com/buildbuddy-io/buildbuddy/blob/master/enterprise/server/hostedrunner/hostedrunner.go) | Runner service, processes `RunRequest`, handles remote headers                    |
| [`proto/runner.proto`](https://github.com/buildbuddy-io/buildbuddy/blob/master/proto/runner.proto)                                                         | `RunRequest` protobuf definition                                                  |
