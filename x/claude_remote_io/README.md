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

The first test implements the round-trip probe; **it is not yet verified**. Child discovery,
recovery, and same-version comparison remain unimplemented. Source inspection informs the
candidate protocol; CI wire captures determine the actual contract.

```bash
bbr test //x/claude_remote_io:test_interop
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

The first CI run reached initialization and a model request through the experimental server.
A user frame without origin metadata was rendered upstream as "Another Claude session sent a
message", with a warning that a peer cannot grant escalation. The internal-event upload marked
its origin as `peer` / `unknown`. The baseline asserts this behavior; it does not claim to submit
an authenticated human-origin command. Output/completion assertions have not passed yet.
