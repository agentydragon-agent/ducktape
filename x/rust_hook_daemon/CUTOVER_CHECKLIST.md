# Rust Hook Daemon — Historical Cutover Checklist

The default has been cut over to the Rust `claude-hook` binary and the Python
daemon has been deleted. Keep this as the live-session validation checklist.

## Must pass (blocks cutover)

- [ ] Session starts without errors (no 500, no daemon timeout)
- [ ] `claude-hook --version` shows the Rust binary
- [ ] `/web_selfcheck` skill passes all SPEC acceptance tests
- [ ] `env -0` under session env shows decrypted secrets
      (`BUILDBUDDY_API_KEY`, `GITHUB_TOKEN`, `DUCKTAPE_CI_READ_GITHUB_TOKEN`)
- [ ] `git --version` via shim works (passthrough)
- [ ] `git add -A` blocked with `BLOCKED` message (git shim policy)
- [ ] `bazelisk build //:hello` succeeds via shim
- [ ] `~/.kube/config` exists with correct server + token (bg command)
- [ ] `bbr test //devinfra/claude/...` completes (RBE works via bbr)
- [ ] Context banner visible in session transcript (`additionalContext`)
- [ ] Daemon log at expected path, no unhandled panics
- [ ] Second `SessionStart` (compaction) reuses existing daemon (no race)
- [ ] Idle watchdog fires after 30min (testable with short timeout override)

## Should verify (non-blocking but important)

- [ ] Daemon restart after SIGKILL (client kills stale, forks new)
- [ ] Circuit breaker blocks rapid re-fork after daemon crash
- [ ] `/mailbox` POST from bg command delivers to next REPL hook
- [ ] Multiple concurrent hook invocations → single daemon (daemon.lock)
- [ ] `curl --unix-socket $HOOK_DAEMON_SOCK http://localhost/health` returns ok
- [ ] Env file has 0o600 permissions

## How to run the live test

1. Open a new session on `devel` after the change lands.
2. Confirm Setup installed devtools and Rust `claude-hook` is on PATH.
3. Walk the checklist above.
