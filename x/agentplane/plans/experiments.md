# Agentplane experiments

Status: **capture implementation and fixtures are integrated; behavioral replay verification and the
thin shared adapter seam are next**.

The native capture work is no longer an open discovery task. PR #15's Claude/Codex drivers, live
capture scripts, scenario fixtures, and replay harness are integrated under [`../capture/`](../capture/).
The provider-specific native replay tests now contain behavioral coverage for every checked-in
provider/scenario replay fixture, with shared pytest setup in `../capture/replay_fixtures.py` and
provider-local assertions beside each provider. Their focused real-binary Bazel run is still the
verification gate; the current development environment is blocked before test execution by the
BCR TLS/PKIX failure.

The purpose of this document is therefore to record observed capture evidence, the remaining bounded
verification, and the experiments that should inform the next shared-protocol slice. It is not a
request to recapture the same baseline behaviors or to build a generic compatibility framework.

## Capture evidence delivered

For both Claude and Codex, the committed examples cover:

- launch and native handshake;
- baseline streaming and terminal output;
- shell command and file-edit tool lifecycles, including externally visible effects;
- active-turn steering or second-input behavior;
- interruption and native terminal state;
- upstream connection retry and retry exhaustion;
- follow-up input after a transport failure; and
- idle native session/thread resume after replacing only the idle process.

Each live capture preserves native stdin/stdout/stderr, complete upstream request bodies, streamed
response chunks, and controlled loss markers. It intentionally excludes headers, cookies,
credentials, OAuth state, and private user data. The repository keeps only the compact upstream
request/response inputs needed to replay the tested model-server side; the native logs are
disposable capture output. The replay tests assert the scenario-relevant lifecycle, output,
process survival, and workspace behavior of a fresh pinned harness against those inputs.

## Current verification gate

The focused test is:

```sh
bazel test //x/agentplane/capture:test_native_replay
```

It launches the pinned Claude and Codex binaries against a deterministic loopback fake model server.
The behavioral assertions are synchronized by native protocol checkpoints and fake-server fixture
consumption, not by sleeps or exhaustive packet equality. They tolerate generated IDs, timestamps,
optional metadata, extra progress events, and provider-specific chunk boundaries where those do not
change the tested behavior.

The gate should verify, for each provider/scenario fixture:

- the native handshake and terminal outcome;
- the relevant tool, command, file, steer, queue, or interrupt lifecycle;
- retry/error/give-up behavior for connection-loss cases;
- same-process survival and follow-up recovery where captured;
- native continuity for idle resume; and
- the expected assistant output or workspace effect.

Request bodies are checked for scenario-relevant shape and identity, not literal equality of every
volatile field. A live recapture is available for investigation when needed. A provider-specific result
must be recorded as **Proven**, **Supported differently**, **Unsupported**, or
**Environment-blocked**, rather than normalized into a false common success.

## Captured provider observations

The current recordings establish these constraints:

- Claude uses newline-delimited stream/control JSON. Its captured version can retry before visible
  stream content, but after a visible text delta it returned an empty terminal result without an
  observed automatic reconnect.
- Codex app-server uses newline-delimited JSON-RPC-shaped messages. Its captured version emitted
  retry notices and eventually reported a failed turn after repeated upstream losses.
- A Claude active-turn second input is observed as native input behavior; it must not be called
  steering unless the provider's native evidence supports that interpretation.
- Codex exposes explicit `turn/steer` and `turn/interrupt` operations in the scenarios where they
  are supported.
- Idle resume uses Claude `--resume` or Codex `thread/resume`, not transcript replay or prompt
  redispatch.

These are observations from the currently pinned harnesses for adapter design. The bridge must not manufacture retry, steering,
acknowledgement, or successful completion semantics that the native process did not emit.

## Next post-capture experiments

The next focused work package is the thin shared stdio protocol and both provider adapters. Use the
existing behavioral tests, compact upstream fixtures, and real binaries to answer only what that
package needs:

1. Which native start/resume, submit, interrupt, and event operations have stable behavioral
   equivalents?
2. What admission, progress, completion, failure, and process-survival evidence should the shared
   seam expose without hiding provider-specific details?
3. How should supported-differently or unsupported steering and queue behavior be represented?
4. Which native continuity identifiers must be retained to resume a replacement idle process?
5. What is the smallest adapter-level contract that can be proven by replay before introducing the
   standalone Agentplane service?

Do not add a neutral timeline, retry policy, central state machine, or persistence schema merely to
answer these questions. Keep live provider captures as the authority and keep checked-in replay data
compact.

## Refreshing harness evidence

The complete native capture output is intentionally not a long-lived Git artifact. If a pinned
harness version changes, or a new protocol behavior needs coverage:

1. obtain the new pinned Claude or Codex harness;
2. run the live capture scripts against the synthetic workspace and model endpoint;
3. eyeball the native and upstream differences against the currently tested behavior;
4. update the provider driver and hand-authored behavioral tests only for behavior we intend to
   pin down; and
5. replace or add the compact upstream replay inputs and update the harness pin as needed.

Do not preserve verbose native logs merely to make the repository self-contained. They can be
regenerated from the capture scripts when a review or investigation needs them.

## Historical capture invariants

These rules remain in force for any new capture or replay fixture:

- use real native stdin/stdout pipes, never PTYs, tmux, terminal scraping, or pane attachment;
- drain stderr and preserve bounded useful diagnostics;
- capture upstream model bodies through the minimal local HTTP server/proxy;
- use synthetic workspaces and deterministic tool inputs;
- synchronize steering and interrupt races with native events or explicit checkpoints, not sleeps as
  the only evidence;
- keep process exit status and relevant failure messages, without PID/signal chronology or
  Kubernetes identity;
- never blindly redispatch an input after uncertain process death; and
- treat unavailable binaries or unsupported provider operations as explicit results.

For connection-loss cases, cut one active upstream stream after a named complete partial-content
packet and before terminal completion. Keep the native process and stdio connection alive, restore
model-endpoint availability, and observe the provider's behavior. Start without tools so retries
cannot repeat side effects. This tests model-API transport behavior, not provider-native resume,
bridge reconnect, or Input redispatch.

## Fixture shape

A live capture contains the complete native and upstream evidence:

```text
metadata.json
stdin.jsonl
stdout.jsonl
stderr.jsonl
llm-requests.jsonl
llm-responses.jsonl
```

Committed `testdata/<provider>/<scenario>/` replay inputs currently retain only the two upstream
files: `llm-requests.jsonl` and `llm-responses.jsonl`. Native logs are disposable capture output,
not replay inputs or golden outputs. Native and upstream files are UTF-8 text. File order is the
ordering authority. Do not add routine
hashes, lengths, timestamps, manifest inventories, parsed mirrors, or custom DLP/promotion machinery.
Semantic expectations belong in hand-authored tests.

## Deferred experiments

One capture-environment cleanup remains explicit: find a supported RBE Claude launcher/toolchain that
runs the pinned CLI without the current Nix ELF-loader workaround in
[`../capture/providers/claude/replay_fixtures.py`](../capture/providers/claude/replay_fixtures.py). This is execution-environment cleanup, not a reason to alter
the capture protocol or behavioral assertions.

These remain outside the capture and adapter slice:

- multiple pending prompts and durable dequeue policy;
- active-turn process death and side-effect reconciliation;
- central-server reconnect or bridge-log replay;
- Pod replacement, Sandbox suspension, PVC lifecycle, or Service topology;
- Thread/Input/Turn persistence, PostgreSQL, and common timeline projection;
- leases, fencing, authentication, mTLS, credentials, approvals, or subscription adapters; and
- the standalone Agentplane API, conversation UI, and Haku Console integration.

They become worthwhile only after the shared seam is proven with the real captured behaviors and a
concrete product failure or decision requires them.
