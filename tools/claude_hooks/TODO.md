# claude_hooks TODO

## Nix Installation Timeout

**Problem**: Installing nix on Claude Code web times out because downloading nixpkgs takes >2 minutes (session start hook timeout).

**Current Workaround**: The `claude_hooks` package is installed via `uv tool install` from a pre-built wheel (published to GitHub releases), avoiding Python dependency installation during session start. Terraform tools (opentofu, tflint) are Bazel-managed via `@multitool//tools/*`. Nix is installed separately for `nix eval`, flake operations, and `nix run nixpkgs#nixfmt` (used by pre-commit hook).

**Potential Solutions:** See <docs/nix-speed-options.md> for detailed analysis. Summary:

- **Pre-built nix store tarball** (recommended) - CI builds closure, publishes tarball, session hook unpacks
- **Pre-computed store paths** - CI records paths, session hook does `nix copy`

## Supervisor Health Check Eventlistener

**Problem**: No proactive health monitoring for auth proxy - if it crashes, supervisor restarts it but we only notice on next bazel invocation.

**Solution**: Add custom eventlistener that:

- Runs every 60 seconds (TICK_60 event)
- Checks TCP port 18081 is listening
- Marks process FATAL if unreachable (supervisor auto-restarts)

Implementation outline:

```ini
[eventlistener:auth_proxy_health]
command=python3 -c "..."  # inline health check script
events=TICK_60
```

Script uses socket to test port, writes READY/RESULT per supervisor protocol.

## Wheel Mode Test: Detect Undeclared Dependencies

**Problem**: The CI wheel-mode test (`wheel-test` job) builds the wheel, installs it via `uv tool install`, then runs e2e tests that invoke `claude-session-start` as a subprocess. When `DUCKTAPE_CLAUDE_HOOKS_USE_WHEEL=1`, the subprocess runs the uv-installed console script, which uses the uv venv's Python. This **should** have caught the missing `httpx` dependency — the uv venv doesn't have it (confirmed: `httpx` is not a transitive dep of any declared requires). Yet a release was tagged from commit `2c7a302` with `httpx` missing.

**Possible explanations** (not yet confirmed):
- Remote cache hit from BuildBuddy returned a passing result from before `httpx` was introduced (despite `--nocache_test_results`)
- E2e tests were skipped by a `skipif` condition (keytool, bazel) that wasn't met in CI
- Some other CI environment artifact

**Fix**: Added a "Verify wheel imports" CI step that runs `uv tool run --from claude_hooks python -c "from tools.claude_hooks import session_start"` outside Bazel. This is a fast, explicit check that fails immediately on undeclared deps.

**Future improvements**:
- Investigate why the subprocess-based e2e test didn't catch the missing dep
- **Automated `requires` audit**: AST-parse wheel-packaged modules and diff third-party imports against declared deps
