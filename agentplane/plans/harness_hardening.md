# Harness hardening burndown

Native subsession implementation is deferred while session-event ownership moves into Sandbox
Service. This work characterizes and hardens the existing harness protocols and test infrastructure;
it does not add a session authority, persistence layer, or production subagent support. The automatic
current-versus-candidate binary upgrade lane is excluded.

The [subagent matrix](native_subagent_sessions.md) owns protocol evidence. The
[discovery proposal](native_session_discovery.md) remains a design, not an implementation commitment.
This file tracks the remaining work and merge dependencies, rather than duplicating that matrix.

## Landed foundation

| Capability | Evidence / PR | Limit |
| --- | --- | --- |
| Claude initialization correlation | #9461: pipe-peer interleaving and real-CLI resume tests | Not general user-command/result correlation |
| Claude root identity timing | #9459: explicit/minted identity, with/without input | No-input observation is bounded to 250 ms |
| Native parser compatibility | #9458: known-frame extensions, opaque unknown payloads, malformed known shapes | Typed projections are not lossless raw-frame round trips |
| RemoteIO peer conformance | #9454: shared HTTP fixture, authentication, malformed input, epochs and cursors | Experimental peer, not a production RemoteIO service |
| Exceptional native-process cleanup | #9455: assertion/cancellation, descendants, trace retention, graceful success | Deliberate `crash()` remains parent-only |

#9453 closed without merging after an accidental closing-keyword reference; #9461 contains its
replacement and the corrected real-CLI failed-resume expectation. Do not count them as two deliveries.

## Current dependency

#9457 relocates RemoteIO into `agentplane/harness_tests/x/claude_remote_io/`. Its prerequisites
#9454 and #9461 have merged. Its synchronized head must pass CI, with only relocation, import,
documentation, build and visibility changes in the diff. Follow-up changes to relocated files depend
on that merge and remain draft until their dependency is satisfied and their own checks pass.

## Next batch

| Work | Acceptance | Dependency |
| --- | --- | --- |
| Fixture refactoring pass | Remove redundant failure-only crash wrappers; retain deliberate crash checkpoints and all protocol assertions. Reuse shared lifecycle ownership; run native cleanup, Claude tool and RemoteIO stdio tests. | #9455; #9457 for relocated files |
| Codex v2 live reconnect | Disconnect only the client during an active turn and after completion. Capture identity, history and lifecycle evidence after reconnect without submitting new work to query status. | Independent of relocation and session-event migration |
| Input correlation and interrupt races | Script overlapping inputs and interleaved results for both harnesses; identify the operation each completion belongs to. Synchronize interrupt-before-start, active and completion boundaries. Reproduce and diagnose the observed Codex input-during-turn race. | Existing shared fixtures; keep protocol changes separate from fixture cleanup |
| Root crash/resume and side-effect replay | Extend existing recovery cases with explicit active/queued input fate and observable side-effect counts. Show whether a completed tool effect repeats on recovery. | Correlation evidence and explicit synchronization |

## Remaining queue

These are extensions of existing tests, not claims that each area currently has no coverage.

- **Protocol contracts:** consolidate evidenced guarantees beside native APIs; link the matrix for
  version-specific observations. Do not promote a source-code inference into a passing wire test.
- **Duplicate-command retry:** lose a bridge reply and retry the same command identity; assert the
  observed execution count and retained result. Coordinate with the session-event migration owner;
  do not introduce another command queue or event store.
- **Failure diagnostics:** retain native stdin/stdout/stderr, pending model-exchange information and
  the failing scenario boundary. Ensure cleanup preserves the original failure rather than hiding it
  behind a target timeout.
- **Synchronization:** replace avoidable timing guesses with native-frame/model-request barriers;
  label negative observations with their bounded window.
- **Large frames/backpressure:** exercise frames across transport buffering boundaries and a slow
  reader; check frame integrity, ordering, cancellation and bounded teardown.
- **Permission lifecycle:** correlate allow/deny responses, interrupt a pending permission request,
  and record what survives reconnect or resume without silently granting permission.
- **Configuration/model changes:** capture acknowledgement and the model/configuration actually used
  by subsequent requests, including rejection and changes during an active turn.
- **RemoteIO input provenance:** distinguish user input, control traffic and background task results;
  preserve native identities without inventing an operation mapping.
- **RemoteIO hydration:** characterize history/replay, epoch and cursor behavior across reconnect and
  process restart. An unavailable task is not evidence of completion, and querying it must not
  secretly reactivate it.

## Completion and evidence rules

A task is complete when its focused PR has merged with passing relevant real-binary tests and
repository checks. Record partial coverage explicitly; the first cleanup PR does not finish the
refactoring program. Subscribe to each PR and check the latest head, not a superseded green run.
Dependent PRs state their merge conditions and stay draft until those conditions are met.

Use scripted loopback model endpoints, synthetic workspaces and retained raw wire traces. Keep
passing observations, source-derived expectations and untested hypotheses distinct. Do not infer
completion from a disconnected transport, an unloaded child or a missing history entry. Existing
native crash/resume tests remain part of the baseline rather than being replaced by a second setup.
