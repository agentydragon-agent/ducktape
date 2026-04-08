@README.md

## Target Platform

Linux by default. macOS-only components (Seatbelt, Sandboxer) are explicitly documented.

@STYLE.md

## Session Start Hook (Claude Code Web)

If you see certificate errors, `bazel: command not found`, `Unable to resolve host
remote.buildbuddy.io`, or other signs that session setup failed: **stop and recover before
doing any other work.** Follow <devinfra/claude/hook_daemon/session_start_recovery.md> completely.
Do not bypass proxy/certificate errors with `--noverify`, `SSL_VERIFY=false`, or similar.
The root cause is always a broken session start hook — notify the user if recovery fails.

## Sandbox

Run `bazel`, `terraform`/`tofu`, `kubectl`, `systemctl`, `ss`, `ip`, `curl`, and other network/system commands **outside the sandbox** (`dangerouslyDisableSandbox: true`). The sandbox blocks their network calls (including localhost, e.g., `kubectl` to haproxy on `localhost:7445`).

## Refactoring

When renaming/moving/deleting files or symbols, search **all references** across the entire codebase (imports, BUILD files, CI configs, docs, Dockerfiles, k8s manifests). Missing a reference is worse than being thorough.

**Atomic API changes**: update all callers in the same commit. No transitional shims within this monorepo.

## Before Hand-off

```bash
bazel build //...
bazel test //...
```

Lint (ruff + mypy) runs by default. Use `--config=nolint` to skip.
If you touched `ansible/`, also follow <ansible/AGENTS.md>.

## Git

**NEVER amend a commit that has already been pushed.**

**NEVER use `git reset --soft` to squash onto a base branch that has moved on the remote.** `git reset --soft origin/devel` collapses _all_ differences between HEAD and `origin/devel` into the staging area — including commits other people landed on devel since your branch diverged. The resulting "squashed" commit silently re-applies every upstream change as if it were yours. Use `git rebase origin/devel` first to rebase, then squash with `git reset --soft $(git merge-base HEAD origin/devel)` so only your branch's changes are staged.

## Debug Notes

Convention: `<subproject>/debug/<topic>.md` for persistent investigation notes (RCAs, debug logs). Examples: `debug/spice_lag/README.md`, `debug/wyrm-oom/INVESTIGATION.md`. The `cluster/` subproject uses `cluster/docs/lessons_learned/` instead.

## Plans

`plans/` directories are for future work or work in progress. Once a plan is fully completed, remove it from `plans/` (delete, or squash into a short tombstone/summary elsewhere).

## TODO Tracking

Subprojects use `TODO.md` for persistent TODO tracking. TODOs local to a specific code location are fine as inline comments; cross-cutting or project-level TODOs belong in `TODO.md`.

## Testing

**Always use Bazel**, not direct pytest/python:

```bash
bazel test //path/to:test_target
bazel run //path/to:binary_target
```

**CRITICAL gotcha**: All `py_test` targets MUST have a `pytest_bazel.main()` entry point. Without it, Bazel runs the file as a script which exits 0 without running tests. Add `@pypi//pytest_bazel` to deps.

```python
import pytest_bazel
# ... tests ...
if __name__ == "__main__":
    pytest_bazel.main()
```

**pytest-asyncio auto mode**: configured via `conftest.py` hooks. Do NOT add `@pytest.mark.asyncio` decorators.

**No test skips for missing tools**: let the test fail. Tools come from Bazel runfiles or the RBE worker image.

**Docker tests run on RBE, never locally**: Tests that use Docker (e.g., container E2E tests, proxy integration tests with mitmproxy testcontainers) are designed to run on BuildBuddy RBE workers, which have Docker available. **Never** skip these tests because Docker is unavailable locally, disable them, or claim they are "not runnable." They work on RBE — that is the intended execution environment. If RBE is not working, recover it by following the "Recovering from a Broken Session Start Hook" section above. Every environment in which agents operate will have BuildBuddy accessible, either automatically (session start hook) or through manual recovery. If you cannot restore BuildBuddy remote execution after following recovery steps, **abort and report the issue to the user** rather than working around it with `--remote_executor=""` or local-only execution for tests that assume RBE.

Use the `py_test` macro from `//devinfra/testing:defs.bzl` (not the raw `@rules_python` `py_test`) and set `requires_docker = True`. The macro handles `env_inherit`, tags, and Docker exec properties automatically. Do not add `env_inherit = ["DOCKER_HOST"]` or `tags = ["requires_docker"]` manually.

**Use undeclared test outputs for log capture**: Write diagnostic data (container logs, HAR dumps, config snapshots) to Bazel's undeclared test outputs directory via `util.testing.undeclared_outputs.undeclared_outputs_dir()`. These are uploaded to BuildBuddy and retrievable from the invocation. Do not dump large log blobs into test stdout/stderr — they clutter the test log and are harder to navigate. To read undeclared outputs from a test run:

```bash
TEST_DIR=$(bazel info bazel-testlogs)/path/to/test_target
ls "$TEST_DIR/test.outputs/"          # list undeclared output files
cat "$TEST_DIR/test.outputs/my.log"   # read a specific output
```

On RBE, the outputs are downloaded to the local testlogs dir after the test completes (Bazel fetches them automatically). The mitmproxy fixture saves `proxy.har` to undeclared outputs as an example; see `test_k8s_proxy_integration.py` for container log capture.

**Test timeouts mean hangs, not slowness**: When a test times out, assume it is wedged — an internal operation is waiting on something that will never arrive (deadlock, stuck future, container that never becomes ready, connection to a port nothing is listening on). Do NOT bump `size`/`timeout` as a fix. Instead, trace the execution to find what is blocked: run with `--test_output=streamed --test_arg=-s`, add logging around fixture setup, check for stuck containers (`docker ps`), etc. A test that ran in 35s last week and now times out at 60s is not "slow" — something broke internally.

### Updating syrupy snapshots

Snapshot tests use syrupy (`.ambr` files in `__snapshots__/`). The `.ambr` files must
be listed in the test target's `data` glob (e.g., `glob(["__snapshots__/*.ambr"])`).

To update after intentional changes, run the test on RBE with `--snapshot-update`, then
copy the updated `.ambr` file from the runfiles tree back to the source tree:

```bash
# 1. Run on RBE with snapshot-update (writes into runfiles, not source tree)
bazel test //path/to:snapshot_test \
  --test_arg=--snapshot-update \
  --nocache_test_results

# 2. Copy updated snapshots back to source tree
cp bazel-bin/path/to/snapshot_test.runfiles/_main/path/to/__snapshots__/snapshot_test.ambr \
   path/to/__snapshots__/snapshot_test.ambr
```

**Why not `--remote_executor=""`?** On NixOS, `/bin/bash` doesn't exist, which breaks
the Ruff lint aspect when running locally. Running on RBE avoids this.

Then commit the updated `.ambr` files.

### Live OpenAI API Tests

Use `live_openai_py_test` from `//openai_utils/testing:testing.bzl`. Generates `.mock` and `.live` targets. CI excludes `.live` via `--test_tag_filters=-live_openai_api`.

```python
# test_foo.py
async def test_mock(mock_client): ...

@pytest.mark.live_openai_api
async def test_live(live_openai): ...
```

## JavaScript / TypeScript

Uses `@aspect_rules_js`. **Do NOT run raw `pnpm install`** -- Bazel manages pnpm (pinned in `MODULE.bazel`).

Adding deps: add to `package.json`, run Bazel (first build updates lockfile and fails), run again, commit `pnpm-lock.yaml`.

See <props/frontend/AGENTS.md> for frontend conventions.
