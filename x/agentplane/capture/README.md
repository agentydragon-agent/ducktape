# Native wire capture harness

**Status:** implementation and fixtures are present; behavioral native replay coverage is ready for the focused gate.

`//x/agentplane/capture:live_capture` runs one explicit Claude or Codex probe against a fresh
synthetic workspace. It drives the real native process over structured JSON on direct stdin/stdout
pipes, drains stderr, and records the native exchange plus upstream LiteLLM request/response bodies.
It is a discovery harness for provider behavior, not the Agentplane service, a generic runner, or a
provider-neutral protocol.

## Scope and acceptance

The capture task is complete enough to support the next Agentplane slice when the following evidence
is present for both providers, or an explicit provider-specific unsupported/environment-blocked result
is recorded:

- real binary launch and native handshake;
- one streamed baseline turn;
- one deterministic shell or file-edit tool interaction with native tool I/O and expected workspace effect;
- steering and interruption behavior;
- native session/thread resume after killing only an idle native process;
- upstream connection-loss behavior with the native harness process kept alive; and
- deterministic fake-model replay through the real native binary, asserting upstream requests and native output.

The committed examples cover `baseline`, `shell`, `file_edits`, `steering`, `second_input`,
`interrupt`, `idle_resume`, `connection_retry`, `connection_exhaustion`,
`post_failure_follow_up`, and `post_exhaustion_follow_up` for both providers. These are provider
captures, not a compatibility matrix or an Agentplane retry policy.

## Evidence format

Each capture output keeps the evidence boring and inspectable:

```text
metadata.json          # provider, scenario, model/version context
stdin.jsonl            # ordered native frames written to the process
stdout.jsonl           # ordered native frames read from the process
stderr.jsonl           # bounded diagnostics
llm-requests.jsonl     # ordered upstream request bodies
llm-responses.jsonl    # ordered upstream response chunks and loss markers
testdata/<provider>/<scenario>/  # committed replay inputs
```

Native and upstream payloads are stored as UTF-8 text because these protocols are textual. The
recording boundary excludes HTTP headers, cookies, environment variables, OAuth state, credentials,
and private user data. Do not add redundant base64, parsed-JSON copies, hashes, lengths, timestamps,
manifest inventories, or a promotion/DLP framework.

Live capture output includes the native stdin/stdout/stderr files shown above. Committed
`testdata/<provider>/<scenario>/` replay inputs currently retain only `llm-requests.jsonl` and
`llm-responses.jsonl`; the native logs remain disposable capture output rather than test inputs.

`expected.json`-style semantic expectations belong in hand-authored tests, not generated from the
observed output. Provider-native request/session/thread/turn ids remain in the provider evidence.
The harness deliberately does not invent Thread, Turn, Input, runtime-generation, retry, or common
operation ids.

## Scenario notes

`idle_resume` completes a seed turn, closes the native process, then resumes the saved native
session/thread from a new process using Claude `--resume` or Codex `thread/resume`. This proves
provider-native continuity, not transcript replay or prompt redispatch.

The connection examples isolate model-API transport behavior from tools. `connection_retry` closes a
model stream at a named complete SSE packet and records native automatic recovery. `post_failure_follow_up`
closes after a visible text delta, waits for the first native terminal frame, and only then sends a
separate user input. `connection_exhaustion` repeats controlled losses until the client stops, while
`post_exhaustion_follow_up` records whether the same process accepts another input afterward.

The recorded captures show provider-specific behavior: Claude Code can retry before visible
stream content but, after a visible text delta, returns an empty terminal result with no automatic
reconnect observed; Codex retries and eventually reports a failed turn after repeated losses. These
are raw observations, not semantics the bridge should manufacture.

The native replay gate is split into provider-specific tests, with shared pytest setup in
`replay_fixtures.py` and provider-specific tests/fixtures/assertions under
`providers/{claude,codex}/`. It uses scenario-specific behavioral assertions rather than requiring
every packet or generated field to match. It checks the lifecycle that matters to each behavior: tool item
opening/progress/completion and workspace effects, steering or queued-input delivery, interruption
and terminal state, provider retry notices and retry exhaustion, same-process follow-up recovery,
native resume, and expected assistant output. During a live capture, complete native and upstream
payloads can be retained as ordered investigation evidence, including volatile request bodies and
provider-specific IDs, but they are not used as a brittle byte-for-byte oracle or kept as permanent
Git fixtures.

## Prompt and environment isolation

Capture launches avoid host-specific prompt bulk. Claude uses safe mode with slash commands disabled,
only the four scenario tools, and empty settings sources. Codex supplies a short app-server
`baseInstructions` value and disables unrelated instruction blocks. This keeps fixtures about native
protocol behavior rather than locally installed skills, plugins, or project instructions.

The upstream recording proxy buffers only enough data to identify complete SSE packets, then forwards
and records each packet. A configured loss occurs immediately after the named complete packet reaches
the native client, including nested Anthropic delta types such as `text_delta`; it is not triggered by
an arbitrary socket read boundary.

## Run a live capture

```sh
bazel run //x/agentplane/capture:live_capture -- \
  --provider codex --scenario shell --binary /path/to/codex \
  --model cheap-model --endpoint http://litellm.example/v1 \
  --credential-file "$key_file" --workspace "$tmp/workspace" --output "$tmp/capture"
```

The live capture uses a finite model-call ceiling and timeout. The credential is supplied to the
native process only for the configured experiment and is neither recorded nor inspected by the replay
server. No capture path uses a PTY, tmux, terminal scraper, prompt heuristic, Kubernetes mutation, or
`kubectl exec` protocol path.

## Replay through the real harness

```sh
bazel test //x/agentplane/capture:test_native_replay
```

The replay test runs pinned Claude and Codex binaries against a loopback server loaded from the saved
LiteLLM bodies. It asserts terminal native frames, ordered mock consumption, and stable request-shape
fields without live credentials or an external model dependency.

For the live-capture entry point, pass
`--replay-from x/agentplane/capture/testdata/<provider>/<scenario>` to serve the saved upstream
exchange instead of calling the live endpoint. Replay does not resend an uncertain user Input; it
replays only the captured model exchange through the native harness.

## Deliberately out of scope

This harness does not implement:

- the shared Agentplane stdio protocol or a neutral operation projector;
- Thread/Input/Turn persistence, PostgreSQL, or a user-facing timeline;
- Kubernetes/Agent Sandbox reconciliation, Services, suspension, or Pod replacement;
- bridge reconnect cursors, leases, fencing, or automatic uncertain-input retry;
- credentials, OAuth ownership, approval policy, subscriptions, or external-event adapters; or
- artifact registries, generated summaries, integrity manifests, or custom DLP/promotion machinery.

Those are separate work packages in the [Agentplane task DAG](../plans/task_dag.md). The capture
fixtures and tests are the behavioral evidence the shared protocol and adapters must consume next,
not a framework to expand before the evidence is understood.
