# Native wire examples

`//x/agentplane/capture:live_capture` runs a single explicit Claude or Codex probe against a
fresh workspace. It records only direct stdin/stdout/stderr JSONL plus LiteLLM request and
response bodies; the proxy never records HTTP headers. The checked-in `testdata/` directories
are small, scanner-reviewed examples—not a fixture framework.

```sh
bazel run //x/agentplane/capture:live_capture -- \
  --provider codex --scenario shell --binary /path/to/codex \
  --model cheap-model --endpoint http://litellm.example/v1 \
  --credential-file "$key_file" --workspace "$tmp/workspace" --output "$tmp/capture"
```
