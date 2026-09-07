# Agentplane Action Service

This package is the standalone canonical coordinator for ActionRequests. It owns its PostgreSQL
schema and `/v1/action-requests` lifecycle; the Agentplane integration app, Haku Console, BFFs, and
external harnesses remain clients rather than state owners.

The v0 executable seam is deliberately small:

- one invariant request envelope, with optional `origin` and `correlation` stored only as untrusted
  provenance;
- caller-own and operator-all reads, recursively redacting credential-shaped fields;
- a human operator Decision route, with expected-version and idempotency protection and a private,
  operator-only `private_reason`, plus optional synchronous `DecisionProvider`s that run first and
  carry a bounded caller-visible `reason_code`/`reason_description` instead;
- automatic dispatch after allow, exactly one `Execution`, and no retry after dispatch may begin;
- restart recovery: pending dispatches resume immediately; dispatching/running work is left alone
  until its own bounded lease expires, then becomes `execution_unknown` and may later be reconciled
  by an authenticated late completion or an authoritative status lookup — see
  [`../docs/executor_liveness.md`](../docs/executor_liveness.md);
- one explicit `agentplane:v0.echo` fixture executor proving the service boundary; and
- a durable, restart-surviving Action event sequence as the result-delivery surface: a caller polls
  `GET /v1/action-requests/{id}/events?after_sequence=<n>` from `decision_pending` to a terminal
  state, and every submit/Decision/dispatch/terminal/`execution_unknown` transition appends exactly
  one ordered event.

## Delivery: polling, not an outbox

The durable Action event sequence (`action_event`, exposed at `.../events`) is the first-slice
result-delivery surface. `after_sequence` is the last sequence number the caller already holds;
polling with it is a cheap, idempotent no-op once no new events exist, so a caller can safely poll
from submission to a terminal state without missing or duplicating a transition.

An earlier `action_outbox` table recorded a pending-decision delivery reference for a future push
notifier. Nothing ever drained it — no consumer was wired into `main.py` — and it duplicated data
already in `action_event`/`action_request`, so it has been dropped (migration
`0004_drop_action_outbox`). The `.../events` polling surface above is not a prerequisite on the
later Event & Notification Hub, which is expected to consume the Action event sequence directly
rather than an outbox.

## Action catalog

`catalog.ActionCatalog` is the Agent-facing discovery seam: an `ActionGroup` (e.g. `github`) is the
executor/backend ownership unit, and each child `Action` (e.g. `get_file`) is namespaced under it as
`github.get_file`. `GET /v1/action-groups` lists every configured group with its Actions'
descriptions and input schemas; `GET /v1/action-groups/{group}/actions/{action}` looks up one Action
directly and 404s clearly on an unknown group or action. Both are workload-authenticated reads with
no owner-scoping, since the catalog is the same for every caller.

The catalog is reviewed runtime configuration, not a dynamic registry: `main.Settings.action_groups`
follows the same `AGENTPLANE_ACTIONS_CONFIG_FILE`-mounted-YAML convention as the integration app's
`AGENTPLANE_CONFIG_FILE` (`x/agentplane/app/main.py`), so an operator edits the catalog and the
process picks it up on restart — sufficient because ActionGroup/executor bindings change at
operator/deploy cadence, not per-request, and the app's existing `Recreate`-strategy Deployment
already restarts on every config change. `ExecutorBinding.config` (backend/account material) is
never exposed by any discovery view; only `ExecutorBinding.description`, a human-authored summary of
the executor (e.g. account/credential ownership), is.

Neither the catalog nor its discovery API selects an Executor or gates `ActionRequest` submission —
that remains `db.ActionStore.submit`'s `supported_capabilities` check against the wired `Executor`.
Binding a real ActionGroup to a live Executor is the deferred `EW` gate
(`plans/task_dag.md`), not this seam.

## Credentialless fixture auto-allow

`fixture_auto_allow` is absent by default: no automatic Decision provider is installed. To opt in,
add this to the staging Action Service YAML named by `AGENTPLANE_ACTIONS_CONFIG_FILE` and restart:

```yaml
fixture_auto_allow:
  group: mcp_fixture
```

The named `action_groups.mcp_fixture` must be a reviewed MCP binding **only to the credentialless
staging fixture server**. This setting selects the group, not an arbitrary tool or argument rule:
only `mcp_fixture.fixture_info` with exactly `{}` can receive an allow vote. The provider refuses a
missing/non-MCP group at startup and returns no opinion while the group is unavailable or no longer
discovers `fixture_info`. A newly discovered tool does not acquire auto-allow authority. The existing
executor still validates the current tool schema before calling it.

Authorization uses only the authenticated `kubernetes-sandbox` caller in `sandbox_namespaces`, with
a nonempty resolved Sandbox UID; request provenance and Agent claims cannot grant it. Reasons are
constant, bounded, and contain no request, identity, or backend values. All votes still go through
`ActionService`'s deny-dominant aggregation, durable Decision, and single-dispatch path. Nonmatches
and provider failures retain human fallback; enabling this does not enable the operator API.

This provider does not attest that an arbitrary endpoint is credentialless: the reviewed deployment
owns that binding and must not repoint the opted-in group at another server. It supplies no
credentials, capability profiles, or generic policy language. The setting alone does not wire an
MCP executor or deploy a fixture, and cannot auto-allow `agentplane:v0.echo`.

## Authentication boundaries

Sandbox calls use ordinary `Authorization: Bearer <workload token>` at this service. The runner does
not hold that token: it presents the public
`agentplane-credential-agentplane-workload` placeholder to the existing pod-local/central egress
path, whose generic `authenticatedWorkloadToken` source substitutes the already-authenticated
`agentplane-egress` bearer for the exact first-party destination rule.

At the destination, `SandboxPrincipalAuthenticator` and `SandboxPrincipalResolver` from
`//x/agentplane/sandbox_auth` perform TokenReview plus live Pod/Sandbox-owner resolution. Ownership
is derived only from the resolved Sandbox namespace and UID. ServiceAccount subject lists, identity
headers, and request `origin`/`correlation` fields are never authorization. Thread and Agent fields
remain untrusted provenance until an authoritative binding exists; workload authentication performs
no Thread or Agent lookup.

Operator/BFF calls use the separate `/v1/operator/...` surface and a separate replaceable
`OperatorAuthenticator`. The production composition is fail-closed unless explicitly configured.
Its minimal v0 file-backed bearer adapter retains only a digest and is not a claim that static
Kubernetes ServiceAccount lists are the final operator design.

Migrations run separately through `:migrate`; the server verifies the migrated schema and never
creates tables at startup. `:image` and `:migration_image` are separate OCI targets. The staging
manifests give the service its own PostgreSQL cluster and credentials rather than coupling it to the
integration app database.
