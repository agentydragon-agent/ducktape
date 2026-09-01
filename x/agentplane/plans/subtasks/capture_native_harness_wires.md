# Capture native Claude Code and Codex wires

Status: **implementation subtask**. This task must deliver working code **and committed real capture
bundles**, not only design notes or documentation.

## Goal

Build a standalone capture harness under top-level `x/agentplane/` that launches recent
installed or otherwise resolved Claude Code and Codex app-server binaries, drives each native
machine protocol directly, records exact bidirectional evidence, and promotes safe captures into
deterministic Bazel regression fixtures. This slice discovers the protocols; it does not implement
the provider-neutral facade or common operation projection that later design will derive from the
captures.

This is a new Harness Control Plane implementation seam. It is deliberately outside the Haku package
root and must not import, wrap, or assume implementation details from `haku/console`, `haku/runner`,
or other `haku/*` code. Those paths and the existing Harness Control Plane documents are
**evidence/reference only**. Implement the subprocess ownership, provider drivers, capture formats,
proxy, scanner, replay, and tests under `x/agentplane/`.

## Required deliverables

Add implementation and tests with a layout equivalent to:

```text
x/agentplane/
  BUILD.bazel
  capture/
    __init__.py
    main.py                     # live scenario CLI
    binary_resolution.py        # explicit path/PATH/resolved package discovery
    process.py                  # process-group lifecycle and exact pipe capture
    records.py                  # schemas, sequence allocation, hashes, JSON wrappers
    artifacts.py                # run bundle assembly, validation, and promotion
    credential_boundary.py      # inert-placeholder or exact temporary-grant setup
    llm_recording_proxy.py      # header-blind request/stream recorder and forwarder
    workspace.py                # isolated workspace snapshots and diffs
    secret_scan.py              # fail-closed promotion scanner
    providers/
      shared_capture.py         # byte/process/artifact mechanics only
      claude/
        driver.py               # explicit stream/control JSON helpers
        scenarios/              # Claude-specific scenario bodies
      codex/
        driver.py               # explicit app-server JSON-RPC helpers
        scenarios/              # Codex-specific scenario bodies
    fixtures/
      operation_probe.py
      structured_tool_server.py
    tests/
      ...
  testdata/
    claude/<capture-set>/<scenario>/...
    codex/<capture-set>/<scenario>/...
```

The exact module split may change, but preserve these ownership boundaries. Provide:

- a Bazel live-run entry point with explicit provider, scenario, binary, model, workspace, artifact
  directory, budget, and credential-delivery arguments;
- real Claude and Codex subprocess drivers using native stdin/stdout protocols, never a PTY, tmux,
  pane scrape, or terminal prompt heuristic;
- explicit `<harness> x <scenario>` tests that show the exact JSON written/read and may use native
  request/session/thread/turn ids where the protocol requires them;
- exact raw run bundles and promoted in-repository fixtures;
- a recording proxy for correlated upstream model traffic;
- a promotion validator and fail-closed secret scanner;
- offline fixture replay and assertion tests that run without credentials, network, Kubernetes, or
  installed harness binaries; and
- a short operator README or CLI `--help` generated from the implementation, including live-run and
  promotion commands. Do not satisfy this item by adding a second design-only document in place of
  code and captures.

Share recording, process control, artifact writing, scanner, workspace, and proxy mechanics.
Deduplicate scenario logic only when the same helper is demonstrably correct for both protocols and
does not obscure the sequence of native requests, ids, acknowledgements, or races. Test code that is
test-driving an unknown protocol should prefer explicit, legible duplication over a premature
facade.

## Binary discovery and compatibility

Support `--claude-bin` and `--codex-bin` overrides. Otherwise resolve the current executable from the
configured toolchain/PATH or a documented package-resolution target. The live runner must use the
resolved executable itself, not a Haku runner image or wrapper.

For every launch, record when available:

- requested command name, resolved real path, file digest, size, and executable metadata;
- self-reported version and package-manager metadata;
- sanitized argv, working directory, OS/architecture, and relevant non-secret environment allowlist;
- provider protocol/capability response; and
- resolver method and package lock/integrity metadata when a package was downloaded.

Versions are evidence, not a launch allowlist. Record known versions and capability differences, but
do **not** hard-fail only because a version is newer, older, or unknown. Handshake/schema/capability
failures may make a scenario `unsupported` or `fail`; version-string mismatch alone may not. Never
silently attribute observations from one binary digest to another.

## Credential and network boundary

Live provider scenarios must use the recently merged `cheap-experiments` LiteLLM virtual-key policy
through one of the already selected Haku Console delivery paths:

1. the existing exact, operator-approved temporary grant; or
2. the existing inert-placeholder plus egress-fence substitution path.

Do not invent another secret-distribution mechanism. The runner may receive the scoped virtual key
through the approved temporary-grant path when the egress-fence placeholder path is unavailable, but
credential plumbing must keep it out of argv and outside every capture/log/exception/manifest path.
The capture code must never read a Kubernetes Secret object, consumer OAuth state, or CLIProxyAPI
login files. An exact temporary grant still follows the ordinary Haku Console approval path and
remains narrowly scoped to the approved origin/method/path and cheap-model policy.

The manifest records only:

- `credential_delivery: temporary_grant | egress_fence`;
- the non-secret virtual-key policy identifier;
- the LiteLLM/CLIProxyAPI route family and endpoint origin;
- grant id and expiry if safe to disclose; and
- proxy/config digests and selected model/effort/budget.

Consumer authentication and refresh remain owned by CLIProxyAPI. No capture scenario performs login.

## Exact capture contract

Use one run-wide monotonically increasing capture sequence plus stream-local sequences. Append and
flush each event before interpreting it for scenario control. Clocks include wall time and monotonic
nanoseconds. No raw fixture record may be truncated, rewritten, canonicalized, or reconstructed from
a parsed object.

### Provider-specific scenario drivers

The live capture suite deliberately speaks Claude stream/control and Codex app-server JSON-RPC
directly. It records each scenario action before writing the corresponding native frame. Native
Claude UUID/session ids and Codex JSON-RPC/thread/turn/item ids may appear in scenario code and
assertions because their routing and lifecycle semantics are exactly what this phase is learning.

Do not implement `start_thread`, `resume_thread`, `submit`, `steer`, `cancel_input`, common
Turn/operation ids, `common.event`, or `provider_debug` merely to run these captures. Do not generate
a common timeline. Preserve unknown frames and native ids exactly, and make provider-specific
assertions directly against the raw protocol, process/workspace evidence, and correlated upstream
traffic.

The captures must leave enough evidence for the next design pass to decide:

- whether each provider owns a prompt queue;
- what happens when an ordinary non-steering prompt arrives while a run is active;
- whether an orchestrator or bridge/runner queue is required instead;
- the observable write, admission, dequeue, delivery, and terminal boundaries;
- how native steering differs from ordinary prompt submission; and
- which queue ownership and neutral behavior both harnesses can tolerate without double buffering.

For Claude, “ordinary prompt while active” and “intended steering” may use the same user-frame shape.
Keep them as separate named scenarios anyway. Record the test intent and exact timing, then let the
native lifecycle evidence show whether the distinction exists on the wire or only at the future
control-plane policy layer.

### Native stdin/stdout

Capture every complete native frame in both directions:

- exact bytes, including the original line delimiter when present, stored as base64;
- byte length and SHA-256;
- direction (`harness_stdin` or `harness_stdout`), process generation, stream sequence, and run
  sequence;
- exact write/read and frame-boundary metadata, including a final unterminated frame at EOF;
- a UTF-8 diagnostic view when decoding succeeds; and
- a parsed-JSON wrapper when parsing succeeds.

Raw bytes are authoritative. Replay and validation must decode the base64 bytes and parse them again;
the stored parsed form is an indexed/diagnostic derivative and must be checked against the raw bytes.
Preserve unknown, malformed, oversized, and non-JSON frames rather than dropping them.

JSONB null safety is mandatory. A parsed value is never stored directly in a nullable JSONB field.
Use a non-null wrapper such as:

```json
{ "state": "parsed", "value": null }
```

or, for non-JSON data:

```json
{ "state": "not_json", "error": { "kind": "decode_error", "offset": 17 } }
```

The wrapper object itself is always present and non-null. This makes JSON `null` distinguishable
from SQL `NULL`. Database/import tests must assert this invariant. The exact raw bytes remain the
source of truth if the wrapper, decoder, or future schema disagrees.

### Stderr and process lifecycle

Drain stderr independently so it cannot block the child. Store exact stderr chunks with base64,
length, digest, timestamps, process generation, and an optional decoded view. Record without
inference:

- spawn requested/succeeded/failed;
- PID, process-group/session identity, executable digest, and sanitized launch metadata;
- stdin writes/close/broken pipe, stdout/stderr EOF, and drain completion;
- every signal requested and delivered, escalation deadline, and target PID/process group;
- graceful shutdown, interrupt, forced kill, observed exit code or signal, and wait status;
- child replacement/resume generation; and
- cleanup failures or surviving descendants.

The runner must be able to signal only the native child process group while leaving the capture
controller alive. Scenario control must choose kill points from captured structured events or safe
workspace markers, not sleeps alone.

### Upstream LLM HTTP traffic

Route each real harness's model traffic through a local recording reverse proxy and then through the
approved LiteLLM route. Capture:

- exact request method, path/query, body bytes, body digest, and parsed JSON wrapper;
- request acceptance/forwarding/completion/error timestamps and retry/attempt number;
- exact streamed response transport chunks and reconstructed SSE/JSON event frames, each with raw
  base64, lengths, digests, ordering, and parsed wrappers;
- non-streamed response bodies in the same form;
- HTTP status, safe content type/encoding metadata, usage, finish reasons, and route metadata when
  present in bodies; and
- a capture request id correlated to run, provider, native process generation, scenario action,
  relevant native ids when known, and the corresponding response stream.

Correlation must be explicit and machine-validated. If a provider request cannot be tied more
precisely than “the sole active native execution in process generation N”, record that basis; do
not fabricate an identifier.

The recorder must be **header-blind by construction**: forwarding code may receive headers long
enough to proxy them, but the capture/event path accepts only an allowlist such as content type and
content encoding. It must reject attempts to record or serialize `Authorization`, `Proxy-Authorization`,
`Cookie`, `Set-Cookie`, API/client keys, OAuth tokens, or arbitrary headers. Do not first persist a
full header map and redact later. Exceptions and debug logging follow the same rule. Request and
response bodies/chunks are in scope; auth headers, cookies, and OAuth material are not.

### Workspace evidence

Every scenario runs in a newly generated synthetic workspace, never the Ducktape checkout, a personal
workspace, or an Agent memory directory. Record before/after snapshots with:

- relative path, type, mode, size, digest, and symlink target;
- exact file bytes for bounded scenario-owned files, represented as base64;
- a deterministic tree digest and machine-readable added/removed/changed diff; and
- explicit exclusions for provider state directories, capture output, sockets, and transient caches.

Include a deterministic operation probe with `echo`, `count`, `wait`, and `fail` modes. `count` must
make duplicate execution observable. Workspace snapshots and model-context continuity are separate
assertions.

## Run bundle and fixture format

A live run first lands in a restricted temporary output directory. A self-contained bundle contains
at least:

```text
manifest.json
native-stdin.frames.jsonl
native-stdout.frames.jsonl
native-stderr.chunks.jsonl
process-events.jsonl
scenario-actions.jsonl
llm-requests.jsonl
llm-response-chunks.jsonl
llm-responses.jsonl
correlation.jsonl
workspace-before.json
workspace-after.json
workspace-diff.json
assertions.json
summary.md
SHA256SUMS
```

`manifest.json` includes the binary and launch metadata above plus:

- repository commit and dirty state;
- run/scenario ids, seed, prompt/tool fixture versions, and capture schema version;
- model, effort, route, budgets, measured usage/cost, and explicit reroutes;
- credential-delivery metadata permitted above;
- proxy version/config digest;
- all process generations, an inventory of native ids found in exact frames, and kill/recovery
  points;
- Kubernetes/Sandbox/Pod/PVC identities when applicable;
- each artifact's size, hash, record count, first/last sequence, and derivation status;
- scenario result: `pass`, `fail`, `unsupported`, or `inconclusive`, with evidence references; and
- scanner version, rule-set digest, outcome, and promotion timestamp.

Promoted fixtures live under
`x/agentplane/testdata/<provider>/<capture-set>/<scenario>/` and retain the exact accepted raw
files unchanged. Do not hand-edit ids, timestamps, chunks, malformed records, or bodies to make tests
pass. Derived summaries are clearly labeled and reproducible from raw records. Common projections
are not part of this slice.

## Fail-closed promotion and secret scanning

Promotion is a command, not a manual copy. It must:

1. validate every expected file and reject unexpected files;
2. verify schemas, sequences, hashes, cross-stream correlations, and manifest inventory;
3. decode and scan every raw/base64 payload, nested JSON string, SSE event, workspace file, stderr
   chunk, summary, and manifest value;
4. reject forbidden field names and values, authorization/header material, cookies, bearer/basic
   credentials, JWTs, API/client keys, OAuth access/refresh/session tokens, private keys,
   signing/webhook secrets, known private workspace/Agent identifiers, unexpected personal text,
   and unknown high-entropy credential-shaped values;
5. reject unknown schema fields, undecodable base64, unscanned bytes, scanner errors, partial scans,
   and scanner timeouts;
6. rerun offline replay and independently authored assertions from the raw bytes; and
7. copy the bundle unchanged only after all gates pass, then regenerate and verify `SHA256SUMS`.

The scanner must fail closed and must not print the candidate secret. A failure does not trigger
best-effort redaction or allow promotion; fix isolation/capture and rerun. Add positive and negative
tests, including credentials hidden in nested JSON, escaped strings, SSE data, base64, stderr,
workspace files, JWT-like strings, and forbidden header names. Include canary fixtures that prove the
scanner examines decoded base64 and all advertised artifact files.

## Required scenario matrix

Implement every scenario for both providers unless it is genuinely provider- or environment-specific.
Each attempt emits a complete bundle and explicit machine-readable outcome. `unsupported` requires
captured capability/error evidence; a missing implementation is not `unsupported`.

| Scenario                       | Required behavior and evidence                                                                                                                                                                                                                                                                   |
| ------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `launch_handshake`             | Resolve binary, launch, initialize, record capabilities/version, and exit without model inference where possible.                                                                                                                                                                                |
| `baseline`                     | One fixed no-tool prompt, native admission, streamed response, terminal result, and one correlated upstream model exchange.                                                                                                                                                                      |
| `shell`                        | Run deterministic success, failure, stdout, and stderr commands; preserve exact provider-native lifecycle and tool output.                                                                                                                                                                       |
| `file_edits`                   | Read, create, patch/edit, and re-read synthetic files; assert exact workspace diff, exact native frames, and no changes outside the workspace. No common file projection is required.                                                                                                            |
| `structured_tools`             | Invoke a deterministic local structured tool with nested arguments and a JSON-null value; capture native call/result and upstream tool-use traffic.                                                                                                                                              |
| `steering`                     | Send input during an active turn, correlate provider-specific admission, and race steering against completion.                                                                                                                                                                                   |
| `normal_submit_while_active`   | Send the provider's ordinary non-steering prompt request/frame during an active run; observe whether the harness rejects, queues, or later admits it and whether multiple prompts preserve order.                                                                                                |
| `dequeue_pending_input`        | Investigate documented/discovered native dequeue or cancellation before admission and after admission. Distinguish a native dequeue from merely withholding a request not yet written by the test driver.                                                                                        |
| `interrupt_with_queued_input`  | Interrupt an active Turn with one or more pending normal/steering inputs and record the independent fate of every input.                                                                                                                                                                         |
| `interrupt`                    | Interrupt a deterministic active wait; record control request/result, process/tool state, terminal native evidence, and completion race.                                                                                                                                                         |
| `kill_idle_resume`             | Complete a memory nonce run, kill only the idle native child, invoke the provider's native resume path with its captured session/thread id, and ask for the nonce.                                                                                                                               |
| `kill_active_reconcile_resume` | Kill the child after an observable side effect but before completion; inspect native history/workspace before any follow-up, resume, reconcile outcome honestly, and prove no implicit duplicate execution.                                                                                      |
| `pod_replacement`              | When an approved Kubernetes/Agent Sandbox backend is available, replace the Pod while retaining scenario PVC state; record changed Pod UID, retained PVC/workspace, and harness-Thread resume separately. Otherwise emit a locally retained `unsupported` run, not a passing repository fixture. |

Use low-cost, fixed prompts and strict per-run call/token/spend ceilings. A scenario must refuse an
implicit default model or unbounded budget.

### Claude-specific cases

At minimum cover:

- stream-JSON input/output launch and correlated `initialize` control response;
- UUID-stamped user frames and command-lifecycle/admission evidence;
- partial `stream_event` deltas plus completed assistant/tool blocks;
- built-in shell/read/write/edit behavior and one deterministic structured tool path;
- another UUID-stamped user frame during a tool wait, during prose if observable, and near terminal
  result, without assuming in advance whether Claude treats it as steering or an ordinary queued
  prompt;
- normal user-frame submission while active, multiple pending inputs, dequeue/cancel lifecycle if
  exposed, and queued-input fate across interrupt/process death;
- correlated interrupt control request versus actual terminal evidence;
- provider session identity and cold resume after idle and active child death; and
- unknown/malformed system, lifecycle, compaction, rate-limit, and control frames preserved raw.

Do not call runner-journal replay “Claude resume”. The nonce must not be written to the workspace or
prompt metadata used for the follow-up.

### Codex-specific cases

At minimum cover:

- `codex app-server --listen stdio://` and the exact `initialize` response / `initialized`
  notification ordering;
- durable, non-ephemeral `thread/start`, recorded thread id, `thread/read`, and `thread/resume`;
- `turn/start` request/response, `turn/started`, item/delta notifications, and `turn/completed`;
- concurrent JSON-RPC ids and at least one app-server-to-client request or deterministic structured
  dynamic-tool interaction, with a correlated client response;
- direct native `turn/steer`, including its race with completion;
- direct native `turn/start` while another turn is active, multiple pending requests, any
  app-server/internal queue behavior, and any native cancellation/dequeue surface;
- `turn/interrupt` targeted to the active thread/turn versus actual terminal evidence;
- command/file-change item lifecycles and output deltas;
- idle and active app-server death followed by explicit history reconciliation before any new turn;
  and
- unknown notifications, optional `jsonrpc`, JSON `null`, malformed lines, and EOF preserved raw.

Do not use ephemeral threads as evidence of cold resume, and do not synthesize cancellation merely
because an interrupt RPC returned.

## Replay and Bazel tests

Provide hermetic Bazel targets for at least:

- record schema and JSONB-null-wrapper validation;
- exact base64/hash round trips for stdin, stdout, stderr, HTTP bodies, and stream chunks;
- Claude and Codex framing from arbitrary read chunk boundaries, malformed lines, JSON `null`, and
  unterminated EOF frames;
- offline request/response correlation and lifecycle reconstruction;
- deterministic workspace snapshot/diff;
- fixture manifest inventory and whole-bundle hashes;
- fail-closed scanner positive/negative/canary cases;
- provider-specific offline replay of every promoted scenario; and
- a guard proving production capture/replay targets have no dependency or import from `haku/*`.

Offline replay must feed accepted raw stdin/stdout fixtures through the new parsers in original
order, regenerate derived views, and evaluate independently authored assertions. It must not trust
stored parsed wrappers as the oracle. Ordinary `bazel test` must perform no network access, paid
inference, grant request, Pod mutation, or binary download.

Live scenarios are explicit opt-in `bazel run` targets. Destructive variants print the exact child or
Pod target and require a dedicated acknowledgement flag in addition to any external approval.

## Later TODO: harness-in-the-loop fake LLM test

After the real-capture slice works, add a tracked TODO for a hermetic harness-in-the-loop test. It
will start a deterministic fake Anthropic Messages/OpenAI Responses server, route **both real
harness binaries** through it, and drive fixed streamed model traffic through the real Claude and
Codex agent loops. The test must assert both sides of the loop:

- the exact LLM requests each harness sends, including tool schemas, conversation/history, tool
  results, retries, and follow-up requests; and
- the exact native runner-protocol responses each harness emits on stdin/stdout after consuming the
  fake model chunks.

The fake server must support deterministic streaming, tool calls/results, JSON `null`, malformed or
interrupted streams, and controlled retry/error responses. Keep this as a later TODO rather than
using a fake model as a substitute for the real cheap-provider captures required by this task.

## Acceptance criteria

The task is complete only when all of the following are true:

1. `x/agentplane/` contains standalone working capture code and no production dependency or
   import from `haku/*`.
2. The live runner launches resolved real Claude Code and Codex app-server binaries and records their
   actual version/path/digest without a version hard gate.
3. Every required local scenario is implemented for both providers and produces a complete bundle;
   Pod replacement runs when the approved backend is available and is otherwise honestly reported.
4. At least one scanner-approved, exact raw fixture bundle for **each provider and each implemented
   scenario** is committed under `x/agentplane/testdata/`; no fixture contains credentials,
   personal workspace data, auth headers, cookies, or OAuth material.
5. Native stdin and stdout are both complete and byte-exact, stderr and lifecycle events are present,
   and every parsed JSON value uses the non-null wrapper with raw bytes authoritative.
6. Each inference scenario has correlated exact upstream request body and streamed response
   body/chunk evidence captured at a boundary that cannot persist auth headers or cookies.
7. Idle resume proves provider-native session/thread continuity separately from workspace survival;
   active-death recovery records uncertainty and never blindly replays a side-effecting prompt.
8. Manifest hashes, sequences, correlations, workspace snapshots, and assertions validate from a
   clean checkout.
9. The fail-closed scanner demonstrably catches seeded secrets in every artifact representation and
   blocks promotion on unknown/unscanned data or scanner failure.
10. Bazel offline replay and fixture tests pass with network disabled and without provider binaries
    or credentials.
11. Live runs enforce explicit cheap model/effort and finite call/token/spend budgets, and record the
    approved credential-delivery mode without exposing the credential.
12. The later fake-LLM harness-in-the-loop test is recorded as a concrete TODO with the two-sided
    request/native-response assertions above.
13. Scenario code is organized as an explicit `<harness> x <scenario>` matrix and shows the native
    Claude/Codex JSON, request/session/thread/turn ids, ordering, and assertions it exercises.
    Shared helpers do not hide protocol-specific behavior, and no common facade or operation
    projector is required.
14. Ordinary non-steering prompt submission while active, native targeted steering where available,
    dequeue/cancel discovery, completion races, interrupt-with-queued-input, and queue survival
    across process death are captured separately for both providers.

A PR containing only this brief, generated schemas, hand-authored example JSON, or reduced summaries
without working live capture code and real accepted bundles does **not** satisfy the task.
