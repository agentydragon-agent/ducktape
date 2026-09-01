# Native wire examples

`//x/agentplane/capture:live_capture` runs one explicit Claude or Codex probe against a fresh
workspace. It records direct stdin/stdout/stderr JSONL and LiteLLM request/response bodies; the
proxy never writes HTTP headers. There is no artifact registry or promotion step.

The committed examples cover `baseline`, `shell`, `file_edits`, `steering`, `second_input`,
`interrupt`, and `idle_resume` for both providers. `idle_resume` completes a seed turn, closes the
native process, then resumes the saved native session/thread from a new process. They are raw
protocol evidence, not a compatibility matrix.

```sh
bazel run //x/agentplane/capture:live_capture -- \
  --provider codex --scenario shell --binary /path/to/codex \
  --model cheap-model --endpoint http://litellm.example/v1 \
  --credential-file "$key_file" --workspace "$tmp/workspace" --output "$tmp/capture"
```

Pass `--replay-from x/agentplane/testdata/<provider>/<scenario>` to run the same native scenario
against the recorded LiteLLM bodies rather than a live model endpoint. The credential stays in the
native process environment and is neither recorded nor inspected by the replay server.

`//x/agentplane/capture:test_native_replay` runs pinned Claude and Codex binaries in Bazel against
that loopback replay server. It asserts terminal native frames, ordered mock consumption, and a few
stable request-shape fields; it has no live credentials or external model dependency.
