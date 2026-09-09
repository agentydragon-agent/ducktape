# Asynchronous approvals: remaining delivery work

Human Decisions, synchronous provider aggregation, shared notes, durable cursor-based events,
notification-driven bounded waits, and owner-only pre-claim cancellation are implemented. Use the
[Action Service specification](../action_service/SPEC.md) and [README](../action_service/README.md),
not a second lifecycle contract here. Native harness approvals remain disabled under the
[runner contract](../runner/SPEC.md).

## Web push approval notification (`NOTIFY`)

Put the first implementation in the integration app: its frontend owns the service worker, browser
subscription, notification click handling, and Approve/Deny presentation; its backend/BFF owns
subscription registration/revocation and web-push delivery. The BFF calls the Action Service's
canonical authenticated Decision endpoint. The Action Service remains the source of truth for
pending Actions, Decisions, and durable events; it does not own browser subscriptions, VAPID keys,
or a second approval lifecycle.

Notify the operator that an ActionRequest needs review with only safe/redacted context. Stale or
duplicate buttons cannot overwrite a winning Decision or create a parallel human lifecycle. The
polling Actions page remains the fallback when push is unavailable. A later Event & Notification
Hub may take over delivery, but is not a prerequisite for this first slice. Prove notification
retries and review races without duplicate effects.

This is optional delivery, not a prerequisite for the current polling UI or human-approved
Claude.ai acceptance. The deployed browser/BFF verification is `APPROVALUI` in the
[task DAG](task_dag.md).

## Concrete progress and unknown-outcome observations

A concrete long-running consumer must define supported bounded, authorized progress/status reads.
Use authoritative reconciliation only where the backend supports it; otherwise an unknown outcome
remains unknown. Tie observations to the existing Execution, without another claim or replay.
Adapter acceptance belongs in
[operations and access](operations_and_access.md).

## Originating-Thread delivery (`ING`)

Consume the canonical Action event sequence for notification matching, batching, rate limits,
offline delivery, and Thread wake/ingress. Preserve individual events and ordering; do not add a
second Action outbox or event store. Cross-Identity delivery requires an explicit read policy.
Thread input queueing/replay is independent `INPUT_DELIVERY` work and requires native Claude/Codex
research and capture review before common-protocol changes.

## Provider-error log safety (`PROVIDERLOG`)

The previous plan claimed raw provider exception text was never logged. Current
`ActionService._ask` calls `logger.exception`, and the test only inspects `record.getMessage()`,
excluding traceback formatting. Prevent sensitive exception material in rendered logs and test
the complete formatted output with a sentinel secret. Durable bounded error codes and provider
aggregation behavior already exist and must remain unchanged.

## Configurable policies

[Action policies](action_policies.md) owns configurable mandatory authorization bounds and reusable
auto-approval deciders. Failure of a mandatory bound must fail closed rather than becoming a
no-opinion vote overridden by another provider. This future distinction is not a claim about the
current optional provider aggregation. The first external OAuth slice uses human approval and
does not depend on selecting policy storage or composition.

Expiry, operator-presence heuristics, LLM deciders, a policy DSL, and standing-grant issuance remain
outside this delivery slice.
