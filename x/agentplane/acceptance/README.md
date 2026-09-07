# Agentplane acceptance suite

Scenarios run against a **deployed** Agentplane: the suite creates real sandboxes through the app's
HTTP API, opens sessions on the real harnesses, and asserts on what the egress proxy recorded. It is
not a unit test with a live backend — it is the check that the deployed system does what
<../egress/SPEC.md> says it does, and that a session's standing instructions reach the model that
serves it.

The general egress and instruction scenarios run on **both harnesses**. The runner protocol is the
same for Claude and Codex, so one test body covers both: the `provider` fixture is parametrised over
`Provider`, and `model` asks the deployment which models it offers for that harness rather than
hardcoding one. `test_launch_presets` instead exercises the configured `public-coder` preset's
intentional Codex default, Sandbox binding, bootstrap marker, inherited fields, and local override.

## MCP integration

`//x/agentplane/acceptance:test_mcp` drives real Claude and Codex agents. It is
manual deployed acceptance, **not runnable from agent pods** under the current
bbr/CI-only execution policy. No approved CI runner currently has staging identity
and connectivity. Building this target or running the remote-safe assertion tests
is not evidence that deployed acceptance passed.

### Scenarios and authority

- **P0 behavior — discovery + echo:** discover the credentialless Everything group
  and `echo(message)`, submit the same bounded message three times, then replay
  after completion. Independently require one ActionRequest, the same Execution ID,
  exact `execution.result == {"content": ["Echo: <message>"]}`, provider
  `mcp_fixture` / reason `credentialless_fixture`, and exactly one ordered history:
  `decision_pending → allowed → dispatching → running → succeeded`. The event cursor
  at the tip must return `[]`.
- **P0 behavior — no human decision:** a valid echo message longer than 200 characters
  lies outside the fixture provider's auto-allow scope. Require `decision_pending`,
  no Decision, no Execution, and only the initial event. Ask the agent to try the
  **existing** operator decision path with its workload placeholder; require a ring
  record of the attempt, then recheck pending/no Execution three times over six seconds.
  This is a bounded observation, not a claim about all future time.
- **P0 behavior — explicit operator deny/allow:** separate parametrized cases submit
  the same non-auto-approved echo through the agent, then use the existing operator
  decision client with expected version + decision idempotency key. Deny requires
  `denied`, a `human_operator` deny Decision, no Execution, and exactly
  `[decision_pending, denied]`. Allow requires the exact echo result and one complete
  execution history. Repeated decision calls, including a stale-version replay after
  terminal, must leave the request and events unchanged.

**Needed support:** an independent observer runs `/usr/bin/curl` using `kubectl exec`
in the suite-owned runner Pod, explicitly through its normal loopback sidecar. Only
GETs, only the public workload placeholder; no token reads, no direct backend calls,
no port-forwards, no live deployment edits. Staging already declares `pods/exec`
authority in its acceptance role and includes curl in the runner image. Missing exec
RBAC, curl, route, workload authentication, or a non-200 response fails loudly. This
observer verifies service responses independently of the model; it is not intended
to defend against a malicious agent replacing the runner's installed curl binary.
The Action service and sidecar URLs are the checked-in staging contracts; changing
only the app URL or namespace does not retarget these MCP scenarios.

The existing app decision-ring API is collected **before** observer reads. It must
show admitted discovery, at least three POSTs, and a read of the reported request.
Unauthorized, unavailable, empty, or evicted evidence fails, never skips. The ring
proves HTTP admission, **not backend invocation counts**. The no-Execution/no-dispatch
assertion is the authoritative evidence that denied/pending work was not dispatched
by the Action Service. No backend-log claim is made: Everything currently exposes no
reviewed, complete per-invocation audit contract, and Action request IDs are not passed
to its echo tool. Pod logs are not collected speculatively or treated as proof of zero
calls. Exact output plus stable Execution ID and a single dispatch history are the
available API-level exactly-once evidence, not a claim of universal external-effect
exactly-once delivery.

### Output contract and diagnostics

The agent's final report has exactly this schema (extra properties forbidden):

```json
{
  "type": "object",
  "required": ["request_id"],
  "additionalProperties": false,
  "properties": {"request_id": {"type": "string", "format": "uuid"}}
}
```

The UUID is only a locator. The independent observer cross-checks its idempotency
key, group/name, exact fresh marker argument, and the entire fresh Sandbox's request
list. A fabricated result or plausible model prose cannot satisfy these assertions.
Authoritative report schemas are `ActionRequestView` and `ActionEventView` in
`action_service/models.py`; discovery is validated against `ActionGroupView` and
`ActionView`, whose closed schemas exclude executor configuration.

Bazel undeclared outputs contain:

- `<sandbox>-actions.json`: ordered `[{"path": "<GET path>", "body": <whole JSON response>}]`.
  Action responses carry request IDs, keys, marker arguments, decisions, execution
  results, and event sequences. Updated after every successful observer read so a
  later assertion failure retains earlier evidence.
- `<sandbox>-ring.json`: the app's credential-free `Decision` records restricted to
  the Action host, captured before observer traffic. No headers, tokens, or raw Pod
  logs are stored. Transport failures show sandbox/path/status, not arbitrary bodies.

Wrong marker means output propagation failed; extra request/Execution ID or dispatch
means idempotency failed; missing/out-of-order events means audit/cursor contract
failed; pending/denied with any Execution is an authority failure. Keep artifact files
with test output. Existing sandbox fixture teardown suspends/deletes on assertion or
transport failures; each run uses a fresh Sandbox identity and random keys. As with
the rest of this suite, abrupt process death still requires deliberate cleanup.

### Current blocked contracts

**Observed source contract:** staging `actions/settings.conf` has no
`operator_bearer_file`; `action_service/main.py` therefore selects
`DisabledOperatorAuthenticator`. The app has no Action BFF forwarding route.
The service does implement
`POST /v1/operator/action-requests/{id}/decision`, but a workload placeholder or app
ServiceAccount token does not become operator authority. Both explicit deny and
human allow are **blocked on current staging auth/route**, not simulated successes.

An operator running on an approved controlled host may select an **already configured**
HTTPS operator service route with `AGENTPLANE_ACCEPTANCE_OPERATOR_URL` and a host-owned
bearer file with `AGENTPLANE_ACCEPTANCE_OPERATOR_TOKEN_FILE`. These fixtures do not
create credentials or enable the adapter. The bearer is read in-process, never given
to the agent, put in argv, or written to artifacts. The operator cases deliberately
FAIL with `BLOCKED operator decision` when these are absent; route/auth failure also
fails preflight. Running these cases authorizes the fixture to submit the named
allow/deny decisions as the operator, not to test a human UI click or invent a BFF.

**Deferred — caller withdrawal:** `action_service/api.py` and its clients have no
caller withdrawal/cancellation endpoint. `ActionState.CANCELLED` is an executor
outcome, not evidence of caller cancellation authority. No fake withdrawal test or
new semantics were added. A future withdrawal slice needs a real API contract and
pre/post-dispatch behavior before it can acquire a real-agent acceptance test.

Remote-safe validation (does not contact staging):

```bash
bbr test //x/agentplane/acceptance:test_action_evidence
bbr build //x/agentplane/acceptance:action_evidence //x/agentplane/acceptance:test_mcp
```

The assertion tests are negative controls (wrong marker, hidden Execution, repeated
dispatch, broken sequence, denied without Decision), not substitutes for live agents.

## Running it

Not in CI, and not on RBE: the target is `manual`, so `//...` never selects it, and it needs a
kubeconfig and a route to the cluster.

```bash
bazelisk test //x/agentplane/acceptance:all --test_output=streamed --test_arg=-s
```

By default it tests `https://agentplane-staging.allegedly.works` and mints its own bearer token with
`kubectl -n agentplane-staging create token agentplane-agent --audience=agentplane`. That call needs
RBAC on `serviceaccounts/token`, and the app only admits subjects its `AGENTPLANE_TOKEN_SUBJECTS`
names, so a token for any other ServiceAccount is refused with `403`.

Override any of it through the environment:

| Variable                                | Default                                      |
| --------------------------------------- | -------------------------------------------- |
| `AGENTPLANE_ACCEPTANCE_URL`             | `https://agentplane-staging.allegedly.works` |
| `AGENTPLANE_ACCEPTANCE_TOKEN`           | minted with `kubectl`                        |
| `AGENTPLANE_ACCEPTANCE_NAMESPACE`       | `agentplane-staging`                         |
| `AGENTPLANE_ACCEPTANCE_SERVICE_ACCOUNT` | `agentplane-agent`                           |

### Controlled-host preflight

Run the suite from a controlled NixOS host, devbox/VM, or FHS-compatible agent
container. Do not use `bbr`/`bb remote` for this suite: the completed test
process must stay on the caller, where it can use the caller's Kubernetes
credentials and network path. BuildBuddy-hosted runners do not inherit the
caller Sandbox workload token or the current egress substitution path.

Before starting a long run, check the client-side seams separately:

```bash
command -v bazelisk kubectl
bazelisk version
kubectl config current-context
kubectl -n agentplane-staging auth can-i create serviceaccounts/token \
  --resource-name=agentplane-agent
kubectl -n agentplane-staging create token agentplane-agent \
  --audience=agentplane --duration=60s >/dev/null
```

The preflight must not print or save the returned token. If the token command
fails, fix caller RBAC or kubeconfig before launching the suite. If Bazel
fails while loading the module graph, fix the caller's Bazel/repository-rule
runtime before investigating staging.

### Failure classification

Use the first point at which the run fails to choose the next investigation:

| Observation                                                   | Likely seam                                                                  |
| ------------------------------------------------------------- | ---------------------------------------------------------------------------- |
| No `accept-*` Sandbox is created                              | Bazel client, module/repository rules, kubeconfig, or acceptance-token setup |
| Sandbox is created but never becomes ready                    | Scheduling, image pull, runner bootstrap, or staging capacity                |
| App rejects the initial API request                           | Acceptance token audience, subject allowlist, or app ingress                 |
| Model turn hangs and the decision ring is empty               | Sandbox proxy environment, proxy route, or model ingress path                |
| Ring records a deny for an expected destination               | Egress policy/binding or destination URL mismatch                            |
| Rules discovery succeeds but destination authentication fails | Placeholder substitution or independent destination authentication           |
| Test assertions pass but teardown reports a failure           | Runtime cleanup/reconciliation; inspect the named Sandbox before rerunning   |
| Process is killed and `accept-*` Sandboxes remain             | Expected teardown limitation; clean them up deliberately before the next run |

Keep the complete test output and the proxy/app decision evidence together.
The model transcript explains what the agent attempted, but the decision ring
is the authority for what the proxy actually served.

### Where an agent can run it

Agent pods must use `bbr`/CI, never local Bazel or pytest. This deployed suite is
`manual` / `no-remote-exec` and lacks an approved CI runner with staging identity and
connectivity. Therefore it is **blocked from agent pods**; do not disable remote
execution/caching or mint substitute credentials to work around that boundary.
The controlled-host instructions above are operator-only, not an agent-pod fallback.
See [repository instructions](../../../AGENTS.md).

Afterwards, check that nothing leaked: `kubectl -n agentplane-staging get sandboxes.agents.x-k8s.io`
should show no `accept-*`.

## What it costs

Each scenario provisions a Pod and runs turns on the cheap-experiments LiteLLM key with Haiku, so a
full run is minutes and a few cents. Sandboxes are suspended and deleted in fixture teardown,
including after a failure; a teardown that cannot delete one fails loudly, because a leaked sandbox
holds a PVC and a node slot on staging.

## TODO: sweep sandboxes a killed run leaks

Fixture teardown suspends and deletes every sandbox a scenario created, including after a failure.
It cannot run if the process is killed outright — a Bazel timeout, a `^C`, a dropped connection —
and each leaked sandbox holds a PVC and a node slot on staging until someone notices.

What that wants is a sweep at session start: list the sandboxes whose names carry this suite's
`accept-` stem, and delete any older than a run could plausibly be. Deliberately not built yet,
because the stem is the only marker and a real sandbox someone named `accept-something` would be
destroyed by it — a label the app sets on suite-created sandboxes, or a dedicated namespace, is the
thing to add first.

## Why it asserts on the ring, not on the agent

The agent's own account of a tool call is prose. "I fetched the repository" is equally consistent
with a request the proxy admitted, a request that never reached the proxy, and a model that did not
run the command at all. The proxy's decision ring is the system's record of what it actually served,
so that is what a scenario checks; the turn's output is carried into the failure message, where it
explains a failure rather than deciding one.

Where a scenario has to look _inside_ the sandbox, it never asks the model to print a secret. A
model that declines to echo a credential, or redacts it, produces output with no credential in it —
which would satisfy an "is it absent" assertion for entirely the wrong reason. The command prints a
verdict token instead, and the scenario fails unless one of the two tokens actually comes back, so a
refusal reads as a failure rather than as an absence.

This suite exists because the last gap of that shape — a runner that dropped the sandbox's proxy
variables, so every call bypassed the proxy and hung with an empty ring — sat behind a fully green
unit suite until someone drove the deployed app by hand.

`test_instructions` is the one scenario that cannot follow the rule: no part of the system records
that a system prompt arrived, so the model obeying the instruction is the only evidence there is.
Its answer to that is a marker token no model emits on its own plus a control session, opened with
no instructions on the same sandbox and given the same prompt, that must not produce it.
