# Central Codex process spike

Experimental upstream-usage fixture. It runs the repository-pinned `codex app-server` with
its `CODEX_HOME` and native frame journal outside the executor directory, and `codex exec-server` with a
separate workspace and environment. A recording WebSocket relay forwards complete messages
without reconstructing RPCs or replaying requests. Only the app-server receives the fake model key.
A scripted Responses endpoint drives real code-mode tools without provider credentials.

```sh
bbr test //agentplane/runner/x/central_codex:test_probe //agentplane/runner/x/central_codex:probe
```

The test checks remote shell, patch and image RPCs, workspace `AGENTS.md` in the actual model request,
and shell environment separation. It parks a mutating shell command after an observed append,
kills the executor process, follows its yielded session with read-only `write_stdin`, reads
conversation history while the executor is unavailable, and
restarts the sampler to read the retained conversation without running inference or replaying the
command. `CODEX_EXEC_SERVER_URL` suppresses upstream's local execution environment.

`test.outputs/` contains executor RPCs, native stdin/stdout/stderr journals, executor diagnostics,
the retained thread, the result of polling the lost process and an uncertainty receipt. All tokens
are fixture values. The experimental host policy observes `environment/status=disconnected`,
records `effects=unknown` outside the executor, then interrupts the turn. The test checks its native
`interrupted` completion. It does not rely on a model deciding to stop or on upstream automatically
turning executor loss into a terminal tool failure.

This fixture shares a host filesystem and principal. Distinct paths and observed RPCs demonstrate
routing and persistence placement, not filesystem authorization or a separate failure domain. It
does not test a storage-daemon outage, container/cgroup descendant fencing, Pod/VM loss,
authenticated Runner Gateway routing, executor LLM network denial, per-Session spend attribution,
or comparable nested-call latency. The relay is test-only and provides no production authority.
The loss fixture cleans up its known blocked shell explicitly; arbitrary descendants require a
real container/cgroup fence.
