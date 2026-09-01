# Native harness capture

`//x/agentplane/capture:live_capture` is an explicit opt-in runner for direct
Claude stream/control and Codex app-server capture. It requires a fresh synthetic
workspace, explicit low-cost model/effort/call/token/spend limits, a `0600`
temporary `cheap-experiments` key file, endpoint, and output directory.

```sh
umask 077
# Write the approved temporary key to $key_file without printing it.
bazel run //x/agentplane/capture:live_capture -- \
  --provider codex --scenario launch_handshake \
  --codex-bin /path/to/codex --model chatgpt/oai-responses/gpt-5.6-luna \
  --effort low --max-calls 0 --max-tokens 256 --max-spend-usd 0.01 \
  --workspace "$synthetic_workspace" --artifact-dir "$capture_dir" \
  --endpoint http://litellm.litellm.svc.cluster.local:4000/v1 \
  --credential-file "$key_file"
```

The runner records no credential value, HTTP authorization header, cookie, or
oauth state. Fixtures can only be copied with `promote_bundle`, which validates
the exact artifact inventory, hashes, JSONL records, and a fail-closed scanner.
