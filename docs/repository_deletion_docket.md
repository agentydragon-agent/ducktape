# Repository simplification docket

This is a living, ranked list of changes that could make Ducktape cheaper to
understand, edit, debug, and review.

The first version of this docket over-weighted bytes and raw line counts. That
made isolated archives and generated bulk look more important than frequently
edited production paths with duplicated state machines, parallel contracts, or
large change surfaces. This revision uses a different cost model:

1. recurring programmer time and cognitive load,
2. breadth of files/contracts touched by one behavior change,
3. likelihood of deleting a complete representation or plumbing stage,
4. conservative whole-tree net LOC payoff,
5. estimated probability that the recommendation will be accepted.

Storage-only wins are now separated from the active engineering queue. A giant
archive that costs one harmless line in `ls` ranks below an ugly live path that
costs hours every month.

Baseline inspected: [`50f75a500`](https://github.com/agentydragon/ducktape/commit/50f75a5000d963715ca2e4afc4e1242404c96f56).

## How to review this

Terse decisions are enough:

```text
D01 yes
D03 prototype first
D07 no, keep the explicit security mirror
Q01 delete the remainder
D09 prototype only after numerical evidence
```

For accepted implementation candidates, the PR must report the actual
whole-tree diff and stay net negative. A refactor that merely moves a giant
function into more files does not satisfy this docket.

## Already decided or completed

These results are no longer active recommendations:

| Result                                    | Decision / evidence                                                                                                                                                                                                                                                              |
| ----------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Accidental TensorBoard notebook cache     | Removed in [#4613](https://github.com/agentydragon/ducktape/pull/4613): 47,958,742 bytes deleted while preserving notebook cells, authored source, normal outputs, and the rerunnable TensorBoard command.                                                                       |
| Unrelated May Props specimen website      | Removed in [#4614](https://github.com/agentydragon/ducktape/pull/4614): 110 files, 12,217 lines, and 13.1 MB. The specimen integration test passed.                                                                                                                              |
| Local Props match scopes                  | Nine occurrences were narrowed to their labeled files in [#4619](https://github.com/agentydragon/ducktape/pull/4619).                                                                                                                                                            |
| Generated Props matchability tracker      | Removed in [#4621](https://github.com/agentydragon/ducktape/pull/4621); the accidental ignore rule was corrected in [#4622](https://github.com/agentydragon/ducktape/pull/4622). The generator remains available on demand.                                                      |
| Two obsolete live Claude prompts          | `codereview.md` and `til.md` were removed in [#4623](https://github.com/agentydragon/ducktape/pull/4623).                                                                                                                                                                        |
| Copied May-specimen Claude prompt archive | The whole copied directory and stale `.prettierignore` entry were removed in [#4627](https://github.com/agentydragon/ducktape/pull/4627); the specimen test passed.                                                                                                              |
| Obsolete Grocy “ideal API” contract       | The stale 644-line parallel contract was removed in [#4642](https://github.com/agentydragon/ducktape/pull/4642).                                                                                                                                                                 |
| Grocy batch orchestration                 | D05 merged in [#4645](https://github.com/agentydragon/ducktape/pull/4645): repeated ordered-batch/retry/enrichment control flow was consolidated for **114 fewer whole-tree lines**.                                                                                             |
| Settings-panel async resources            | D06 merged in [#4648](https://github.com/agentydragon/ducktape/pull/4648): five loader state machines became one typed resource primitive for **24 fewer whole-tree lines** and about **70 fewer production lines**.                                                             |
| Haku tool-call projections                | D02 merged in [#4643](https://github.com/agentydragon/ducktape/pull/4643): the duplicate MCP record/projection stage was removed for **128 fewer whole-tree lines**. Typed-caller correctness follow-up [#4652](https://github.com/agentydragon/ducktape/pull/4652) also merged. |
| Haku manifest change-detector prototype   | **Rejected after security review.** The strongest D07 version saved only 15 whole-tree lines and still weakened independent RBAC, namespace-label, proxy, credential, and migration release-gate oracles. No PR was opened.                                                      |
| Augur amount-reducer prototype            | **Rejected after numerical/performance review.** D09 saved only 30 lines, deleted no complete execution stage, and added an unnecessary fan-only terminal-vector transfer. No PR was opened.                                                                                     |
| Raw inference `.eval` archives            | **Deferred by decision.** Keep the 11 files for now; do not pursue without renewed approval.                                                                                                                                                                                     |
| LiteLLM exact-config mirror tests         | Do not duplicate [open PR #4472](https://github.com/agentydragon/ducktape/pull/4472). The broader invariant cleanup in [#4469](https://github.com/agentydragon/ducktape/pull/4469) is already merged.                                                                            |

## Parked prototype

| ID  | Status                                                                                                                                                                                                                                                                                      | Actual payoff                                                 |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------- |
| D03 | [Parked draft PR #10](https://github.com/agentydragon-agent/ducktape/pull/10) is a cleanup patch based on feature PR #4584 because it touches that feature branch's session-lifecycle code. #4584 belongs to a separate feature track; do not modify or manage it from this cleanup docket. | **34 fewer whole-tree lines**; **102 fewer production lines** |

## Active prototype

| ID  | Status                                                                                                                                                                                                                              | Actual payoff                  |
| --- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------ |
| D08 | [PR #4657](https://github.com/agentydragon/ducktape/pull/4657) moves Grocy's client-critical conventions into owning tool/schema descriptions while retaining an 11-line compatibility preamble for the two genuinely global rules. | **174 fewer whole-tree lines** |

## Remaining programmer-cost queue

The queue is ordered by estimated acceptance probability, with larger complete
stage deletions first when probabilities are similar. Estimates are deliberately
conservative and include replacement code and test changes.

| ID  | P(agree) | Recommendation                                                         | Estimated whole-tree payoff | Risk              |
| --- | -------: | ---------------------------------------------------------------------- | --------------------------: | ----------------- |
| D04 |      84% | Share neutral Claude/Codex projection mechanics                        |             **180–320 LOC** | medium–high       |
| D10 |      70% | Shrink the Haku Console README to a canonical-doc index                |             **190–290 LOC** | medium docs       |
| D11 |      68% | Consolidate duplicate Gmail/Calendar façade and client input contracts |               **40–90 LOC** | medium API-schema |

## Prototype sequence outcome

The approved D03 → D02 → D05 → D06 → D07 → D09 sequence has been executed. D02,
D05, and D06 merged; D03 is a parked cleanup patch on the separate
#4584 feature track; D07 and D09 were rejected after independent review. The rejected
prototypes remain local and unpushed.

The results reinforce the docket's acceptance rule: a prototype must delete a real
representation or orchestration stage, remain whole-tree net negative, and preserve
independent semantic/security oracles. Passing focused tests is not enough when the
result merely reshuffles a reducer or weakens a manifest contract.

## Detailed recommendations

### D02 — canonicalize the Haku tool-call path

**Targets and change surface:**

- [`haku/console/mcp_approval.py`](../haku/console/mcp_approval.py) —
  `PostgresToolCallLedger`, its record/MCP projections, and `McpServerDispatcher`
- [`haku/console/tool_call_service.py`](../haku/console/tool_call_service.py) —
  `ToolCallRepository`, `ToolCallApplicationService`, duplicated list/get/execute paths
- [`haku/console/mcp_server.py`](../haku/console/mcp_server.py) —
  `McpToolCallResponse`, `_record_to_result`, `_direct_to_result`, `_dispatch`

Together these files are about 2,830 lines and have changed in roughly 30 commits
in the last 180 days. One tool call is repeatedly represented as database rows,
general records, MCP-specific records, response models, approval stubs, and final
`ToolResult` values. The application service also exposes parallel general/MCP
list and get methods.

**Safe replacement:** keep one durable row, one domain record carrying the full
terminal/approval state, and transport-specific renderers at the HTTP/MCP edge.
Build listing projections from one statement shape rather than maintaining
parallel `_record_projection_stmt` / `_mcp_projection_stmt` and conversion paths.
Preserve the operator/Agent authorization checks and terminal-state transitions.

The implementation should delete a representation boundary; merely renaming or
moving the same adapters is not a win.

**Validation:**

- `bbr test //haku/console:test_mcp_approval //haku/console:test_tool_call_service //haku/console:test_mcp_server`
- approval, denial, withdrawal, timeout, direct execution, and degraded-server integration tests
- API/MCP schema snapshots or generated client checks

**Risk:** medium–high. Approval authorization and audit history are security
contracts; preserve fail-closed actor scoping and exact terminal semantics.

### D03 — collapse duplicate session lifecycle and query paths

**Targets:**

- [`haku/console/x/session_store.py`](../haku/console/x/session_store.py) — 2,477 lines,
  62 commits in 180 days
- [`haku/console/x/session_runtime.py`](../haku/console/x/session_runtime.py) — 1,130 lines,
  57 commits in 180 days

`SessionStore` owns allocation, leases, prompt queues, turn state, frames,
projection, conversation reads, close/abort/failure, and cleanup. `SessionService`
then wraps several of those operations while also owning claims, runner handling,
provisioning views, renewal, abort watching, finalization, and route adapters.
Lifecycle status and query concerns cross both classes, so a new session state or
runtime behavior routinely changes database code, service wrappers, and views.

**Safe replacement:** define one explicit lifecycle-transition component for
allocation/lease/terminal state, one read-model/query component for conversation
and transcript views, and keep runner orchestration in `SessionService`. Delete
pass-through service methods and parallel status/provisioning branches once all
callers use the owning component.

This candidate is accepted only if a prototype demonstrates a whole-tree deletion
of at least one complete query/lifecycle path. Splitting the 2,477-line class into
more files without deleting logic is not the goal.

**Validation:**

- `bbr test //haku/console/x/...`
- Matrix homeserver/full-stack E2E tests
- lease expiry, prompt replay, resumed turn, abort, failure, cleanup, and reprojection tests

**Risk:** high. The store implements exactly-once and recovery behavior around a
real database; preserve transactional locking and replay invariants.

### D04 — share neutral Claude/Codex projection mechanics

**Targets:**

- [`haku/console/x/claude_code/projection.py`](../haku/console/x/claude_code/projection.py)
- [`haku/console/x/codex_app_server/projection.py`](../haku/console/x/codex_app_server/projection.py)

Both modules independently define `OpenItem`, `ProjectionState`, `RecordedFrame`,
`project`, `finish`, `project_log`, and a mutable `_Projector`. Provider-specific
frame interpretation is legitimately different, but item lifecycle, ordered
emission, open-item bookkeeping, finish semantics, and projection result assembly
are parallel machinery.

**Safe replacement:** extract a small neutral projection accumulator and item
lifecycle API. Keep Claude and Codex pattern matching/fold decisions in their own
modules. Do not force both providers through a giant union of frame types.

**Validation:**

- both projection suites and recorded-frame fixtures
- transcript/reprojection tests
- equivalence checks over all existing captured logs

**Risk:** medium–high. Ordering, partial items, and terminal flush behavior are
user-visible transcript contracts.

### D05 — remove repeated Grocy batch orchestration

**Target:**
[`grocy_mcp/batch_tools.py::register_batch_tools`](../grocy_mcp/batch_tools.py)

The file is now 1,620 lines; almost all tools are nested inside one registrar.
Useful helpers already exist (`_retry`, `_retry_mutation`, `_stock_mutate`,
`_simple_batch_create`, enrichment maps), but individual tool bodies still repeat
batch-size checks, name/ID resolution, client acquisition, ordered per-item
result/error conversion, and best-effort post-mutation reads.

**Safe replacement:** introduce one typed ordered-batch executor with explicit
read-only, idempotent-mutation, and uncertain-mutation policies; use domain-specific
resolvers/enrichers around it. Keep tool registration near each owning model, but
count success only if repeated control flow disappears. A mechanical file split is
not enough.

**Validation:**

- `bbr test //grocy_mcp/...`
- retry-safety and uncertain-mutation tests
- E2E coverage for stock, products, shopping lists, entities, and volatile stock
- compare exposed tool schemas/descriptions before and after

**Risk:** medium. Error ordering and “mutation may have applied” behavior must not
be generalized away.

### D06 — use one async-resource primitive in the settings panel

**Target:**
[`haku/console/frontend/settings_panel.tsx`](../haku/console/frontend/settings_panel.tsx)

The 1,024-line component separately implements `loadMcpServers`, `loadAgents`,
`loadDeployment`, `loadIndexStatus`, and `loadDaemons`, each with similar loading,
error, refresh, and stale-response handling. Tab activation, polling, reconnect,
and mutation callbacks must know which subset to reload.

**Safe replacement:** one typed `useAsyncResource`/query primitive should own
loading state, error state, cancellation/generation, refresh, and optional polling.
Cards remain domain-specific. Avoid adding a heavyweight state library for this
single page.

**Validation:** frontend typecheck/tests, settings navigation, reconnect/polling,
OAuth connection, Agent changes, and MCP refresh browser tests.

**Risk:** low–medium; guard against stale responses replacing newer data.

### D07 — delete pure Haku manifest change-detector tests

**Targets:**

- `test_public_coder_and_haku_standing_diagnostics_are_secret_free`
- `test_public_coder_kubernetes_proxy_contract`
- exact-shape portions of `test_haku_console_migration_release_gate`

in [`cluster/validation/test_haku_manifest_contracts.py`](../cluster/validation/test_haku_manifest_contracts.py),
plus the repeated subject roster in
[`cluster/validation/kyverno/test_agent_diagnostics_readers.py`](../cluster/validation/kyverno/test_agent_diagnostics_readers.py).

The main contract file is 750 lines and changed in 31 commits over 180 days.
Large expected role/resource/subject dictionaries and fixed name/port/health-check
objects reproduce checked-in manifests in Python. They fail on any desired-state
edit, but copying the new desired state into the test does not distinguish a correct
change from an incorrect one.

This is the pattern rejected by [`STYLE.md`](../STYLE.md):

> No pure change-detector tests: don't assert a checked-in literal equals itself
> copied into the test. Test semantics — invalid values rejected, invariants hold,
> behavior differs by mode.

**Prototype objective:** delete the copied dictionaries and exact-shape assertions,
not merely derive or restate them differently. Retain a test only where it has an
independent semantic oracle and can distinguish invalid behavior, for example:

- standing verbs remain read-only,
- Secrets and pod exec/attach/port-forward remain forbidden,
- public-coder never receives the cluster-admin ceiling,
- the sandbox reaches Kubernetes only through the proxy,
- proxy Service/route/port/Secret references resolve,
- Flux dependencies and health checks reference real resources,
- migration and server images remain coupled, and the migration gate stays
  unprivileged and release-blocking.

If an assertion only says the rendered configuration equals another checked-in
literal, delete it. Do not preserve it solely because the mirrored configuration is
security-sensitive. The egress allowlist matrix remains a separate case because it
can encode independently reviewed policy rather than merely copying one manifest.

**Validation:**

- `bbr test //cluster/validation:test_haku_manifest_contracts`
- `bbr test //cluster/validation/kyverno:test_agent_diagnostics_readers`
- `bbr test //cluster/validation:test_cluster_integration`

**Risk:** medium–high. The prototype must make the semantic-oracle distinction
explicit so useful negative authorization checks are not confused with literal
mirrors.

### D08 — fold Grocy conventions into owning tool descriptions

**Targets:**

- [`grocy_mcp/server_instructions.md`](../grocy_mcp/server_instructions.md) — 197 lines
- `_load_server_instructions` in [`grocy_mcp/server.py`](../grocy_mcp/server.py)
- eval-only prompt concatenation

[`grocy_mcp/TODO.md`](../grocy_mcp/TODO.md) records the architectural problem:
Claude.ai does not expose MCP `initialize.instructions` to the model. The same
quantity-unit, stock mutation, expiry, typed-vs-generic, and shopping-list rules
are partly repeated in `mcp_types.py`, `batch_tools.py`, and `tool_metadata.py`.

**Safe replacement:** move client-critical guidance to the Pydantic field or tool
that owns it. Retain a short compatibility introduction for clients that do consume
`initialize.instructions` until tools-list and eval coverage proves the long file
unnecessary.

**Validation:** tools-list description assertions, Grocy E2E tests, and eval cases
covering units, expiry, stock correction, opening, and shopping lists.

**Risk:** medium. Do not silently remove guidance from clients that currently use it.

### D09 — delete parallel Augur amount/reduction adapters

**Target:**
[`finance/augur/sim/engine/jax_engine.py`](../finance/augur/sim/engine/jax_engine.py),
especially `run_jax_product_summary`, `run_jax_product_summaries`,
`_amount_values`, `_amount_values_tuple`, and `_amount_values_vec`.

The 3,769-line engine changed in 48 commits over 180 days. The remaining promising
large-scale simplification is not decomposing the single financial scan; it is
removing parallel tuple/vector/scalar amount materialization and reduction plumbing
around it.

**Safe replacement:** preserve one canonical structured amount/result path through
JIT boundaries and derive summaries directly from it. Preserve all financial
formulas, exact lot-marking/tax arithmetic, and the single `lax.scan`. Reject a
prototype that expands call sites or tests and fails to produce a whole-tree
reduction.

**Validation:** all `//finance/augur/sim:all` and product tests, deterministic
rollout equality, tax/lot golden cases, failed-rollout behavior, and performance
comparison at production-relevant rollout counts.

**Risk:** high numerical and performance risk. Prototype and measure before making
this an implementation PR.

### D10 — make the Haku Console README an index

**Target:**
[`haku/console/README.md`](../haku/console/README.md)

The 695-line README changed in 34 commits over 180 days and restates detailed live
contracts for MCP admission/approval, Agent authority, OAuth browser ownership,
chat/session/channel semantics, and schema generation. Those subjects already have
canonical specialist documents under [`haku/console/docs/`](../haku/console/docs/),
including `agent_authority.md`, `oauth_browser_surfaces.md`, `chat_layers.md`,
`conversation_schema.md`, and `chat_runtime_facts.md`.

**Safe replacement:** keep architecture, entrypoints, local operation, and a short
summary/link per subsystem. Each detailed contract should have one owner.

**Validation:** link/anchor scan, console tests, and review of any docs or code that
links directly to a README heading.

**Risk:** medium discoverability risk; the replacement must remain a useful start page.

### D11 — consolidate duplicate Google MCP input contracts

**Targets:**

- Gmail façade signatures in [`haku/console/tools/gmail.py`](../haku/console/tools/gmail.py)
  versus `CreateGmailDraftArgs`, `UpdateGmailDraftArgs`, and label/thread models in
  [`gmail_client.py`](../haku/console/tools/gmail_client.py)
- Calendar façade signatures in
  [`google_calendar.py`](../haku/console/tools/google_calendar.py) versus
  `CreateCalendarEventArgs`, `ListCalendarEventsArgs`,
  `ListCalendarEventInstancesArgs`, `EventDateTime`, and reminder models in
  [`google_calendar_client.py`](../haku/console/tools/google_calendar_client.py)

Defaults, descriptions, optionality, and validation are represented once in the
flat public FastMCP function signature and again in internal Pydantic argument
models. A change can update one contract but not the other.

**Safe replacement:** keep the current flat public MCP schema. Add narrow conversion
constructors or shared annotated field definitions so validation/default ownership
is not duplicated. Do not expose nested internal request models merely to reduce
source lines.

**Validation:** exact tools-list schema comparison, Gmail/Calendar unit tests, and
live mocked client request-body tests.

**Risk:** medium. Tool schema changes affect every Agent client even when runtime
behavior is unchanged.

## Small follow-ups, not roadmap drivers

These are likely acceptable but too small to drive the active simplification roadmap.
Bundle them with related work rather than opening a stream of micro-PRs.

| ID  | P(agree) | Follow-up                                                                                                                                                  |        Payoff | Validation                             |
| --- | -------: | ---------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------: | -------------------------------------- |
| S01 |      93% | Centralize the repeated Claude runtime test/config payload across `haku/console/x/conftest.py`, the Matrix console replica, and runtime/profile tests.     | **25–40 LOC** | targeted Haku runtime/config tests     |
| S02 |      90% | Move duplicate Matrix Synapse/operator/password fixtures from the two E2E suites into `haku/console/x/channels/matrix/conftest.py`.                        | **30–45 LOC** | both Matrix E2E suites and sync tests  |
| S03 |      80% | Trim pure current-shape assertions from the Haku migration release gate while retaining rollout, privilege, image, dependency, and health-gate invariants. | **20–30 LOC** | manifest and cluster integration tests |

## High-confidence deletions with low recurring programmer cost

These are valid cleanup opportunities, but their main benefit is repository hygiene,
not recurring engineering time. They should not outrank the live-code candidates above.

### Q01 — delete the remainder of `x/claude_commands_old/`

**P(agree): 95%. Payoff: 919 lines. Risk: very low.**

The remaining five prompt files are explicitly archived and superseded by
[`.claude/commands/`](../.claude/commands/) and [`skills/`](../skills/). Two files
were already removed in #4623; the full copied specimen archive was removed in
#4627. Delete the remaining live archive and its README after one final inbound
reference scan. Git history preserves the wording.

### Q02 — consolidate overlapping useless-documentation scans

**P(agree): 88%. Payoff: roughly 400–550 net LOC. Risk: low.**

`prompts/scans/useless_documentation.md` and
`prompts/scans/useless_comments_and_docs.md` encode substantially the same policy.
Keep one prompt and the short canonical standard; merge only genuinely distinct
examples before deletion.

### Q03 — delete stale generated/manual inventories

**P(agree): 85%. Payoff: hundreds of lines. Risk: low.**

Examples include `mcp_infra/docs/mcp_tool_name_violations.md` and the unreferenced
aggregate `props/prompts/code_health_audit_fullprops.md`. Confirm no manual workflow
copies the exact aggregate prompt, then generate such reports as CI artifacts or
compose them from canonical standards.

## Parked or deprioritized candidates

These may be reasonable deletions, but current evidence does not show enough recurring
programmer cost to prioritize them:

- raw machine diagnostics, generated experiment traces, and old architecture surveys;
- inactive Props snapshots or copied subtrees not yet proven outside their import and
  evidence closure;
- retired deployment/IaC snapshots whose only cost is storage;
- exact renderer snapshots that protect intentional presentation behavior;
- migrations and schema acceptance tests that preserve durable compatibility;
- the Tana workspace fixture and reverse-engineering reference trees consumed by real
  workflows.

For Props snapshots, prune only after import tracing, issue-path closure checks, and the
production specimen integration test. Do not treat absence from one active image list as
proof that prepared training/evaluation data is abandoned.

Every candidate remains independently reviewable and reversible. The recorded sequence
above is not permission to combine unrelated cleanups into one PR or to trade behavior
coverage for smaller source files.
