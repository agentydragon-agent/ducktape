# MCP0: live staging acceptance contract

**Status: blocked, not a passing live test.** This is the contract-only fallback until the
runtime can execute a real MCP Action. It belongs to the deployed suite, not the in-process
adapter tests. No production wiring, credentials, or substitute executor is introduced here.

## P0 behavior

A real Claude or Codex Agent discovers one designated safe MCP ActionGroup, submits one
ActionRequest, and polls its durable Action events to success. An independent test oracle
checks the exact persisted MCP result and exactly one backend invocation. Assistant prose,
including a JSON report or a claimed request ID, is diagnostic only.

Use the existing `provider`, `model`, `client`, and `sandbox` fixtures and `Agent.open` /
`Agent.run` from [agent.py](agent.py). Run the same scenario for both providers, each with a
fresh `accept-` sandbox and a fresh non-secret marker `MCP0-<uuid>`. Keep the fixture's
suspend/delete teardown on failures. Do not substitute a harness simulator.

### Safe fixture contract

The staging fixture must expose an MCP echo Action with arguments `{"text": marker}` and
structured result **exactly** `{"echoed": marker}` (no extra keys). This is the safe result
shape already exercised by `test_mcp_executor.py`'s `echo_once` scenario, not evidence that
such a tool is deployed. Only the designated fixture is allowed; do not select an arbitrary
catalog Action or fall back to `agentplane:v0.echo`. The latter is not MCP and returns a
different envelope.

The fixture must let the test read authoritative backend call evidence scoped to the marker,
without giving the Agent a direct MCP connection. Count actual `tools/call` invocations,
not catalog refreshes. A read-only echo plus test-owned invocation evidence needs no OAuth,
profile, static credential, or account binding work in this slice.

### Scenario and oracle

1. Give the Agent the designated group, marker, fresh idempotency key, and the existing
   workload Action Service access instructions, but not a fabricated catalog response.
   Have it GET `/v1/action-groups` and
   `/v1/action-groups/{group_key}/actions/{action_key}`. Require the designated group to be
   available with `executor_kind == "mcp"`; validate the Action's input schema against the
   arguments. Use the discovered Action `id` as the capability. Other groups may exist.
2. Have the Agent POST `/v1/action-requests` once, with that capability, exact arguments,
   and the supplied idempotency key. Require HTTP 202. A transport-ambiguous submission
   must not cause a new key or a replacement request. Do not have the test submit the
   request on the Agent's behalf or silently approve it using operator credentials.
3. Have the Agent poll GET `/v1/action-requests/{request_id}/events?after_sequence=N`,
   starting at zero and advancing only to the last returned sequence. Bound polling by
   `TURN_SECONDS`, with a delay between empty responses. Stop on `succeeded`, `denied`,
   `failed`, `cancelled`, or `execution_unknown`; only `succeeded` passes. Remaining in
   `decision_pending` at the deadline is a failure, not a skip or an implicit allow.
4. Independently read the owner's durable request list and select by the test's
   idempotency key, not by the model's claimed ID. Require exactly one match, the exact
   capability and arguments, an allow Decision, and one non-null Execution. Require
   request and Execution states both `succeeded`, `execution.error is None`, and
   `execution.result == {"echoed": marker}` using whole JSON equality.
5. Independently replay that request's events from sequence zero through the existing
   `ActionServiceClient.events` / `get` APIs. Require strictly increasing sequences, one
   `dispatching`, one `running`, and one terminal `succeeded` event, with the last
   sequence equal to the terminal request version. Repeat the read: the terminal view,
   Execution ID, and complete event list must be unchanged, and a poll after the last
   sequence must return an empty list. Deduplicate only across overlapping polling
   responses, never within the authoritative full replay.
6. Require authoritative backend evidence to contain exactly one call with the exact
   marker arguments. One Execution row or one `running` event alone does **not** prove
   one MCP call. Also require trusted transport evidence that this sandbox actually
   performed discovery, submission, and event polling; independent oracle polling must
   not satisfy the Agent's obligation. Preserve the safe responses, durable replay,
   backend evidence, and harness transcript in undeclared test outputs, including on
   failure. Never preserve bearer headers or raw secret-bearing logs.

## Needed support / integration blockers

The repository currently has the HTTP request/catalog/event models and a real MCP adapter,
but the following seams prevent this scenario from being executable:

- [The composition root](../action_service/main.py) constructs `EchoExecutor()` and does
  not start `McpActionGroupExecutor`. Its catalog defaults to empty. The
  [staging Deployment](../../../cluster/k8s/agentplane-staging/actions/deployment.yaml)
  does not configure a safe MCP group/server.
- [The staging Action egress policy](../../../cluster/k8s/agentplane-staging/egress/egresspolicy-agentplane-actions.yaml)
  allows request paths, not `/v1/action-groups` or its descendants.
- The composition root supplies no Decision providers and defaults to a disabled
  operator authenticator. A supported allow path for this safe scenario must land;
  acceptance code must not mint authority or bypass decision evaluation to finish it.
- The safe deployed fixture and its authoritative call-evidence reader are not wired.
  Neither is an independent acceptance reader for this sandbox's durable Actions:
  the app acceptance token is not a workload identity, and a model report is not a
  replacement. Reuse the existing authorized workload/operator surfaces when that
  integration lands; do not invent a new endpoint or credential mechanism here.
- Trusted attribution of discovery/submission/polling to the Agent must be connected to
  the suite's evidence reader. Merely running the same calls in an oracle does not test
  Agent discovery or polling.
- Existing acceptance targets are `manual` / `no-remote-exec` and document local Bazel
  execution. This task permits **bbr/CI only**, so a runner with staging access must be
  available before a live run can be claimed. Do not fall back to local Bazel.

**Deferred:** executable live scenario and only the read/poll/assert helpers required by
these landed seams; replay/restart chaos, catalog mutation, OAuth, profiles, bindings,
and production changes. Do not add an always-skipped or expected-failure test to imply
coverage while blocked. Passing adapter/unit tests is not MCP0 live acceptance evidence.
