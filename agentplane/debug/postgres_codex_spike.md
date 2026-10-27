# Postgres Codex sampler spike

Baseline merged in [PR #12207](https://github.com/agentydragon/ducktape/pull/12207), 2026-10-27: `/root/postgres_harness_spike` implements the operator-dispatched
code-mode-only experiment in `agentplane/x/postgres_codex`, branch `x/postgres-codex-20261027`.
This report describes a custom outer loop reusing upstream components; it is not a persistence fork
or a production replacement. No staging changes or live inference were requested or performed.

## What the slice establishes

The executable checkpoints a complete provider response, runs a real upstream JavaScript cell and
remote shell/patch, commits its output, and lets a fresh sampler process issue the next model request.
The integration fixture uses PostgreSQL and the pinned npm Codex 0.162.1 binaries, rather than copies
of their runtime or patch implementation. The same SSE fixture also drives the full native app-server.
Tests cover encrypted reasoning continuation, stale-owner rejection, lost replies after a real append,
a truncated provider stream, sampler SIGKILL while sampling, and executor SIGKILL mid-tool.

All seven integration cases passed in **51.9 seconds** on RBE, invocation
[`8a1a2810-b81f-45ea-b971-ad6cec41e15a`](https://app.buildbuddy.io/invocation/8a1a2810-b81f-45ea-b971-ad6cec41e15a).
The invocation also named all five runtime libraries so their mypy and Ruff aspects ran:

```sh
bbr test //agentplane/x/postgres_codex:test_sampler \
  //agentplane/x/postgres_codex:store //agentplane/x/postgres_codex:executor \
  //agentplane/x/postgres_codex:code_mode //agentplane/x/postgres_codex:sampler \
  //agentplane/x/postgres_codex:main --test_output=errors
```

Normal pre-commit hooks passed on the implementation commit. The adapter consumes upstream's
`process/output`, `process/exited` and `process/closed` push hints and collects retained output
through `process/read`, whose `nextSeq` is an exclusive cursor. The real binary tests exposed these
interleaved events; a request/response-only fake would have missed them.

## Cost accounting

At the passing implementation, physical lines including comments and blanks were: `store.py` 143,
`executor.py` 81, `code_mode.py` 153, `sampler.py` 103 and `main.py` 83: **563 new runtime lines**.
Test/support code is 511 lines. These are source counts, not a claim that a complete harness fits
in that size. BUILD and documentation lines are excluded.

The direct Python runtime dependencies are existing `aiohttp`, `SQLAlchemy` and `asyncpg`; the
test-only executable also uses the existing managed-engine helper. Tests add existing pytest,
pytest-bazel, testcontainers and native harness fixtures. No lockfile or production dependency changes
are needed. Runtime also requires PostgreSQL, a sampler-side `codex-code-mode-host`, and executor-side
`codex` plus `/bin/sh`. These compiled upstream components dominate the reused implementation.

Source at tag `rust-v0.162.1` (`092d3acd`), counting all `.rs` files including tests:

| Upstream crate       | Rust files | Physical lines | Direct Cargo dependencies |
| -------------------- | ---------: | -------------: | ------------------------: |
| code-mode-host       |         31 |          9,412 |                        19 |
| code-mode-runtime    |         26 |          8,393 |                        11 |
| code-mode-protocol   |         20 |          5,023 |                         8 |
| exec-server          |        181 |         64,975 |                        43 |
| exec-server-protocol |         10 |          2,891 |                         9 |
| apply-patch          |         16 |          5,638 |                         9 |
| core, for comparison |        846 |        448,069 |                       105 |

Dependency counts are manifest entries, not unique transitive packages. These crate totals are not
executed-line counts, a minimal link closure, runtime memory measurements, or quantities that can be
summed as the exact binary footprint. The experiment reuses release binaries; it does not trim them.
No fork patch or full persistence-fork implementation was built, so a measured fork LOC comparison
is unavailable. Removing upstream rollouts/state-db alone would retain core's substantial orchestration.

## Provider and runtime surface we would own

The new provider code owns Responses Lite's header, `additional_tools`, a freeform `exec` declaration,
SSE terminal detection, encrypted-reasoning echo, custom-tool output shape, model/cache metadata and
full-history requests. It persists only complete provider responses, without partial streaming deltas.
It does not test OpenAI authentication, provider cache behavior, live model acceptance, compaction,
multimodal output, retries or reconnect protocols. The native baseline establishes agreement with a
pinned independent consumer of the scripted protocol; it does not establish live API compatibility.

The upstream host owns JavaScript parsing, V8 isolation and nested-tool delegation. Our adapter owns
host protocol V1 and the enabled tool definitions. The executor adapter owns initialization,
`process/start`, `process/read`, output-cursor draining and a deliberately restricted tool result.
It executes actual upstream patch code by argv. It does not replicate upstream shell policy, approval,
PTY/stdin, image handling or formatted tool metadata. Neither remote process effects nor live V8
isolate state become transactional because their intent was committed in Postgres.

The [experimental contract](../x/postgres_codex/SPEC.md) lists the intended status of every omitted
headless capability. This slice makes custom conversation storage feasible with a small adapter;
whether the omitted control features are acceptable remains a product decision. Prefer upstream
central Codex for broad feature compatibility today. A custom loop becomes a reasonable candidate
if code-mode-only, completed-cell checkpoints and the narrower tool contract are accepted, with
provider tracking and uncertainty reconciliation explicitly owned. Frontend tracing is separate work;
the operator explicitly removed it as an acceptance gate because Langfuse provides partial links.

## Process-control extension

The operator required `wait`, stdin and interrupts as minimum custom-sampler capabilities after the
baseline merged. The extension retains the actual pinned code-mode host across model sampling and
`session/wait` observations in `main_bin run`. A yielded JS cell has a host-UUID-prefixed handle;
raw native IDs restart at `1`, so they cannot be global database keys or model-facing identities.
A separate durable process registry tracks running/terminal shell handles and retained-output cursors.
The model receives current execution state regenerated from these tables alongside conversation input.

`exec_command` can yield, and `write_stdin` sends real bytes or polls the same process. A sole Ctrl-C
uses `process/signal`; EOF uses PTY Ctrl-D. The pinned protocol has no pipe-close operation, and that
unsupported EOF request is rejected. Initialization must resume the database's executor `sessionId`:
process IDs are session-scoped, and initializing a different session makes them unknown even on the
same server. The pinned server keeps a detached session for **30 seconds**. Expiry/server loss with
live handles blocks recovery without a replacement session or replay. Terminal handles permit a new
session. V8 state remains live-only: a fresh sampler owner cannot reconstruct a yielded cell from
nested results and must block, rather than replay JavaScript.

An external CLI `interrupt` targets the active owner generation, persists a request and is observed
by `advance`/`run`; `status` exposes its outcome. A committed request prevents the next outer or
nested dispatch. Interrupt closes the sampling response, tries native cell termination, observes
host shutdown, gates further executor mutations, terminates known processes and observes their exits.
Stopping the whole host closes the window where native execution started before its cell registry
write. Known fixture shell/child PIDs are checked for no remaining live process after successful
cleanup; this is not a cgroup fence for escaped descendants.

Successful cleanup appends interrupted/not-started results for every outstanding committed model
call, stops sampling and allows only explicit new input to reopen the turn. Provider cancellation is
local HTTP cancellation; provider completion and partial remote effects are not rolled back. Lost
cleanup outcomes remain `effects_unknown` with a blocking intent, including an interrupt that occurs
between transitions. Stdin mutations and shell commands are never automatically retried. The
[experimental SPEC](../x/postgres_codex/SPEC.md) describes deadlines and remaining omissions.

The extension has **1,275 physical runtime Python lines**, including comments/blanks, across
`store.py` 435, `executor.py` 193, `code_mode.py` 329, `sampler.py` 127, `main.py` 116 and `control.py` 75. The baseline was 563; the
additional lifecycle and durable control code is 712 lines. New control test/support code is 737
lines. Counts exclude BUILD, SQL and docs, and do not include the reused upstream Rust inventory
above. No new third-party runtime dependency or production caller was added.

Validation is running for the final host-shutdown boundary and additive migration. An earlier
complete run passed seven process-control cases, four interrupt cases and the original seven cases,
with named runtime libraries' Ruff/mypy aspects:
[`8e89959a-fff1-4e64-8be0-c52469fbb866`](https://app.buildbuddy.io/invocation/8e89959a-fff1-4e64-8be0-c52469fbb866).
The new checks retain real binaries and Postgres. No live inference, production integration, merge
or deployment is established by this extension. Compaction is independently implemented and must
preserve the live registry prefix and interruption outputs when integrated.
