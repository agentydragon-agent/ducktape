# Bazel Caching in CI

## Overview

Bazel CI uses two caching layers:

1. **BuildBuddy remote cache** — caches action results (build outputs, test results) across runs. Hosted builds use `.github/actions/bb-remote`; workflows that run Bazel directly configure the same remote cache after `.github/actions/setup-bazel`.
2. **GHA repository cache** — caches Bazel's `repository_cache` (compressed downloads of external dependencies) for workflows that run Bazel directly on GitHub-hosted runners. It uses unified `actions/cache@v6` restore and save behavior.

## Why repository_cache only?

Bazel's local state under `~/.cache/bazel` breaks down as:

| Directory                  | Size   | Purpose                           |
| -------------------------- | ------ | --------------------------------- |
| `output_base/external/`    | ~9.5GB | Extracted external repos          |
| `_bazel_*/cache/repos/v1/` | ~2GB   | Compressed downloads (repo cache) |
| `_bazel_*/install/`        | ~192MB | Extracted Bazel installation      |
| `~/.cache/bazelisk`        | ~62MB  | Bazelisk binary                   |

`output_base/external/` is dominated by the LLVM toolchain (~8.2GB extracted), which alone exceeds the 10GB GHA per-repo cache limit.

The `repository_cache` stores compressed downloads (~2GB). It is content-addressable: each archive is stored by its content hash, so restoring it lets Bazel skip network fetches during analysis even when only some dependencies changed. BuildBuddy handles action-level caching (build outputs, test results), so the GHA cache only needs to cover the analysis-phase download cost.

## Cache key strategy

```
bazel-repo-cache-<hash of MODULE.bazel + MODULE.bazel.lock>
```

- **Shared across all CI jobs** — repository_cache contents are identical regardless of which job populated them.
- **`restore-keys: bazel-repo-cache-`** — on dependency changes, the previous cache is partially restored (content-addressable, so unchanged downloads are reused).
- **Single cache entry** (~2GB) fits within the 10GB limit.

## Cache flow

Workflows that run Bazel directly on a GitHub Actions runner call
`.github/actions/setup-bazel`. Each job restores the exact cache key, falling
back to the newest `bazel-repo-cache-` entry after dependency changes. Bazel
and Bazelisk populate the restored directories as the job runs.

The action uses unified `actions/cache@v6`, which saves the populated cache as
a post step only when the exact key was absent during restore. There is no
dedicated prewarm or `compute-targets` job. BuildBuddy-hosted `bb remote` runs
execute in separate runner VMs and use BuildBuddy's cache rather than this
GitHub-runner filesystem cache.

## Duplicate-key problem (historical)

The former `bazel-repo-cache-save` action used `actions/cache/save@v4`, which creates a new cache entry even when the same key already exists. Multiple CI runs created conflicting entries per key. The GHA cache service responded with HTTP 400 on all restore attempts, making the cache useless across all jobs.

The fix was to switch to the unified `actions/cache` action (currently v6), which only saves when the exact key was not found during restore. This prevents duplicate entries by design.

## Cached paths

- `~/.cache/bazelisk` — Bazelisk-downloaded Bazel binary
- `~/.cache/bazel/_bazel_runner/cache/repos/v1` — Bazel repository cache

The `_bazel_runner` segment assumes the GHA runner username is `runner` (standard on `ubuntu-latest`).

## Alternatives considered

| Approach                                   | Size   | Pros                 | Cons                         |
| ------------------------------------------ | ------ | -------------------- | ---------------------------- |
| Cache full `~/.cache/bazel`                | ~12GB  | Fastest cold start   | Exceeds 10GB GHA limit       |
| Cache `output_base/external/` minus LLVM   | ~1.3GB | No extraction cost   | Fragile exclusion            |
| Cache `repository_cache` only (current)    | ~2GB   | Simple, within limit | Extraction cost on miss      |
| `bazel-contrib/setup-bazel` external-cache | Varies | Per-repo granularity | LLVM still 8.2GB             |
| No GHA cache, BuildBuddy only              | 0      | Simplest             | ~5 min repo fetching per-job |
| Dedicated prewarm job + save               | ~2GB   | Seeds cache once     | Adds to the critical path    |
