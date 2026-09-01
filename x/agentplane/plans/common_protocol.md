# Common protocol: deferred notes

Status: **deferred until native captures exist**.

This file is deliberately not an implementation specification for the first capture slice. The
native Claude and Codex protocols are the control boundary initially. A neutral protocol should be
written only after real captures show which interactions are shared and which are provider-specific.

## What the first slice must preserve

- native frames in both directions;
- complete payloads and framing boundaries;
- file order within each transcript;
- provider-native request, session, thread, turn, item, and tool ids;
- model request bodies and streamed response chunks;
- enough process exit information to diagnose a failed run; and
- hand-authored assertions linked to the relevant transcript records.

Do not add redundant byte lengths, hashes, parsed-object copies, timestamps, sequence fields, or
outer copies of provider ids to a capture record. The transcript already supplies payload and order.

## Future product nouns

These are possible future product concepts, not requirements of the capture task:

- **Thread**: durable user-visible interaction context;
- **Input**: an accepted inbound message;
- **Turn**: one provider execution bracket;
- **Runner**: the bridge/native process serving a Thread; and
- **Timeline event**: a later UI projection of native evidence.

The initial tests may use provider-native ids directly. They do not need to persist or project these
nouns.

## Questions to answer from captures

After the P0 scenarios work, use their evidence to decide:

- whether Claude and Codex support a shared submit/steer/interrupt/resume vocabulary;
- what counts as native acknowledgement or admission for each provider;
- whether active input is queued, steered, rejected, or simply not written;
- what native resume means after idle process loss; and
- whether a durable central input/timeline model is needed for the next product slice.

Until then, do not invent common state transitions for queueing, delivery, cancellation, recovery,
or terminal outcomes. Preserve an unknown native event and make the provider-specific assertion
explicit.

## Later, if needed

A future bridge may expose a small provider-neutral interface such as:

```text
start_or_resume(...)
submit(...)
steer(...)
interrupt(...)
events()
```

That interface should be derived from the capture tests, not implemented as part of them. PostgreSQL,
Kubernetes lifecycle, bridge reconnection, authorization, and UI projection are separate follow-up
work. They must not be hidden inside the native transcript format.
