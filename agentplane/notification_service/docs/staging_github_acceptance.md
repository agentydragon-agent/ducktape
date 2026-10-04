# Staging GitHub notification acceptance — 2026-10-04

This is a bounded live acceptance record, not a claim that every supported event, repository or
recovery path has been exercised. Remaining work lives in the [notification plan](../../plans/notifications.md).

## Deployment and installation

- App **5188971**, `agentplane-staging`, is enabled separately from the existing MCP OAuth App.
  The operator confirmed installation on all their repositories. The test exercised
  `agentydragon/ducktape`; it did not enumerate or audit the complete installation scope.
- After [#8982](https://github.com/agentydragon/ducktape/pull/8982), staging had 2/2 updated,
  ready/available notification replicas, zero restarts, successful migration containers, and Flux
  Ready/Healthy. Source discovery advertised `actions` and `github`; the webhook HTTPRoute was
  Accepted with resolved references. [Recorded rollout evidence](https://github.com/agentydragon/ducktape/issues/8956#issuecomment-5983967691).
- The observed image was `devel-20261004200821-e77f1d7`. No database reset, credential rotation or
  imperative deployment change was used. The existing session inbox retained its identity and
  acknowledged prefix through cursor 5 before the live GitHub test.

## Live delivery

The agent subscribed through the authenticated notification API, using its explicit sandbox
incarnation and runner session. No integration-app API was used in this test.

- A `devel` branch subscription received **13 real GitHub events**, inbox cursors **6–18**:
  `workflow_run`, `check_run`, `check_suite` and `status`. These were new deliveries from ongoing CI,
  not synthetic signed payloads or replayed historical checks. Runner notices appeared in the
  agent conversation; stored notice receipts reported confirmation.
- An approved Action posted [a test comment on PR #8982](https://github.com/agentydragon/ducktape/pull/8982#issuecomment-5984066218).
  Its `issue_comment.created` delivery, `f6a2f040-c031-11f1-9b39-370040a9f3e8`, produced **one**
  inbox entry at cursor **20**, matching both overlapping PR-comment subscriptions. The stored body
  matched the posted comment, and the notice reached the harness.
- Reads did not advance acknowledgement. The agent explicitly acknowledged the handled prefix
  through **24**, including the test Action's progress events, and cancelled all smoke-test
  subscriptions. No CI rerun was required.

## Limits

Overlap deduplication does not prove same-delivery-ID redelivery, restart recovery or access-loss
behavior. Those tests remain open, as do broader event/fork coverage and live negative ingress
probes. Installation across all repositories is operator-reported, not a discovery-API result.
The test showed several small notices during bursts; configurable debounce is proposed in
[#8988](https://github.com/agentydragon/ducktape/pull/8988), not part of this deployed proof.
