# Common protocol: post-capture design notes

Status: **native captures and replay fixtures are integrated; the shared seam is the next focused
implementation slice**.

This document is no longer a pre-capture placeholder. The Claude and Codex capture work has already
produced live native/upstream observations, provider scenario drivers, and compact upstream replay
fixtures under [`../capture/`](../capture/). The evidence is now the input to protocol design. The
remaining capture verification is the focused real-binary behavioral replay gate; it must not be
replaced by more bookkeeping or by a speculative compatibility framework.

## Evidence already available

For both native harnesses, the checked-in behavioral replay set covers:

- launch and handshake;
- a baseline streamed turn;
- shell and file-edit tool interactions;
- active-turn steering or second-input behavior;
- interruption;
- upstream connection retry and retry exhaustion;
- same-process follow-up after a transport failure; and
- idle native session/thread resume in a new process.

Each live capture preserves the ordered native stdin/stdout/stderr evidence and the complete upstream
request/response bodies or chunks. Only the compact upstream request/response inputs needed by the
replay server are checked in. The hand-authored replay tests exercise a fresh pinned harness and
assert the behavior relevant to the scenario rather than requiring every generated ID, timestamp,
progress packet, or chunk boundary to be identical. Provider differences remain visible:

- Claude and Codex expose different native control and lifecycle frames.
- Claude's post-visible-content connection loss produced an empty terminal result without observed
  automatic reconnect in the captured version.
- Codex emitted retry notices and eventually a failed turn after repeated losses.
- Steering, queued input, interruption, and resume use provider-native mechanisms and outcomes; they
  are not assumed to be equivalent merely because both providers have a related operation.

These observations are constraints on the adapter seam, not a license to manufacture common
semantics the providers did not demonstrate.

## What the shared seam may own next

The next implementation package is one thin stdio protocol plus a Claude adapter and a Codex
adapter. It should expose only operations and observations that the replay tests can prove with the
real binaries. A small candidate surface is:

```text
start_or_resume(...)
submit(...)
steer(...)       # only where the provider supports a meaningful native operation
interrupt(...)
events()
```

The seam may report provider capability and provider-specific terminal/error outcomes. It must not
silently turn a second input into steering, emulate retry, redispatch an uncertain input, or present
an unsupported operation as successful. Native provider IDs should remain available to callers
where they are needed for correlation and resume.

The shared driver protocol is an internal stdio boundary. It is distinct from the browser-facing
Agentplane API and does not decide Thread naming, archive presentation, timeline UX, or HTTP/SSE/WebSocket
resource design.

## Capture evidence contract

When a capture is run, the capture scripts and adapters must continue to preserve:

- native frames in both directions;
- complete payloads and framing boundaries;
- file order within each transcript;
- provider-native request, session, thread, turn, item, and tool IDs;
- model request bodies and streamed response chunks;
- enough process-exit information to diagnose a failed run; and
- hand-authored behavioral assertions tied to the relevant transcript records.

The complete native capture is an investigation artifact, not a permanent Git fixture. Checked-in
replay data should remain limited to the upstream request/response inputs required by the fake model
server and the hand-authored tests. Do not add routine byte lengths, hashes, parsed-object copies,
duplicate timestamps, sequence registries, or outer copies of provider IDs. The ordered payload
already supplies that information.

## Refreshing a pinned harness

When upgrading a Claude/Codex harness or adding coverage for a currently untested protocol area,
obtain the new pinned binary and run a fresh live capture. Review the native and upstream protocol
differences, then update the provider driver and behavioral tests only for the behavior we choose to
support. Replace or add the compact upstream replay inputs and the binary pin together. Do not check
in the verbose native stdin/stdout/stderr logs; regenerate them from the capture scripts when a
review needs them.

## Product nouns after capture

These nouns can now be tested against observed provider behavior, but they are still product-level
concepts rather than fields to inject into native transcripts:

- **Thread**: durable user-visible interaction context;
- **Input**: an inbound message accepted by the Agentplane service;
- **Turn**: one provider execution bracket;
- **Runner**: the native process or adapter serving a Thread; and
- **Timeline event**: a later UI/service projection of native evidence.

The first shared seam should not require a central persistence model for these nouns. The standalone
service can introduce them at its own API boundary after the adapters are proven.

## Decisions enabled by the captures

Before expanding the seam, use the committed tests and fixtures to settle only the decisions needed
for the next slice:

- which native operations map cleanly to `submit`, `interrupt`, and `resume`;
- how each provider reports admission, progress, completion, failure, and process survival;
- whether a provider's active second input is queued, steered, rejected, or otherwise observable;
- which resume identifiers and native state must be supplied to a replacement process; and
- which provider-specific events must remain explicit instead of being collapsed into a common enum.

If a behavior is unsupported or supported differently, preserve that result in the adapter contract.
Do not add a generic state machine, retry policy, neutral operation projector, or timeline schema to
make the matrix appear symmetric.

## Separate follow-up work

Post-capture adapter work must remain separate from:

- the Agentplane REST/OpenAPI and SSE/WebSocket API;
- Thread/Input/Turn persistence and any PostgreSQL schema;
- Kubernetes/Agent Sandbox lifecycle and Pod replacement;
- bridge reconnect cursors, leases, fencing, or uncertain-input recovery;
- authorization, credentials, approvals, or subscription adapters; and
- conversation UI and Haku Console integration.

Those layers may consume the shared seam later, but none is required to define it or to reinterpret
the raw capture evidence.
