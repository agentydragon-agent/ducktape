# A second harness, later

This note records the intentionally small seam for a future Codex harness. Codex is **not** a
production option in PR1.

`CliBackend` supplies only process bootstrap: a name, executable resolution, argv/cwd/environment
handling. The v3 runner does not inspect native payloads and has no `replayable()` hook. Every
`harness_frame` is retained and replayed by its opaque wire position, so Claude's stream deltas and
Codex's JSON-RPC notifications follow the same recovery path.

A future Codex change will add its own `CodexBackend`, launch builder, native Console protocol
client, projection, and deployment namespace. It must not add Codex branches to `runner.py`.
`HarnessFrame.frame` is exactly the JSON object the selected CLI wrote; harness identity is fixed
out of band when the runner starts rather than repeated around every native message.
