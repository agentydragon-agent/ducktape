# Claude RemoteIO interoperability spike

Experimental, single-session, in-memory server for Claude Code **2.1.292**. The separate
Bazel pin does not change Agentplane's runner or its `2.1.252` scripted baseline.

## Acceptance

1. Real CLI initialization, scripted model request, output and completion through RemoteIO.
2. Correlate command delivery receipts with model requests and terminal output, without treating
   receipt as execution or persistence proof.
3. Discover real native children: identity, parent links, attributed output, and terminal outcomes.
4. Characterize transport reconnect separately from clean process resume and crash recovery,
   covering completed and active children, duplicate delivery, and repeated side effects.
5. Compare matching scenarios with `2.1.292` `stream-json` and recommend adoption only for measured gains.

The round-trip probe passed against the real CLI on `ffb21bad` in
[CI](https://github.com/agentydragon/ducktape/actions/runs/37757068286).
The follow-up `bf5a8508` passed tests/build, lint, formatting, Gazelle and import checks.
The child scenario passed on `8671925f`: a real `Agent` launch yields `task_started` and
`task_notification` with matching `task_id` and originating `tool_use_id`. Child assistant prose
arrives with that call's `parent_tool_use_id` and the parent's `session_id`; the latter alone cannot
identify children. The live-process SSE reconnect probe passed on `9e500aa9`: the CLI reconnects
at the delivered cursor, retains the earlier answer in model context, and emits no duplicate first
result during the tested continuation.

The completed-child crash probe passed on `588bb9ac`. It kills the parent after child completion,
retains native files, increments the worker epoch, and starts `--resume` with no server-provided
history. The fixture drops already-settled inbound commands at that explicit boundary; this is
not a general replay policy or server-durability test. The first crash capture retained the completed child's result in parent model history. However,
`TaskOutput` is absent from this configuration's roster despite the explicit tool allowlist;
invoking it returns `No such tool available: TaskOutput`. That is an unavailable query route,
not a missing-child observation. The passing probe pins that error and notification absence through the resume/input/query
sequence without reactivating the child. It does not establish
whether another route can recover the child's fate.
The same-version `stream-json` control now tests equivalent child attribution, unavailable
`TaskOutput`, and completed-child resume after both clean exit and crash; those assertions await CI.
RemoteIO clean exit, active-child crash, and server hydration remain unimplemented. Source inspection
informs the candidate protocol; CI wire captures determine the actual contract.

```bash
bbr test //x/claude_remote_io:all
```

## Test boundary

The CLI accepts only approved HTTPS hosts for `--sdk-url`. A loopback-only CONNECT fixture
maps exactly `api.anthropic.com:443` to our local TLS server. It never resolves or contacts
that host, denies other destinations, and uses a generated test CA with normal TLS verification.
The server requires a synthetic token and serves only the fixture session path. Model requests
use a separate loopback scripted endpoint. No real credentials or inference are used.

The baseline provides epoch `1` via `CLAUDE_CODE_WORKER_EPOCH`, empty worker metadata and
empty internal-event history. It does not claim to recover history. Capture commands, uploads,
delivery reports, stdout/stderr and CLI diagnostics as Bazel undeclared outputs. HTTP captures
exclude headers. Server-provided hydration must be separately identified in future recovery tests.

This is not production authentication, durable admission, multi-replica storage, or a runner
transport cutover. Do not import this experimental server into Agentplane services.

## Initial wire observation

CI verified initialization, a model request, assistant output and a successful result through the
experimental server, with the expected native session ID.
A user frame without origin metadata was rendered upstream as "Another Claude session sent a
message", with a warning that a peer cannot grant escalation. The internal-event upload marked
its origin as `peer` / `unknown`. The baseline asserts this behavior; it does not claim to submit
an authenticated human-origin command.

The capture distinguishes two identifiers in `/worker/events/delivery`: `received` uses the SSE
envelope's `event_id`, while `processing` and `processed` use the user payload's `uuid`. They
are deliberately different in the test. The captured terminal result has no `user_message_uuid`;
receipts cannot simply be joined to it by assuming every lane uses the same ID. The baseline
serializes one prompt, so it does not yet establish concurrent/coalesced-command correlation.
A delivery receipt is not proof of model consumption; the separate model request and result
assertions provide that evidence for this probe.
