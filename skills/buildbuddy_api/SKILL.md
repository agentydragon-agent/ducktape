---
name: buildbuddy_api
description: >
  Reference for querying the BuildBuddy API. Use when investigating failed or slow
  CI builds, inspecting invocations by commit or branch, reading build or test logs,
  checking remote execution (RBE) details (exit codes, stderr, worker logs), analyzing
  cache hit/miss rates, or downloading undeclared test outputs from RBE workers.
  Trigger when the user asks "why did this build fail", "show me the build log",
  "check RBE execution", "get test output from RBE", "what happened in this CI run",
  "check cache performance", or any task that requires fetching data from BuildBuddy.
allowed-tools: Bash
---

# BuildBuddy API

## Prerequisites

All commands require `BUILDBUDDY_API_KEY` to be set (session hook exports it automatically).

## CLI (`bbapi`)

If `bbapi` is in PATH, prefer it over raw API calls:

```bash
# Show invocation details
bbapi invocation <invocation-id>

# List recent invocations (auto-detects repo from git remote)
bbapi invocation list [--repo URL] [--count N]

# Print build log
bbapi invocation log <invocation-id>

# List remote executions for an invocation
bbapi execution <invocation-id>

# Search remote executions across invocations
bbapi execution search <query>

# Show cache scorecard (per-action hit/miss)
bbapi cache <invocation-id>

# Get metadata for a cached artifact by digest
bbapi cache metadata <digest>

# List artifacts, or download one by name match
bbapi artifact <invocation-id> [name-substring]

# List targets in an invocation
bbapi target <invocation-id> [--filter SUBSTR] [--label LABEL]

# Show pass/fail/flake history for targets
bbapi target history <target-label>

# Show build performance trends
bbapi trend [--days N] [--repo URL]
```

All commands support `--json` for raw JSON output.

## Raw API Fallback

If `bbapi` is not available, use the Twirp JSON API at `app.buildbuddy.io` directly
with curl. Read <devinfra/buildbuddy_cli/client.go> for how the CLI talks to the API
(Twirp JSON over HTTP). The API key comes from `BUILDBUDDY_API_KEY` env var, or
parse it from `~/.config/bazel/buildbuddy.bazelrc` (`x-buildbuddy-api-key=...`).

Proto definitions for request/response schemas:

- <https://github.com/buildbuddy-io/buildbuddy/blob/master/proto/buildbuddy_service.proto> (internal, ~70 RPCs)
- <https://github.com/buildbuddy-io/buildbuddy/blob/master/proto/api/v1/service.proto> (public, 9 endpoints)

## Known Limitations

**Fork PRs don't have BuildBuddy invocations.** GitHub Actions does not pass
`BUILDBUDDY_API_KEY` to workflows triggered by fork pull requests (head repo !=
base repo). As a result, `bazel-check` and `bazel-test` are skipped entirely on
fork PRs (see [#787](https://github.com/agentydragon/ducktape/issues/787)).
When investigating a failed fork PR, BuildBuddy has no record of the run — check
GitHub Actions logs directly instead.
