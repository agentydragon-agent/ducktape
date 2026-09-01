# Subtask: capture native Claude Code and Codex wires

Status: **implementation task**.

Build the smallest useful experiment: launch real Claude Code and Codex processes, drive their
native JSON protocols, capture the native exchange and upstream model exchange, and prove the
drivers with replay tests. Do not build the future control plane around the experiment.

## Goal

For each provider, produce a small committed fixture and tests that establish:

- the real launch and initialization sequence;
- one normal streamed turn;
- tool input and tool result handling;
- steering and interruption where the provider supports them;
- native session/thread resume after an idle process restart; and
- the upstream LLM requests and streamed responses that make those interactions work.

The fixture is evidence for the provider driver. It is not a product timeline, database dump, or
compatibility registry.

## Explicit non-goals

Do not implement in this task:

- PostgreSQL, JSONB wrappers, or a Thread/Turn/Input persistence model;
- a provider-neutral facade or common operation projector;
- Kubernetes/Agent Sandbox reconciliation, Services, suspension, or Pod replacement;
- bridge reconnect cursors, leases, fencing epochs, or stale-writer handling;
- artifact promotion, generated summaries, or a fixture registry;
- checksums, SHA fields, body lengths, or per-artifact integrity manifests;
- a custom DLP/entropy scanner;
- package-manager discovery and executable integrity metadata;
- approval requests, dynamic tools, credentials, subscriptions, or external-event adapters.

Those may be future work if a concrete implementation needs them. They are not prerequisites for
proving native harness driving.

## Suggested layout

The exact split is flexible, but every module must support launching, driving, recording, replaying,
or asserting the native harness behavior:

```text
x/agentplane/capture/
  BUILD.bazel
  README.md
  process.py              # pipes, stderr drain, timeout, exit status
  transcript.py           # ordered native/upstream transcript I/O
  fake_llm.py             # deterministic replay server
  providers/
    claude.py             # Claude stream/control driver
    codex.py              # Codex app-server driver
  scenarios.py            # small provider-specific scenario helpers
  tests/
    test_transcript.py
    test_claude.py
    test_codex.py
    test_replay.py
  testdata/
    claude/<scenario>/
    codex/<scenario>/
```

Use an explicit binary path or a simple environment variable. Do not add a resolver for every
possible package installation method.

## Capture format

Fixtures should be readable and boring. A scenario directory contains:

```text
metadata.json      # provider, scenario, human-readable binary version if known
native.jsonl       # one ordered native frame per line
llm.jsonl          # ordered model requests and response chunks
stderr.log         # useful diagnostics; empty is fine
expected.json      # hand-authored assertions
workspace/         # only files needed to prove the scenario's effect
```

`native.jsonl` preserves the exact protocol payload and direction. For the JSON-native protocols,
store the complete line as `data` (with its framing newline represented in the record) and do not
copy fields such as ids, lengths, hashes, or parsed projections into an outer schema. File order is
the sequence.

`llm.jsonl` contains the complete request bodies and streamed response chunks in observed order.
Use one simple request/exchange marker only when needed to associate a response with a request. Do
not create separate correlation, response-reconstruction, route, timing, usage, or digest files.

The native and model transcripts are the diagnostic truth. `expected.json` is a small, independently
written semantic oracle: expected handshake, important native events, tool calls/results, terminal
outcome, and workspace effects. It must not be generated from the observed output.

Record process exit status and a bounded stderr diagnostic for a failing live run. Process IDs,
monotonic timestamps, signal histories, process generations, and Kubernetes identities do not belong
in committed fixtures.

## Upstream model capture and replay

Use a small local HTTP server or proxy that:

- forwards the live request to the configured experiment endpoint when capturing;
- writes only request/response bodies and response chunks;
- never writes HTTP headers, environment variables, cookies, or proxy credentials; and
- can later replay the saved `llm.jsonl` exchange deterministically.

The fake server is not a replacement for real-provider captures. It is what makes the valuable
real-harness integration test repeatable without paid inference.

## Required scenarios

Implement the following for both providers where the native surface supports them:

1. **launch** — start the binary and complete its native handshake;
2. **baseline** — submit one prompt and assert streamed output plus terminal completion;
3. **tool** — exercise one deterministic shell or structured tool and assert the native call,
   result, upstream request(s), and expected workspace effect;
4. **steer** — send steering during a controlled active turn, or record an explicit unsupported
   result when no native steering surface exists;
5. **interrupt** — interrupt a controlled active turn and assert the actual terminal evidence;
6. **resume** — complete a no-tool turn, kill only the idle native child, use the provider's native
   resume function, and assert that a nonce in model context is recoverable;
7. **replay** — run the real harness against the deterministic fake model loaded from the captured
   upstream exchange and assert both the upstream requests and native output.

The provider-specific tests must remain explicit. Do not force Claude's user-frame behavior and
Codex's JSON-RPC behavior through a shared scenario abstraction before their differences are known.

## Tests

The minimum useful test set is:

- framing across partial pipe reads;
- handshake and request/response routing for each provider;
- replay of each committed native transcript;
- replay of each committed upstream transcript through the real harness when the binary is available;
- tool call/result and workspace assertions;
- steering and interrupt assertions or explicit provider-unsupported results;
- idle native resume assertions;
- a simple fixture guard that rejects obvious credential material and serialized HTTP headers; and
- a check that capture code has no import from `haku/*`.

The real-binary tests are opt-in if the binaries are unavailable. Offline transcript tests must run
in ordinary Bazel tests without network access, credentials, Kubernetes, or provider binaries.

## Live-run rules

- Use a synthetic temporary workspace.
- Set a finite model-call ceiling and a finite timeout.
- Do not use a PTY, tmux, pane scraping, prompt heuristics, or `kubectl exec` as the protocol path.
- Drain stderr independently so the child cannot block.
- Use synchronization from native events or the test tool, not arbitrary sleeps, for steering and
  interrupt races.
- Never automatically resend a prompt after uncertain process death.
- Commit only bodies and synthetic-workspace data that have been inspected for credentials and
  private user data.

## Completion criteria

This subtask is complete when:

- both native drivers launch the resolved real binaries and complete their handshakes;
- committed fixtures contain the bidirectional native exchange and corresponding upstream bodies;
- the baseline and tool scenarios replay offline;
- the real-harness fake-model replay test proves the driving loop for both providers, or records a
  concrete environment blocker;
- steering, interrupt, and native idle resume are proven or explicitly unsupported per provider;
- tests assert native output, model requests, tool I/O, and workspace effects; and
- no implementation or fixture requires PostgreSQL, Kubernetes, a common facade, hashes, lengths,
  or a custom promotion/scanner framework.
