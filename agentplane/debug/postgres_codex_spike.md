# Postgres Codex sampler spike

In flight, 2026-10-27 07:50 PDT: `/root/postgres_harness_spike` implements the operator-dispatched
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

Validation is in progress; a test's presence does not yet establish its result. Initial RBE execution
confirmed database fencing and truncated-stream handling, then exposed exec-server's interleaved
`process/output` and `process/exited` notifications. The adapter now consumes these push hints and
collects retained output through `process/read`, whose `nextSeq` is an exclusive cursor.

## Cost accounting

At the first complete draft, physical lines including comments and blanks were: `store.py` 143,
`executor.py` 81, `code_mode.py` 153, `sampler.py` 103 and `main.py` 83: **563 new runtime lines**.
Test/support code was 515 lines. These are source counts, not a claim that a complete harness fits
in that size. The final counts and successful test invocation will replace this draft measurement.

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
