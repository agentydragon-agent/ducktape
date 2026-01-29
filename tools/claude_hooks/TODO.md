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

**Problem**: The CI wheel-mode test (`wheel-test` job in `claude-hooks-release.yml`) builds the wheel, installs it via `uv tool install`, then runs Bazel tests against the installed package. But this didn't catch a missing `httpx` dependency in the wheel's `requires` list because:

1. The Bazel test environment already has `httpx` available via `@pypi//httpx` (transitive dep), so the import succeeds even though the wheel doesn't declare it.
2. The wheel is installed into a uv-managed venv, but the test runs inside Bazel which has its own dependency resolution.

**Potential Solutions**:

- **Import smoke test in isolated venv**: After `uv tool install`, run `claude-session-start --help` (or a lightweight import check) *outside* Bazel in the uv venv. This would fail immediately on missing deps since uv only installs declared `requires`.
- **Automated `requires` audit**: Script that compares actual imports in wheel-packaged modules against the wheel's `requires` list. Could use `importlib.metadata` or AST parsing to find all third-party imports and diff against declared deps.
- **`pip check` / `uv pip check`**: After installing the wheel, run dependency consistency checks to surface missing or conflicting deps.
- **`pipdeptree --warn fail`**: Detect missing transitive dependencies post-install.
