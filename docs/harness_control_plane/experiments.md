# Rerunnable protocol and recovery experiments

Status: **required implementation plan**. The architecture does not promote provider recovery
behavior to a guarantee until these experiments exist as code and pass for an exact compatibility
profile.

The suite uses real Claude Code and Codex binaries for semantic probes, but minimizes paid inference.
Parser/projection tests replay saved fixtures offline. Kubernetes lifecycle tests use safe
filesystem markers and the lowest-cost explicitly configured model.

## Objectives

Prove separately:

1. native completed-turn Thread-context resumption after harness-process death;
2. workspace/PVC persistence after process death, Pod deletion, and Sandbox suspension;
3. the observable result of harness death during an active turn;
4. interrupt request and terminal-state semantics;
5. Claude boundary-queued input and Codex targeted mid-turn steering;
6. central-server disconnect/reconnect with lossless bridge-log replay;
7. raw-native to common timeline projection for shell, file, and structured-tool operations;
8. an opaque A2A 1.0 projection of delegated task status, artifacts, and follow-up context;
9. version drift detection before a provider image is promoted;
10. correlation of native harness records with the corresponding upstream LLM HTTP requests and
    streamed responses.

The suite must not conflate a surviving file with surviving Thread/model context, or runner journal
replay with provider-native resume.

## Proposed code layout

```text
experiments/harness_control_plane/
  BUILD.bazel
  README.md
  runner.py                    # CLI and scenario orchestration
  model_budget.py              # explicit model/effort/cost limits
  llm_capture.py               # correlation with the recording proxy
  artifacts.py                 # manifest, exact JSONL capture, promotion
  a2a_spike.py                 # common-turn to A2A interoperability probe
  fault_injection.py           # signals, process kill, network cut, Pod delete, suspend
  fixtures/
    operation_probe.py          # deterministic workspace-local side-effect probe
    workspace_probe.sh         # safe marker operations
  testdata/<provider>/<profile>/<scenario>/
    *.jsonl                     # promoted full-wire regression fixtures
  providers/
    base.py
    claude.py                   # stream/control adapter for probes
    codex.py                    # app-server JSON-RPC adapter for probes
  scenarios/
    baseline.py
    resume.py
    active_turn_death.py
    interrupt.py
    steering.py
    central_disconnect.py
    sandbox_suspend.py
    operation_projection.py
  tests/
    test_fixture_projection.py  # offline golden replay tests
    test_artifact_validation.py
```

The live entry point should be a Bazel `py_binary`; offline replay tests run under
BuildBuddy/Bazel. Live paid/provider and cluster scenarios are explicit `bb run` invocations, not
ordinary presubmit tests.

## Safe execution contract

Every live run requires:

- explicit provider;
- exact harness binary/image digest;
- verified Sandbox-owned PVC mounts for workspace and selected provider state;
- verified `restartPolicy: Never` for the bridge-entrypoint Pod;
- explicit model name;
- explicit lowest accepted reasoning/effort setting;
- maximum provider calls/tokens and estimated spend ceiling;
- unique isolated workspace path;
- scenario allowlist;
- artifact output directory;
- recording-proxy endpoint and scoped test-credential policy id;
- acknowledgement if the scenario will delete a Pod, suspend a Sandbox, or explicitly dispose of
  Sandbox storage.

The runner refuses to use an implicit production default model. For Claude the intended default
probe class is the cheapest supported Haiku-class model. For Codex the runner discovers or is given
the lowest-cost allowlisted Responses-compatible model and uses the lowest reasoning effort it
accepts. The selected model and any provider reroute are recorded in the manifest.

Live semantic probes use the same in-cluster LiteLLM -> CLIProxyAPI Messages/Responses paths as Haku
Console, with capture integrated at the model-gateway boundary. CLIProxyAPI owns the Claude and
Codex consumer OAuth sessions and refreshes them outside the experiment workload. The runner
preferably uses the same configured endpoint plus inert-placeholder/egress-fence substitution as
Haku Console; it never performs consumer login or mounts OAuth state.

The preferred unattended credential is a dedicated virtual key restricted to the allowlisted cheap
test models and a hard budget. Ducktape PR
[#5348](https://github.com/agentydragon/ducktape/pull/5348) provides the initial
`cheap-experiments` LiteLLM key and makes its dedicated Secret eligible for an exact temporary Haku
Console grant. An active grant still requires operator approval through the ordinary grant
mechanism; that temporary-grant path is the selected first delivery mechanism. The experiment
artifacts record the virtual-key policy id, LiteLLM/CLIProxyAPI route, and proxy/config digests,
never any key or OAuth material. A standalone runner outside the Haku Console fence may use that
temporary exact grant; the manifest records `credential_delivery: egress_fence | temporary_grant`.
The exact model route is part of the compatibility profile, not a separate consumer-OAuth test
surface.

No scenario edits a real repository or relies on external side effects. All operation work is
confined to a unique temporary directory on the test PVC.

## Artifacts

Each run writes a self-contained directory:

```text
run-<timestamp>-<provider>-<scenario>/
  manifest.json
  bridge-wire.jsonl
  native-stdin.jsonl
  native-stdout.jsonl
  llm-requests.jsonl
  llm-responses.jsonl
  common-timeline.jsonl
  process-events.jsonl
  kubernetes-events.jsonl
  assertions.json
  summary.md
  workspace-before.txt
  workspace-after.txt
```

`manifest.json` includes:

- git commit and dirty state;
- provider, harness version, binary/image digest, and sanitized launch argv;
- bridge/projector version;
- model, reasoning effort, endpoint family, token usage, and measured/estimated cost;
- recording-proxy version/config digest and scoped virtual-key policy id;
- Agent Sandbox controller version, SandboxTemplate digest, storage class, Claim/Sandbox/Pod UIDs;
- scenario seed, nonce, kill point, timing deadlines, and environment capabilities.

Every bidirectional native record is saved with direction, monotonic timestamp, native sequence,
and capture metadata. A fixture is invalid if it captures only what the harness emitted: it must
also contain every captured bridge-to-harness request/control record in `native-stdin.jsonl` and the
full harness-to-bridge stream in `native-stdout.jsonl`. Assertions are machine-readable and include
`pass`, `fail`, `unsupported`, or `inconclusive`; “no exception” is not a passing recovery assertion.

Every upstream LLM request and streamed response is captured with a correlation id that links it to
the provider continuity reference, Turn, and bridge records. The recorder captures exact JSON
request/response bodies and stream chunks but excludes HTTP authorization headers, cookies, proxy
credentials, and OAuth material by construction. Usage, finish reasons, timing, retry, and
proxy-routing metadata are retained. This evidence distinguishes harness behavior from
LiteLLM/CLIProxyAPI or provider behavior during recovery.

Synthetic runs should be promoted into the repository as complete exact-payload JSONL fixture
bundles rather than reduced to hand-written summaries. The intended layout is:

```text
experiments/harness_control_plane/testdata/<provider>/<profile>/<scenario>/
  manifest.json
  bridge-wire.jsonl
  native-stdin.jsonl
  native-stdout.jsonl
  llm-requests.jsonl
  llm-responses.jsonl
  projected-common-timeline.snapshot.jsonl
  process-events.jsonl
  kubernetes-events.jsonl
  assertions.json
  summary.md
```

CI replays the captured input and output wire in both directions, projects it into the expected
common timeline, and checks the machine-readable assertions without provider inference. The
captured payload structure, ordering, generated ids, timestamps, chunk boundaries, and bodies are
preserved rather than reconstructed, canonicalized, or summarized.

The preferred promotion path performs **no payload scrubbing**. The capture runs in a fresh isolated
container and synthetic workspace, receives no personal Agent memory or production repository data,
and records only credential-free protocol bodies at capture points that exclude HTTP headers and
OAuth state. An automated scanner inventories account/provider identifiers and rejects bearer
tokens, cookies, refresh tokens, authorization headers, private keys, API/client keys, client
secrets, Basic-auth values, access/session tokens, signing/webhook secrets, known private
Agent/workspace identifiers, and unexpected personal text. The promotion schema classifies every
captured field as allowed content, allowed identifier, or forbidden credential material; an unknown
field or unknown high-entropy credential-shaped value blocks promotion until the schema is reviewed.
An opaque provider account id is not treated as a secret by itself, but it must be a declared
identifier and the manifest records its presence so repository review can make the privacy decision
explicitly.

If a useful capture fails that gate, the default is to fix the recorder or isolation and rerun it.
A deterministic schema-declared substitution path remains available as a fallback; any transformed
copy is labeled **wire-faithful fixture**, not **restricted raw**, and records pre/post hashes plus
all substitutions.

Promotion is a deterministic build step, not manual editing:

1. record whole-file hashes for the immutable capture;
2. validate native-wire, upstream-traffic, process-event, Kubernetes-event, and manifest schemas
   plus cross-stream correlation references;
3. run the credential/personal-data scanner and either accept the exact payload files unchanged,
   reject and rerun, or invoke the explicit fallback substitution path;
4. replay the production projector from the accepted fixture input to generate
   `projected-common-timeline.snapshot.jsonl`;
5. apply the scenario's independently authored `assertions.json` to that generated timeline; and
6. regenerate all derived files from the fixed captured input and require byte-for-byte identical
   output before accepting the fixture.

CI treats the captured wire and upstream files as inputs. The projected timeline is a generated
regression snapshot, not an independent correctness oracle. Independently authored assertions are
the semantic oracle, and promotion of a new fixture requires review of the native-to-common mapping
diff. Scenario assertions are never generated from the observed result they are meant to test.

## Deterministic fixtures

### Thread-memory nonce

Generate a random nonce such as `violet-7f3a2c`. In a no-tool completed turn, ask the harness to
remember the nonce and reply only `ACK`. Do not write the nonce into the workspace or system prompt.
After restart/resume, ask for the nonce. Exact recovery proves provider model-context continuity;
finding a workspace file cannot satisfy this assertion.

### Workspace sentinel

Write a sentinel through a deterministic local script or provider tool:

```text
/workspace/probe/<run-id>/sentinel.json
```

The file contains run id, nonce, Sandbox UID, Pod UID, and checksum. After process/Pod/suspend
recovery, assert content/checksum, Sandbox UID, PVC/PV identity when observable, and changed Pod UID.
This proves storage continuity independently of model memory.

### Active-turn kill window

Use a safe command with observable boundaries:

```sh
printf 'before\n' > "$PROBE/phase"
sleep 30
printf 'after\n' >> "$PROBE/phase"
```

Kill the target after the `command started` native event and after the file contains `before`, but
before `after`. This gives a machine-checkable kill point and a harmless possible side effect.

After resume, do **not** automatically replay the original prompt. Inspect native history, common
timeline, and file state first. A follow-up asks the harness to describe the prior turn without
requesting it to rerun the command.

### Deterministic operation probe

A workspace-local `operation_probe.py` exposes command modes:

- `echo VALUE` -> structured JSON and text echo;
- `count KEY` -> atomically increments a run-local counter;
- `wait MARKER SECONDS` -> creates an observable active operation;
- `fail CODE` -> deterministic nonzero exit.

It logs invocation ids and exact arguments/results. `count` detects duplicate admission or replay.
The native harness invokes it through its ordinary shell operation. Saved fixtures separately test
generic structured-tool projection.

## Scenario matrix

| ID  | Scenario                            | Claude         | Codex        |       Paid calls | Core assertion                                      |
| --- | ----------------------------------- | -------------- | ------------ | ---------------: | --------------------------------------------------- |
| P0  | Binary launch and handshake         | yes            | yes          | 0 where possible | exact profile initializes                           |
| P1  | Baseline no-tool turn               | yes            | yes          |                1 | one admitted and terminal turn                      |
| P2  | Shell + file + tool projection      | yes            | yes          |                1 | equivalent common operations, native provenance     |
| R1  | Kill harness idle, resume           | yes            | yes          |                2 | memory nonce survives or is honestly unsupported    |
| R2  | Delete Pod idle, resume PVC/context | yes            | yes          |                2 | new Pod, same workspace, provider continuity result |
| R3  | Manual idle suspend, resume         | yes            | yes          |                2 | active request rejected; PVC/continuity result      |
| R4  | Kill harness mid-turn               | yes            | yes          |              1-2 | partial side effect and native history classified   |
| R5  | Delete Pod mid-turn                 | yes            | yes          |              1-2 | no false clean interruption/replay                  |
| R6  | Explicit Sandbox disposal           | cluster-only   | cluster-only |                0 | only confirmed action destroys Sandbox-owned PVC    |
| C1  | Restart central server mid-turn     | yes            | yes          |                1 | no missing/duplicate wire/common events             |
| D1  | Crash at each dispatch transition   | yes            | yes          |              1-2 | no blind replay or lost durable input               |
| B1  | Kill bridge/PID 1 while idle        | yes            | yes          |              1-2 | replacement only after old workload termination     |
| B2  | Kill bridge/PID 1 mid-turn          | yes            | yes          |              1-2 | uncertain/terminal evidence is honest               |
| F1  | Old and new bridge reconnect        | yes            | yes          |                0 | stale generation cannot admit or append             |
| I1  | Interrupt during command            | yes            | yes          |                1 | request correlated; terminal state observed         |
| I2  | Interrupt racing completion         | yes            | yes          |                1 | one honest terminal classification                  |
| S1  | Mid-turn steering during tool wait  | boundary input | `turn/steer` |                1 | provider-specific admission evidence                |
| S2  | Steering during prose/reasoning     | boundary input | `turn/steer` |                1 | timing and race documented                          |
| S3  | Steering racing completion          | yes            | yes          |                1 | admitted current/future/rejected, never lost        |
| V1  | Unknown native event replay         | fixture        | fixture      |                0 | generic event preserves payload                     |
| V2  | Delta coalescing equivalence        | fixture        | fixture      |                0 | reconstructed content/hash matches exact stream     |
| A1  | Delegated task through A2A facade   | fixture        | fixture      |                0 | context, artifacts, status survive opaque mapping   |

Paid-call counts are targets, not a reason to exceed the manifest ceiling. Related assertions should
share one provider turn where that does not make the result ambiguous.

## Detailed scenarios

### P0: launch and handshake

Before either provider launches:

- reject the template unless `/workspace` and selected provider-state paths resolve to
  Sandbox-owned PVCs rather than `emptyDir`;
- reject the template unless the bridge-entrypoint Pod has `restartPolicy: Never`;
- record the resolved PVC/PV identities and effective Pod spec in the artifact manifest.

Claude:

- compare probe and production argv, including the current `--print` discrepancy;
- send initialize control request and capture correlated response;
- record all reported capabilities/version fields;
- exit without model inference if possible.

Codex:

- launch app-server against a local fake Responses endpoint;
- perform `initialize` / `initialized`;
- prove request/response endpoint wiring without paid inference;
- validate durable versus ephemeral `thread/start` behavior at the schema/process level where
  possible.

### P1/P2: baseline and projection

Run one prompt that invokes the safe workspace script and deterministic operation probe, then answers a
short fixed phrase. Assert:

- one accepted input and one native admission;
- one terminal provider turn;
- shell/file/tool operation ids have monotonic lifecycle;
- completed item/result is authoritative over deltas;
- common text equals reconstructed native text;
- every common event resolves to native provenance;
- no duplicate operation after raw replay.

### A1: A2A facade spike

Project the saved Claude and Codex baseline fixtures through an A2A 1.0 server and client without provider inference. Assert:

- the server creates an opaque A2A `context_id` and privately maps it to the common Thread;
- the server creates an opaque A2A Task id and privately maps it to one delegated provider Turn;
- caller and agent messages retain task/context correlation;
- final text and deliverable file diffs stream as artifacts;
- submitted/working/terminal state and cancellation map without exposing internal operation events;
- a server-side mapping rejoins follow-up context to the private Postgres timeline;
- outbound messages, artifacts, task metadata, and status contain no Thread/Turn, bridge, native,
  or other common-protocol identifiers;
- omitting tool and raw-frame events does not make the external task view misleading.

This is an interoperability test for an opaque agent-to-agent facade, not a substitute for bridge crash, native resume, or the web UI's rich internal timeline tests.

### R1: idle harness-process death

1. complete the no-tool memory nonce turn;
2. record the provider continuity id and flush all logs;
3. kill only the native harness child, leaving bridge/Pod/PVC alive;
4. launch a new child and invoke provider-native resume;
5. ask for the nonce;
6. assert exact response and changed process identity.

For Codex, use a durable non-ephemeral thread and the same persisted `CODEX_HOME`. For Claude, record
and use its provider continuity id and required state paths. A runner frame cursor does not count.

### R2: idle Pod death

Repeat R1 but delete the Pod while retaining the Sandbox. Assert:

- connection and runtime end are observed;
- Sandbox UID and PVC sentinel survive;
- Pod UID changes;
- replacement bridge reconciles the append-only log before new dispatch;
- provider-native resume result is recorded independently from PVC result.

### R3: idle Sandbox suspension

1. while a safe Turn is active, request suspension and assert that the API rejects it without
   changing desired Sandbox mode;
2. leave one accepted future input pending and assert suspension is still rejected, then cancel it;
3. let the Turn finish and complete the memory and workspace fixtures;
4. invoke the explicit operator suspend action;
5. flush/stop the native child cleanly;
6. set `spec.operatingMode: Suspended`;
7. wait for `Suspended=True` and prove the Pod is absent;
8. prove Sandbox CR, PVC, and optional Service remain;
9. wait at least one reconciliation interval and prove no automatic disposal occurs;
10. resume the Sandbox and wait for a new Pod/bridge handshake;
11. run both workspace-sentinel and Thread-memory assertions.

Also verify that scaling a WarmPool to zero is not used as suspension: unclaimed pool Sandbox/PVC
loss is a separate controller test.

### R6: explicit Sandbox disposal

Create a disposable cluster-only Sandbox with a PVC sentinel. Verify that no elapsed retention
window deletes it. Invoke the explicit dispose action, require confirmation, and assert that the
Claim/Sandbox and Sandbox-owned PVC are deleted while central audit metadata remains. Attempting to
dispose an active-turn Sandbox must be rejected; failed/uncertain state requires an explicit
abandonment acknowledgement.

### R4/R5: active-turn death

Use the active-turn kill window. Run both child-process kill and Pod deletion. Record:

- last provider event before death;
- whether native rollout stores a partial item or interruption marker;
- whether a cold resume is accepted;
- whether the provider considers a turn active, failed, interrupted, or absent;
- whether starting a follow-up is allowed;
- workspace phase file;
- whether any side effect repeats without an explicit replay request.

Passing behavior is not necessarily continuation. Honest `uncertain` plus safe follow-up may be the
correct production contract.

### C1: central-server restart

Keep bridge and harness alive. After an operation starts, stop the gateway/server replica or
cut only its network path. Let the native turn finish if possible, then start another replica.
Assert:

- bridge continues reading and records land in the append-only PVC log with contiguous native
  sequences;
- reconnect announces the last acknowledged sequence;
- central storage receives each missing record exactly once semantically;
- common projection contains no duplicate messages/operations;
- accepted input is not redispatched.

Run this without killing the harness to isolate central recovery from native resumption.

### D1: dispatch crash windows

Inject a deterministic central, connection, bridge, or child failure immediately after each
transition:

1. central `input.accepted` commit;
2. `input.offer` write;
3. bridge-log append but before `input.bridge_durable` acknowledgement;
4. native protocol write but before provider admission evidence;
5. native admission observed but before central commit;
6. terminal native record observed but before central terminal commit.

For every point, restart/reconnect and assert the durable input is visible, the dispatch state is
honest, and `operation_probe.py count` did not repeat without an explicit new instruction. The
expected outcome may be safe retry, provider-continuity reconciliation, or `outcome_uncertain`;
silence
and blind redispatch both fail.

### B1/B2: bridge death and runtime fencing

First partition the old bridge from the central service while leaving its Pod and native child
alive. Request replacement and assert that the control plane blocks new dispatch,
provider-continuity
resume, and replacement activation while the old workload can still run. Central fencing alone is
not a passing result.

Then terminate bridge PID 1 while idle and during the active-turn kill window. Assert
`restartPolicy: Never` prevents an in-place container restart. After the old Pod/process is observed
terminated, let the reconciler delete/recreate the Pod, allocate a new Runtime ID, and increment the
runtime generation.
Finally reconnect a captured old-generation client while the replacement is active. The server may
retain its diagnostics, but must reject stale input admission, wire append, cursor advancement, and
terminal updates.

### I1/I2: interrupt

Interrupt during the deterministic wait and near natural completion. Assert request correlation,
provider response, command/item state, terminal turn state, and workspace phase. Acceptable race
results are provider-defined, but exactly one honest terminal classification must be visible.

### S1-S3: steering

Claude:

- send a UUID-stamped user frame during an active tool wait;
- observe command-lifecycle/boundary admission;
- verify behavior during continuous prose and near completion;
- classify input as admitted in current turn, queued for later boundary/turn, cancelled, or rejected.

Codex:

- call `turn/steer` with exact active thread/turn id and client user-message id;
- await JSON-RPC result;
- correlate resulting user item and continued turn;
- race the same call against `turn/completed` and record accepted/rejected outcome.

The suite separately tests “queue a future turn”; it must not use future-turn queuing as evidence that
mid-turn steering works.

## Assertions by failure boundary

| Boundary                          | Must not be used as proof           |
| --------------------------------- | ----------------------------------- |
| Central reconnect                 | Provider continuity resume          |
| Runner/bridge-log replay          | Provider model-context memory       |
| PVC sentinel survival             | Native thread/session survival      |
| Interrupt request acknowledgement | Turn actually interrupted           |
| Process exit                      | No side effect occurred             |
| Pod recreation                    | Same process/session is still alive |
| Same Kubernetes object name       | Same UID or retained storage        |
| Reconstructed final text          | Lossless lifecycle/tool evidence    |

## Fault injection mechanisms

- harness death: signal/kill the exact child PID through the bridge's test control;
- bridge death: terminate PID 1, assert no same-Pod restart, then observe controlled Pod
  deletion/replacement;
- central death: stop one replica or inject a gateway endpoint failure without touching the Pod;
- network partition: NetworkPolicy/test proxy or an adapter-local transport cut;
- Pod loss: delete the backing Pod, not the Sandbox;
- suspension: patch Sandbox operating mode and wait on controller conditions;
- disposal: invoke only the explicit confirmed control-plane action against a dedicated disposable
  Sandbox;
- storage fault: unmount/read failure only in a dedicated disposable environment.

Every injector records command, target UID/PID, timestamp, observed completion, and cleanup. No test
uses tmux `send-keys` or visual pane scraping to choose a kill point.

## Promotion report

The suite produces one compatibility report per provider profile:

```text
Provider/profile: codex <version> / <model> / agent-sandbox v0.5.5
Baseline protocol: PASS
Completed-turn cold resume: PASS
Pod replacement workspace: PASS
Pod replacement Thread context: PASS
Active-turn process loss: INCONCLUSIVE -> production behavior: outcome_uncertain
Interrupt during command: PASS
Mid-turn steer: PASS
Central reconnect replay: PASS
LLM request/response correlation: PASS
Manual suspension guard: PASS (active Turn rejected)
Explicit Sandbox disposal: PASS
Common operation projection: PASS
```

Production code consumes this report as configuration: automatic native resume and steering are
enabled only for passing profiles. An inconclusive active-turn result becomes an explicit
conservative behavior, not a reason to block all other capabilities.

## Initial economical sequence

1. Build offline artifact, wire, projector, and fixture tests.
2. Provision the scoped cheap-model virtual key and recording proxy in a separate small change.
3. Add P0 for both real binaries with no paid inference where possible.
4. Spend one minimal turn per provider to capture a baseline operation fixture plus correlated LLM
   request/response recording.
5. Prove completed-turn native resume with two short no-tool turns per provider.
6. Reuse that profile for process/Pod/manual-suspend workspace checks.
7. Run active-turn kill, interrupt, and steering scenarios with one safe tool-using turn each.
8. Run central disconnect against the same deterministic tool scenario.
9. Run the cluster-only explicit-disposal contract on a dedicated Sandbox.
10. Repeat only failed/inconclusive cases while developing; rerun the full matrix at release gates.

This ordering discovers protocol incompatibility before spending on the more expensive fault matrix.
