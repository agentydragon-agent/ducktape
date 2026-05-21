# Rust Hook Daemon v0

Rewrite the retired Python Claude Code hook daemon in Rust. Single static
binary, wire-compatible with Claude Code's JSON protocol.

Rust implementation: `devinfra/claude/claude_hook/`.

## Status

| Phase                                                           | Status   |
| --------------------------------------------------------------- | -------- |
| 1. Container E2E contract test                                  | **Done** |
| 2. Kubeconfig extraction to standalone script                   | **Done** |
| 3. Rust scaffolding + client dispatch + double-fork             | **Done** |
| 4. SessionStart parity (env, shims, bg cmds, lifecycle, banner) | **Done** |
| 5. Release pipeline + flake wiring                              | **Done** |
| 6. Cutover to Rust and delete Python daemon                     | **Done** |

The Python daemon has been deleted. Future parity work from the deleted daemon
is tracked in <../devinfra/claude/TODO.md>.

## Release pipeline

- `release.yml` matrix entry builds `//devinfra/claude/claude_hook:claude_hook`
  and publishes to GitHub Releases with tag `claude-hook-rs-<12hex>`.
- `sync-pins.yml` auto-updates `npins/sources.json` every 30min.
- `nix/packages/default.nix` has `claude-hook-rs` derivation (static binary,
  no runtime deps; installs as `$out/bin/claude-hook`).

## Flake outputs

```
#devtools → devToolsCommon + Rust claude-hook-rs binary + Python statusline
```

`web_setup.sh` installs the Rust `claude-hook` binary. The Python
`claude-hooks` wheel now contains the statusline only.

## Testing the Rust impl live

Open a session and validate with `/web_selfcheck`.

## Remaining gaps

1. **Per-profile context template**. Rust parses `context_template` but does
   not render it.
2. **OpenTelemetry tracing**. Deferred.
3. **Skip re-exec in double-fork**. The grandchild currently `exec`s
   itself (`claude-hook daemon --sock --daemon-dir`) for a clean process
   image. Since the tokio runtime hasn't been created before fork, the
   grandchild could call `run_daemon()` directly — saves ~1ms and one
   exec. Alternatively, split into separate client/daemon binaries.
4. **Python unit test parity**. The Rust tests cover the main path, but some
   restart/crash edge cases from the deleted Python tests still deserve direct
   Rust coverage.

Cutover readiness checklist: <CUTOVER_CHECKLIST.md>
