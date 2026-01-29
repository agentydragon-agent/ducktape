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

## Wheel Mode Test: Detect Undeclared Dependencies (fixed)

**Problem**: The CI wheel-mode test runs `claude-session-start` as a subprocess when `DUCKTAPE_CLAUDE_HOOKS_USE_WHEEL=1`. The subprocess uses the uv venv's Python, which only has declared `requires`. However, Bazel's test runner sets `PYTHONPATH` to include all runfiles paths (including `@pypi//httpx`). The subprocess inherited this `PYTHONPATH`, so undeclared deps like `httpx` were importable via Bazel's leaked dependency tree despite not being in the wheel's `requires`.

**Root cause**: `subprocess.run()` in `run_session_start_hook` inherited `os.environ` including Bazel's `PYTHONPATH`. Confirmed via CI artifact `hook-stdout.log` which showed `sys.path` containing `pypi_313_httpx/site-packages` from runfiles.

**Fix**: Clear `PYTHONPATH` from the subprocess environment when `USE_WHEEL=1`, so the process only sees packages from the wheel's venv.
