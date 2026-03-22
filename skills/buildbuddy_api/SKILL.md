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
# List recent invocations (auto-detects repo from git remote)
bbapi invocations [--repo URL] [--count N]

# Print build log
bbapi log <invocation-id> [--lines N]

# List remote executions for an invocation
bbapi executions <invocation-id>

# Show cache scorecard (per-action hit/miss)
bbapi cache <invocation-id>

# List test output artifacts (label + filename)
bbapi artifacts ls <invocation-id>

# Download an artifact by name match (prints to stdout)
bbapi artifacts get <invocation-id> <name-substring>
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
