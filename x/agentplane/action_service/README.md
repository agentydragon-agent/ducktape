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
already restarts on every config change. `McpExecutorBinding.config` (backend/account material) is
never exposed by any discovery view; only `McpExecutorBinding.description`, a human-authored summary of
the executor (e.g. account/credential ownership), is.

Neither the catalog nor its discovery API selects an Executor or gates `ActionRequest` submission —
that remains `db.ActionStore.submit`'s `supported_capabilities` check against the wired `Executor`.
The production composition starts one `McpActionGroupExecutor` per reviewed group with
`executor.kind: mcp`, parsed as `McpExecutorBinding`, using the stdio or streamable-HTTP
`config` described below. It passes the same group objects to discovery and the adapters, unions their
live capabilities on each submission, and routes dispatch by the exact group prefix. EchoExecutor
remains an explicitly injected unit fixture; production does not advertise its capability.

An empty catalog starts with no supported capabilities. Missing bindings and unsupported kinds fail
settings validation; missing/invalid MCP config, connection failure, or failed initial
`tools/list` aborts startup before HTTP serving or pending-request recovery. All bindings are
validated before any server is launched. Startup unwinds already-opened adapters, including a
partially started adapter; shutdown stops service tasks before closing MCP clients/refresh tasks,
then Kubernetes and database resources. After startup, catalog-refresh failures retain the landed
adapter's unavailable-and-retry behavior. OAuth, credential/profile design, and a generic executor
registry are not part of this composition.

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

## MCP executor transports

`McpActionGroupExecutor.from_group` owns one persistent MCP connection for a group. Its
`McpExecutorBinding.config` accepts a stdio launch (`command`, optional `args`, `env`, `cwd`, and
`transport: stdio`) or a credentialless streamable-HTTP endpoint:

```yaml
transport: streamable-http
url: http://127.0.0.1:8000/mcp
```

HTTP uses the pinned FastMCP `StreamableHttpTransport` and MCP session implementation, including
JSON/SSE responses and session shutdown. Both transports use the same catalog refresh, live schema
validation, safe tool-error mapping, and ambiguous-call failure path; a failed `tools/call` transport
exchange is not retried. HTTP config rejects userinfo, URL fragments, launch fields, and authentication
or header settings. The production composition uses this same transport selection. OAuth and
credential profiles are outside this seam.
