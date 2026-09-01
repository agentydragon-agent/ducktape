# Native wire examples

`//x/agentplane/capture:live_capture` runs one explicit Claude or Codex probe against a fresh
workspace. It records direct stdin/stdout/stderr JSONL and LiteLLM request/response bodies; the
proxy never writes HTTP headers. There is no artifact registry or promotion step.

The observed native wire records use UTF-8 `text` fields and LiteLLM records keep each UTF-8
request/response `body` as a JSON string. The current protocols are textual, so fixtures do not
carry redundant base64 or parsed-JSON copies.

The committed examples cover `baseline`, `shell`, `file_edits`, `steering`, `second_input`,
`interrupt`, `idle_resume`, `connection_retry`, `connection_exhaustion`,
`post_failure_follow_up`, and `post_exhaustion_follow_up` for both providers. The connection
examples are recorded only after real LiteLLM requests, never synthesized by the proxy.
`idle_resume` completes a seed turn, closes the native process, then resumes the saved native
session/thread from a new process. `connection_retry` closes a model stream at `message_start` and
records only native automatic recovery: request order, streaming mode, and monotonic proxy times.
`post_failure_follow_up` instead closes after a `text_delta`, waits for the first terminal native
frame, and only then supplies a separate user input. This distinction matters for Claude Code
2.1.252: it retries a drop before stream content, including one non-streaming retry after a response
has started, but after a visible text delta it returns an empty terminal result with no automatic
reconnect observed.

`connection_exhaustion` keeps closing each native recovery request until the client itself stops.
In the recorded versions, Claude Code 2.1.252 stops after 12 losses, produces a `result` with
`is_error: true` and `API Error: Connection dropped (ECONNRESET)`, and accepts a new user frame in
the same process afterward. Codex 0.144.1 stops after 26 losses, emits `turn/completed` with
`status: failed`, and accepts a new `turn/start` on the same thread afterward. The corresponding
`post_exhaustion_follow_up` fixtures preserve those recovery paths. Claude exposes no documented
retry control; these are raw version-specific wire observations, not Agentplane retry policy or a
compatibility matrix.

The recording proxy buffers only enough upstream data to identify complete SSE packets, then
forwards and records each packet. A configured loss occurs immediately after the named complete
SSE packet reaches the native client—not after an arbitrary socket read that happens to contain
the event name. For Anthropic messages, packet matching also recognizes the nested delta type
(such as `text_delta`) inside the native `content_block_delta` event.

Capture launches deliberately avoid host-specific prompt bulk: Claude uses safe mode with slash commands
disabled and only the four scenario tools, while Codex supplies a short app-server `baseInstructions` value.
This keeps fixtures about native protocol behavior rather than locally installed skills, plugins, or project
instructions.

```sh
bazel run //x/agentplane/capture:live_capture -- \
  --provider codex --scenario shell --binary /path/to/codex \
  --model cheap-model --endpoint http://litellm.example/v1 \
  --credential-file "$key_file" --workspace "$tmp/workspace" --output "$tmp/capture"
```

Pass `--replay-from x/agentplane/capture/testdata/<provider>/<scenario>` to run the same native scenario
against the recorded LiteLLM bodies rather than a live model endpoint. The credential stays in the
native process environment and is neither recorded nor inspected by the replay server.

`//x/agentplane/capture:test_native_replay` runs pinned Claude and Codex binaries in Bazel against
that loopback replay server. It asserts terminal native frames, ordered mock consumption, and a few
stable request-shape fields; it has no live credentials or external model dependency.
