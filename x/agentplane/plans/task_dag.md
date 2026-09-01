# Agentplane P0 task DAG

This is a sequencing aid for the first native-harness slice, not a workflow engine or a second
architecture. A node is complete only when its evidence exists.

## Outcome

For Claude and Codex, a real harness can be launched, driven through its native protocol, observed
through its upstream model exchange, and run again from a deterministic replay with assertions for
native output, tool I/O, and workspace effects.

## DAG

```text
A. Fix the experiment contract
   |  provider binaries, model endpoint, synthetic workspace, finite budget
   v
B. Minimal process + transcript harness
   |  native stdin/stdout, stderr drain, ordered payloads, exit status
   v
C. Provider launch/handshake drivers
   |-----------------------------|
   v                             v
D. Claude baseline/tool       E. Codex baseline/tool
   |                             |
   +-------------+---------------+
                 v
F. Minimal fake model replay
   |  load saved model exchange; drive real harness; assert requests and native output
   v
G. Upstream disconnect + reconnect
   |  cut one active model stream; observe native retry/reconnect, duplication, and outcome
   v
H. Steering + interrupt
   |  provider-specific; unsupported is an honest result
   v
I. Idle native resume
   |  kill idle child; invoke native resume; prove context continuity
   v
J. Commit compact fixtures + Bazel replay tests
```

A and B are support. C through I are behavior. J is only the minimum regression packaging for the
behavior already proven.

## Gates

- Do not start F until at least one real baseline/tool path works for each provider.
- Do not add a shared provider abstraction before D and E expose an actual common behavior.
- Do not add persistence, common timeline, Kubernetes lifecycle, or recovery machinery to unblock a
  node in this DAG.
- If a node fails because the provider lacks a capability, record the provider-specific result and
  continue; do not expand the framework to make the matrix look complete.
- If the implementation has more artifact bookkeeping than native-driving logic, stop and cut it.

## Evidence by node

- **A:** documented command and endpoint assumptions; no credentials committed.
- **B:** one test proving partial pipe reads and complete ordered payload capture.
- **C:** actual initialize/handshake exchange for each provider.
- **D/E:** real baseline/tool transcript plus hand-authored expected behavior.
- **F:** real Claude/Codex binaries driven against a deterministic fake upstream; captured model
  requests and native output both asserted.
- **G:** one controlled upstream stream loss after partial response; exact chunks before loss,
  subsequent connection/request behavior, native output, process survival, duplicate suppression or
  duplication, and terminal outcome. Explicit no-retry/unsupported is valid evidence.
- **H:** actual steering/interrupt request and resulting native evidence, or explicit unsupported.
- **I:** native session/thread continuity after idle child restart, or explicit unsupported.
- **J:** offline replay passes with no network, credentials, Kubernetes, hashes, lengths, manifests,
  or custom promotion/scanner system.

## Deferred branch

Only after I, and only if a concrete product need remains, investigate:

- multiple pending inputs and dequeue;
- active-turn process death and side-effect reconciliation;
- central/bridge reconnect;
- Pod replacement and Sandbox suspension;
- PostgreSQL Thread/Input/Turn persistence;
- a neutral bridge protocol and UI projection; and
- authentication, fencing, approvals, credential delivery, subscriptions, and external-event
  adapters.
