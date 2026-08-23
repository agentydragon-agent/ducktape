# The second harness seam

Codex app-server is the second implementation of the shared harness bridge.

`CliBackend` still supplies only process bootstrap: a name, executable resolution, argv/cwd/environment
handling. The shared runner does not inspect native payloads and has no provider branches or
`replayable()` hook. Every `harness_frame` is retained and replayed by its opaque wire position, so
Claude's stream events and Codex's JSON-RPC-shaped notifications follow the same recovery path.

The two implementations remain parallel at the edges:

- `haku/runtime/x/bridge/claude_options.py` and `codex_options.py` choose the provider process;
- `haku/console/x/claude_code/` and `codex_app_server/` own native clients, frame vocabulary,
  projection state and `RuntimeAdapter` implementations;
- `HarnessFrame.frame` is exactly the JSON object the selected CLI wrote;
- harness identity is fixed out of band when the runner starts rather than repeated around every
  native message.

Codex is linked for projection and runner/client testing but is not deploy-launchable yet. There is
no Codex runtime resource configuration, sandbox namespace, credential, image packaging, access
profile edge or conversation writer. Those deployment choices can land separately without changing
the common bridge or turn loop.
