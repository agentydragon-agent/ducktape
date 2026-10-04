# Notification Service: remaining work

Actions subscriptions are shipped and verified in staging ([live proof #8853](https://github.com/agentydragon/ducktape/pull/8853)).
GitHub PR/branch/commit subscriptions, durable webhook intake, PostgreSQL-driven delivery, settings and
fixture-based tests are implemented in [#8891](https://github.com/agentydragon/ducktape/pull/8891).
GitHub remains disabled pending provisioning and live verification; implementation is not proof of rollout.

The [service README](../notification_service/README.md), HTTP OpenAPI and source discovery document
implemented behavior. This file tracks only remaining rollout work and deferred decisions.

## Registration and credential preparation

- [ ] Register the environment-wide **agentplane-staging** GitHub App (subject to name availability),
      distinct from the existing MCP OAuth App. Install it on the intended repositories. Any authenticated
      agent can subscribe to App-accessible repositories, including private ones; choose installations
      with that sharing policy in mind. Broader App permissions for other Agentplane uses are allowed.
- [ ] Configure notification-required repository read permissions: Metadata, Contents, Pull requests,
      Issues, Checks, Commit statuses, and Actions for workflow-run subscriptions. Subscribe to
      `pull_request`, `issue_comment`, `pull_request_review`, `pull_request_review_comment`, `check_run`,
      `status`, `push`, `create`, and `delete`; include `workflow_run`/`check_suite` if used. Verify
      installation lifecycle delivery and actual fork-PR coverage; an uninstalled fork is not covered
      merely because its base repository is installed.
- [ ] Wire the supplied `cluster/k8s/agentplane-staging/github-app.sops.yaml` through
      Secret-backed environment variables as described in the service README. Put the public
      App ID in YAML settings, not the Secret. Leave existing MCP OAuth credentials and callbacks
      untouched.

## Rollout and live verification

- [ ] Verify the deployed [staging webhook ingress](../../cluster/k8s/agentplane-staging/README.md#webhook-ingress):
      Gateway acceptance, TLS and direct delivery to **only `/v1/webhooks/github`**, with workload
      APIs remaining private. Configure the App webhook URL and matching signing secret.
- [ ] Perform the coordinated schema/service rollout without resetting the staging database. Verify
      existing Action subscriptions, inbox identities, payloads and acknowledgements survive; check
      migration completion, real server/migration image tags and replica readiness.
- [ ] Enable GitHub in YAML settings and restart the service. Verify source discovery, signed intake,
      installed-repository authorization and current installation access using the real App.
- [ ] Prove a real PR comment and check/status update through committed receipt, matching, inbox entry,
      harness notice, non-destructive read and explicit acknowledgement, with no integration-app
      dependency. Verify listener/process restart recovery and delivery-ID deduplication. A synthetic
      signed payload or successful ingress response alone is not the live acceptance proof.
- [ ] Verify failed-delivery visibility and the operator/API redelivery procedure. GitHub does not
      automatically retry failed webhook requests; durable recovery starts only after receipt commit.

## Next: event-driven Actions consumption

Replace the notification source's five-second Action-history polling in a separate implementation PR:

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
