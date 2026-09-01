# Agentplane experiments

Status: **focused experiment plan**.

The first experiment is not a control-plane validation suite. It answers one practical question:
can a small bridge reliably drive native Claude Code and Codex processes, including the interactions
we need, while recording the upstream LLM exchanges that made them happen?

## P0 questions

For both providers, establish:

1. how to launch and initialize the native process;
2. how a normal prompt is submitted and how streamed output terminates;
3. how tool calls and tool results appear on the native wire;
4. how upstream model requests and streamed responses map to the native exchange;
5. whether steering exists and where it is accepted;
6. how interruption is requested and what native terminal evidence follows; and
7. how the unchanged native harness behaves when one active upstream LLM stream is lost and the
   model endpoint becomes reachable again; and
8. whether a completed turn can be resumed after killing only the idle native process.

The capture may use provider-native ids directly. It does not need to invent Thread, Turn, Input, or
runtime-generation ids before the providers' behavior is understood.

## P1 questions, deferred

Do not block the P0 capture on:

- multiple pending prompts and native dequeue semantics;
- active-turn process death and side-effect reconciliation;
- central-server reconnect or bridge-log replay;
- Pod replacement, Sandbox suspension, PVC lifecycle, or Service topology;
- PostgreSQL persistence and common timeline projection;
- leases, fencing, authentication, mTLS, approvals, credentials, or subscription adapters.

Those are control-plane experiments after the native driving seam works. A P0 driver may record a
simple failure or unsupported result, but it should not implement these systems to obtain one.

## Code and fixture shape

Keep the implementation under `x/agentplane/capture/` and keep provider scenario code separate.
A small shared process/transcript helper is appropriate; a shared protocol state machine is not.

Each scenario fixture should contain only:

```text
metadata.json
native.jsonl
llm.jsonl
stderr.log
expected.json
workspace/              # only when the scenario has a workspace effect
```

`native.jsonl` is an ordered transcript of complete native frames with direction and exact payload.
`llm.jsonl` is an ordered transcript of model request bodies and streamed response chunks.
`expected.json` is hand-authored and states the behavior the test is intended to prove. File order is
sufficient ordering; do not add hashes, lengths, timestamps, process generations, or manifest
inventories.

## Capture rules

- Use real native stdin/stdout pipes, never a PTY or terminal scraper.
- Drain stderr so it cannot block the child; preserve a useful failure log, not a forensic event
  stream.
- Capture model bodies through a minimal local HTTP server/proxy. Never serialize headers, cookies,
  environment variables, or credentials.
- Use a synthetic workspace and deterministic tool inputs.
- Use native events or explicit test synchronization for steering and interrupt races, not sleeps
  as the only evidence.
- Keep process exit status and the relevant failure message; omit PID, signal chronology, digests,
  and Kubernetes identity from fixtures.
- Do not blindly redispatch an input after uncertain process death.
- Treat unavailable binaries or unsupported provider operations as an explicit test skip/result, not
  as a reason to grow a compatibility framework.

## P0 scenario matrix

| Scenario               | Claude  | Codex   | Evidence required                                               |
| ---------------------- | ------- | ------- | --------------------------------------------------------------- |
| launch/handshake       | yes     | yes     | native initialization exchange                                  |
| baseline streamed turn | yes     | yes     | prompt, streamed output, terminal result, model exchange        |
| tool interaction       | yes     | yes     | native tool call/result, model requests, expected effect        |
| steering               | attempt | attempt | accepted behavior or explicit unsupported result                |
| interrupt              | attempt | attempt | request plus actual native terminal evidence                    |
| upstream reconnect     | attempt | attempt | retry/reconnect requests, duplicate output, process/outcome     |
| idle native resume     | attempt | attempt | native session/thread continuity or explicit unsupported result |
| fake-model replay      | yes     | yes     | real harness driven from saved model exchange                   |

The first useful fixture set can be one baseline/tool/replay capture per provider. Do not generate a
fixture for every possible failure window before the core loop is working.

For the upstream reconnect scenario, use one controlled cut after a valid partial assistant-content
chunk and before terminal completion. Keep the harness process and native stdio connection alive;
restore model-endpoint availability and observe rather than forcing a retry. Record the exact model
request/chunks before loss, a minimal transport-loss marker, any subsequent request/chunks, native
frames, bounded stderr, process survival, duplicated partial output, and terminal outcome.

This is model-API transport behavior, not provider-native resume, central/bridge reconnect, or Input
redispatch. Start without tools so a retry cannot repeat side effects. A result of immediate failure,
retry then failure, successful retry, or explicit environment blocker is all useful provider evidence.

## Real-harness replay test

This is a P0 deliverable, not a future TODO:

1. start a deterministic fake Anthropic Messages or OpenAI Responses server;
2. load a saved `llm.jsonl` exchange;
3. launch the real Claude or Codex binary;
4. drive its native protocol through the provider driver;
5. return the recorded model chunks from the fake server; and
6. assert the model requests, native output, tool I/O, terminal result, and workspace effect.

The fake server should support the smallest needed set of request/response shapes first. Add tool
calls, streaming, errors, or malformed responses only when a scenario tests them. The purpose is to
prove the bridge/harness loop, not to emulate all of either provider's HTTP API.

Keep the real-provider capture and fake-model replay as separate evidence:

- real-provider capture shows what the deployed route and binary actually do;
- fake-model replay shows that the driver can reproduce and test the interaction without paid
  inference or network access.

## Native resume test

Use a random in-memory nonce in a completed no-tool turn. Ask the harness to remember it without
writing it to the workspace. Kill only the idle native child, start a new child using the provider's
native resume mechanism, and ask for the nonce.

The test must distinguish:

- provider-native context recovery;
- workspace file survival; and
- starting a new unrelated conversation.

Do not treat a bridge journal cursor or a replayed prompt as native resume.

## Provider-specific notes

Claude uses newline-delimited stream/control JSON. Capture initialization, user frames, command
lifecycle, assistant/tool frames, terminal results, and the native interrupt response. A second user
frame during an active turn may be ordinary queued input rather than steering; record the observed
behavior instead of assigning it a common meaning.

Codex app-server uses newline-delimited JSON-RPC-shaped messages. Capture `initialize`,
`initialized`, thread start/resume, turn start, item notifications, turn completion, `turn/steer`,
and `turn/interrupt` where available. The driver must handle server requests that are actually
needed by the tested scenario rather than assuming stdout contains notifications only.

Provider-native ids stay in the transcript. Do not duplicate them into a future common envelope in
this experiment.

## Tests and gates

Ordinary Bazel tests should:

- parse frames across partial reads;
- replay native transcripts in order;
- replay model transcripts through the fake server;
- run hand-authored assertions against both sides of the exchange; and
- verify that capture code does not import `haku/*`.

Opt-in live tests should run the real binaries and use a finite call/time budget. They must not
perform credentials, Kubernetes mutations, or arbitrary network access beyond the configured model
endpoint.

Use the repository's normal secret checks and a small fixture guard for obvious serialized headers
or token prefixes. Do not create a custom entropy-based promotion pipeline.

## After P0

Only once both providers have useful captures should we decide whether a common adapter needs
`submit`, `steer`, `interrupt`, `resume`, or queue operations, and which state belongs in PostgreSQL.
Then run narrowly targeted experiments for the specific failure or lifecycle behavior that the
product actually needs. Keep unsupported provider behavior visible instead of expanding the first
implementation to make the matrix look complete.
