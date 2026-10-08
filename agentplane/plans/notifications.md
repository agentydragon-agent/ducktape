# Notification Service: remaining work

The [task DAG](task_dag.md) owns outstanding work and dependencies. This file records only
remaining acceptance and future decisions. For implemented behavior and deployment, see the
[service README](../notification_service/README.md), [App notification diagnostics](../app/README.md#notification-diagnostics),
and the [staging acceptance record](../notification_service/docs/staging_github_acceptance.md).

## Remaining live verification

- [ ] Audit remaining event/permission coverage, including PR lifecycle/reviews, pushes/ref changes,
      installation lifecycle, revoked access and fork-head correlation. An uninstalled fork is not
      covered merely because its base repository is installed. Successful ducktape subscriptions do
      not prove access to every installed repository or all supported event kinds.
- [ ] Complete live negative ingress checks (unsigned request rejected; private workload API paths
      not publicly routed). HTTPRoute acceptance, exact-path configuration and successful signed
      delivery are verified, not a substitute for these negative probes.

## Deferred: event-driven Actions consumption

If idle polling becomes a priority, replace the notification source's five-second Action-history polling in a separate implementation PR:

- Add a read-authorized SSE change feed backed by the Action Service's existing committed-event
  notifications. Its current SSE endpoint is operator-only; notifications must not gain operator
  authority to consume updates. No cross-service database access.
- Use one shared feed per notification-service replica, rather than one waiting connection per
  subscription. Treat feed messages as invalidations, not as another authoritative event log.
- On startup, reconnect, subscription creation and invalidation, drain the canonical Action event API
  from each subscription's persisted `actions_after_sequence`. Commit progress with inbox entries.
- Register the stream before catch-up reads and fence invalidations racing with processing. Waiting
  for source changes must not occupy an inbox delivery worker or hold its lease.
- Reconnect with refreshed projected credentials and bounded error backoff. Keep delivery retries and
  retention scheduling, but remove periodic Action-history reads while idle.
- Test reconnect/missed-signal recovery, concurrent events and subscription creation, ownership checks,
  and that idle subscriptions neither poll history nor prevent unrelated inbox delivery.

## Deferred decisions and follow-ups

- Home Assistant entity/event subscriptions:
  [`HOME_ASSISTANT_NOTIFICATIONS`](task_dag.md#home_assistant_notifications--entity-and-event-subscriptions).
- Extract genuinely shared source wiring as concrete implementations accumulate, not a speculative
  framework: [`NOTIFICATION_SOURCE_WIRING`](task_dag.md#notification_source_wiring--extract-shared-wiring-as-sources-accumulate).

- Recurring scheduled/cron notifications with durable scheduling and explicit missed-tick behavior:
  [`CRON_NOTIFICATIONS`](task_dag.md#cron_notifications--scheduled-notifications-for-agents).

- Structured notification-message provenance for eventual compact frontend rendering:
  [`NOTIFICATION_PRESENTATION`](task_dag.md#notification_presentation--structured-metadata-and-compact-notification-rendering).
  Preserve full agent-facing text and raw evidence; never identify notices by text prefix alone.

- Agent-visible Kubernetes rollout monitoring, potentially as a notification source:
  [`KUBERNETES_MONITORING`](task_dag.md#kubernetes_monitoring--agents-observe-rollout-progress-and-outcomes).
  Backend ownership, authorization and the watch API remain design choices.
- Authenticated discovery of App-accessible repositories and source capabilities:
  [#8981](https://github.com/agentydragon/ducktape/issues/8981). Distinguish accessible repositories,
  active subscriptions and healthy delivery without exposing other agents' subscriptions.

- Bootstrap GitHub head/fork associations, then maintain them from durable webhooks instead of
  refetching current heads on every matching pass. Keep authorization/revocation checks separate;
  define recovery for missed deliveries and out-of-order head changes before removing API refreshes.

- Consider removing `lifetime_days`. Prefer no automatic expiry; if retained, make it opt-in with
  agent warning/expiry-notification semantics.
- Add command-scoped admission/confirmation/failure tracking through Sandbox Service, resumable by
  command ID and backed by the runner's journal, so notifications need not follow conversation content.
- Consider automatic Action following or a submission convenience flag, backed by durable authorized
  intent and reconciliation rather than a best-effort second request.
- Consider narrower GitHub repository/event grants instead of shared access to every App installation.
- Bound raw GitHub receipt retention without breaking subscription boundaries, association evidence or delivery-ID deduplication.
- Additional sources/scopes: personal GitHub Notifications API, issue/repository subjects, workflow-specific
  filters, tags/releases and deployment/environment subscriptions. No promise of complete historical replay.
- Notification-triggered provisioning/resume, offline-delivery guarantees and wake budgets.
- Runner-hosted MCP context, per-session identities, cross-account delivery and successor-session retargeting.
- Proper runner RPC authentication/TLS; the authenticated service APIs do not resolve the runner-leg gap.
