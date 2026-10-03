# Standalone subscriptions and notifications

Status: **Actions provider shipped and verified end-to-end in staging (2026-10-03).**
Next slice: **GitHub PR updates and comments**, with the proposed design below. The implemented
[service contract](../notification_service/README.md), HTTP OpenAPI, and provider discovery are the
source of truth for the existing API, storage limits, and recovery behavior; the old illustrative
pre-implementation API is no longer a backlog item.

## Shipped / burned down

- [x] Independent Sandbox Service for provisioning, explicit destination/ServiceAccount bindings,
      session access, commands, and event following. No integration-app dependency or runner callback
      to notifications. The app remains a client and owns its archive.
- [x] Standalone notification HTTP API, authenticated subscription CRUD/provider discovery, owned
      PostgreSQL database/migrations, multi-replica fenced workers, quotas, retention, and error state.
- [x] Actions-first provider: canonical event history, source ownership checks despite the service's
      broad read access, replay after subscribe races, retained payloads, and overlapping-match deduplication.
- [x] Session inboxes: committed cursor prefix, non-destructive reads, explicit monotonic acknowledgement,
      and notification coverage independent of acknowledgement. No repeated reminders for unread entries.
- [x] Native delivery through Sandbox Service: persisted command identity, admission versus causal
      harness confirmation, lost-response recovery, no automatic startup/resume.
- [x] Agent egress and initial subscribe/read/ack prompt guidance with explicit destination IDs.
- [x] Long-session delivery fix: checkpoint the journal tail before the first attempt, rather than
      replaying unrelated history. After an attempt, recover receipts without skipping entries.
- [x] App-independent native Claude/Codex acceptance, including busy/idle harnesses and lost responses.
- [x] Live staging smoke: replayed five Action events, received the automated message, verified native
      confirmation, explicitly acknowledged through inbox cursor 5, and cancelled only the test
      subscription. Payloads remained stored and the session inbox remained usable.

Evidence: [implementation #8845](https://github.com/agentydragon/ducktape/pull/8845),
[HTTP cleanup/schema #8851](https://github.com/agentydragon/ducktape/pull/8851), and
[delivery fix and live proof #8853](https://github.com/agentydragon/ducktape/pull/8853).
The verified staging image was `devel-20261003083540-82f0720`, with two updated/ready replicas.
This is not a claim that every production environment, backup/restore scenario, or native crash
window has been audited.

**In review, not shipped:** [#8860](https://github.com/agentydragon/ducktape/pull/8860) improves agent
advice about short waits, approval notifications, independent parallel work, and explicit handling.
Initial API instructions already shipped; the richer advice must not be counted as deployed yet.
Prompt changes apply to new sessions, not immutable existing session specs.

## GitHub: proposed next slice

### Agent-facing subscription

Make the common request **follow this PR**, rather than requiring agents to understand all the
webhook-to-PR joins. Preserve GitHub's vocabulary for event selection and retained payloads.
**Decision:** keep routing/lifecycle fields in a common subscription envelope, with a nested `source`
discriminated union selected by `source.provider`. `GitHubSource` owns `repository`, `subject`, and
`events`; `ActionsSource` owns `request_id` and `after_sequence`. These are concrete provider-defined
models, not optional fields on a universal source model or an untyped filter dictionary. Each provider
owns validation and its schema, exposed through OpenAPI and `/v1/providers`.

The following is the proposed GitHub request fragment, not a deployed schema; common
`destination_ref`, `session_id`, `client_key`, and `lifetime_days` fields are omitted:

```json
{
  "source": {
    "provider": "github",
    "repository": "agentydragon/ducktape",
    "subject": {"kind": "pull_request", "number": 8860},
    "events": [
      {"event": "pull_request"},
      {"event": "issue_comment", "actions": ["created", "edited"]},
      {"event": "pull_request_review", "actions": ["submitted"]},
      {"event": "pull_request_review_comment", "actions": ["created", "edited"]},
      {"event": "check_run", "actions": ["completed"]},
      {"event": "status"}
    ]
  }
}
```

The Actions variant is `source: {"provider": "actions", "request_id": "REAL_ACTION_UUID",
"after_sequence": 0}`. GitHub subjects may themselves use a provider-owned tagged union; they are
not subjects that every notification provider must implement. Reject fields/combinations belonging
to another variant. In particular, do not add Actions replay sequence semantics to GitHub by analogy.

Omitting `events` should use a documented PR-follow default covering lifecycle, discussion, reviews,
completed check runs, and commit statuses. Explicit selection permits comments-only or checks-only
subscriptions. Keep native `pull_request` action values such as `synchronize`, `closed`, and
`ready_for_review`; merge remains `pull_request` / `closed` plus GitHub's merged fields, not a new
invented upstream event. `issue_comment` must be a comment on the selected PR, not a same-number
object from another repository. General reviews and inline review comments are distinct events.

A tagged subject gives a natural extension to repository, issue, or commit/SHA subscriptions.
Implement the PR subject first; do not advertise other subjects before their matching and authorization
work. `check_suite` and `workflow_run` can be optional additions, not extra default notifications for
the same CI activity. This is not GitHub's personal Notifications API and requires no browser/user OAuth
session in the integration app.

### Matching PR CI events correctly

Checks/statuses are associated with commits, not reliably with a PR number. Resolve the PR's current
head through the provider's GitHub read access; refresh on `pull_request` / `synchronize`. Correlate
by repository identity and SHA, not a global SHA lookup or branch-name substring. Handle empty
`pull_requests` arrays, fork PRs, multiple PRs sharing a head, delayed deliveries, and out-of-order
head/check updates. Ambiguous or temporarily unresolved matches need bounded reconciliation rather
than silently dropping a relevant completion.

Default intent is **follow the PR as its head changes**, not a fixed commit. Keep the event SHA in the
payload and do not present an old-head completion as current PR health. Define and test this behavior
before enabling checks/status subscriptions. GitHub remains authoritative for current PR/CI state;
we do not build another required-checks/mergeability evaluator.

### Direct webhook ingress (decided), provider-owned verification

**Decision:** GitHub targets the notification service directly over HTTPS, for example a provider route
`POST /v1/webhooks/github`. There is no integration-app relay or separate webhook/demultiplexing service.
The notification service verifies, durably ingests, and demultiplexes deliveries to subscriptions. Use one configured repository/App webhook per event source, never one webhook per agent
subscription. The existing Flux webhook handles push/registry reconciliation; it is not an Agentplane
notification ingress and should not be repurposed to couple these services.

The provider verifies `X-Hub-Signature-256` against the exact raw body with a configured signing secret,
validates the event and repository/installation against the source configuration, and applies body/rate
limits before durable acceptance. This route uses GitHub authentication, not agent workload bearer auth;
agent subscription/inbox routes remain workload-authenticated. Provision secrets, HTTPS ingress, and
narrow network access declaratively, without exposing credentials to agents.

Persist verified delivery metadata and the actual GitHub payload before acknowledging acceptance.
Use the source plus `X-GitHub-Delivery` as a retry identity, detect conflicting reuses, and deduplicate
fanout into each inbox even when subscriptions overlap. Perform fanout asynchronously with existing
PostgreSQL fencing/recovery; no new message broker. An acknowledged webhook must survive worker restart.
Return a failure if durable acceptance fails rather than acknowledging and losing it.

GitHub webhooks do not provide the Actions provider's complete historical replay contract. Establish
an explicit local subscription boundary against durable ingress so arrivals during creation are not
lost. V1 can be live-follow from that boundary: advise agents to **subscribe, then read current PR
state** so an already-completed check does not leave them waiting. Do not invent historical webhook
notifications from a current snapshot. Redelivery/local retained-delivery replay is distinct from
reconstructing everything that happened before the webhook was configured; broader backfill is deferred.

### Authorization and credentials: decide before wiring

Webhook authenticity is not subscriber authorization. A provider's ability to receive/read a private
repository must not give every workload access to its payloads. Resolve repository names to stable
GitHub repository IDs and bind them to explicit authorized ServiceAccounts/source configuration;
enforce access at creation and before fanout, and stop future matching after revocation. Retained
payload access/revocation semantics must be explicit, not accidentally inherited from a broad service token.

Proposed first rollout: a small configured repository set, beginning with public `agentydragon/ducktape`,
with explicit workload grants. Do not expose arbitrary repository/private installation subscriptions.
Use a provider-owned read credential with only required permissions. Prefer a dedicated read-only GitHub
App for installed repositories; a repository webhook plus a suitably scoped existing read credential is
also a viable initial deployment. Do not silently widen the existing write-capable automation App or
reuse an operator's integration-app session.

Open operator choices:
1. Initial repositories and whether private repositories must work in this first slice.
2. A dedicated/read-only GitHub App installation webhook versus managed repository webhooks with
   an existing suitable read credential. Confirm actual event coverage and provisioning ownership.

### Small, data-preserving provider generalization

Current storage and wire models contain Action-specific `request_id` and sequence fields. Add only
the provider-tagged subscription/event identity needed by the second real provider. Keep provider
filter/content schemas concrete and discoverable through `/v1/providers`; no speculative plugin framework
or universal event DSL. The current Actions request has flat provider/request fields; moving to the
nested `source` union is an explicit wire-contract change, not its existing shape. Preserve existing
Actions clients with a narrow compatibility boundary or an explicitly versioned migration, rather
than silently breaking them or retaining two internal source representations. Explicitly version any
necessary response-envelope change rather than fabricating Action UUIDs for GitHub events.

Use an additive migration/backfill that preserves existing subscriptions, entries/payloads, cursors,
acknowledgements, notice IDs, and receipt checkpoints. Rollout must tolerate old/new worker overlap;
activate GitHub sources only when all serving workers understand the new provider. Reuse existing
inbox/HWM, retention, notice delivery, and Sandbox Service authorization instead of duplicating them.

### Build order / remaining work

- [ ] Agree on source registration, repository grants, and the PR-follow/default-event contract.
- [ ] Implement the minimal provider-tagged models and data-preserving storage migration; retain Actions behavior.
- [ ] Add verified, durable webhook intake, source deduplication, and restart-safe fanout.
- [ ] Add PR/comment/review matching, then head-aware checks/status matching and bounded reconciliation.
- [ ] Wire declarative source credentials/webhooks/ingress/egress, provider discovery, and agent examples.
- [ ] Prove signed GitHub delivery through the real inbox/harness/read/ack path in staging, with no app dependency.

Acceptance includes invalid signature and oversized-body rejection; unauthorized repositories/SAs;
retry/conflicting delivery IDs; overlapping subscriptions; creation/cancellation races; fork/head-change
and empty-PR-list CI cases; source revocation; preserved Actions data; concurrent replicas; and restart
after HTTP acceptance but before fanout. Reuse the native delivery tests rather than building another
runner test stack. Live proof should cover a real PR comment and check/status update, not only a synthetic
signed payload or a successful ingress HTTP response.

## Still deferred

- Command-scoped admission/confirmation/failure tracking through Sandbox Service, resumable by command
  ID and backed by the runner's existing journal. Notifications does not need conversation content;
  today's tail checkpoint is the bounded fix, not the eventual interface.
- Automatic Action following or a submission convenience flag; durable authorized intent and reconciliation
  are required, not a best-effort second HTTP request.
- GitHub personal Notifications API, generic arbitrary filters, automatic webhook creation per agent,
  complete historical reconstruction, and non-PR subjects until their semantics are implemented.
- Notification-triggered provisioning/resume, offline-delivery guarantees, and wake budgets.
- Runner-hosted MCP context conveniences, per-session identities, cross-account delivery, or implicit
  retargeting across successor sessions. ServiceAccount authority and explicit destinations remain.
- Proper runner RPC authentication/TLS. Service APIs are already authenticated; this is the runner-leg follow-up.
