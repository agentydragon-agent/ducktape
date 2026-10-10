# App use of Sandbox Service-owned Session IDs

Status: audit remaining identity requirements against deployed `CreateSession` and its tests.
The archive migration and retirement are complete; this is not a new deployment hold or
a request to repeat backfill. Close requirements already covered by code/tests and scope
separate fixes only for demonstrated gaps.

## Boundaries

- `CreateSession` reserves a public UUID, frozen spec, and private runner locator
  before runner contact. Its Open key is an opaque attempt identity, **not** a
  Session ID. The app may render an Event-log/Thread projection under the returned
  public UUID. Old Threads keep their UUIDs, `s-*` runner locators, URLs and feeds.
- The browser should send a stable opaque Open key and the _original_ overrides once;
  it must not invent a public Session ID. The app must call `CreateSession` and
  materialize the Thread idempotently after a confirmed lookup if a response or app commit is lost.
  Never retry failed creation or bootstrap automatically; only explicit discard/start-fresh
  permits a new Open after an ambiguous outcome.
- `{session_id}` in a working-directory override must be expanded **after** the
  service has reserved the public ID, not from a client-minted runner locator.
  Audit both defaults and overrides against this requirement.
- The browser deliberately persists only an Open key across reloads, not the
  original spec/setup script (they can contain secrets). A response-lost or
  restarted browser cannot replay `CreateSession` without the original inputs.
  Add a narrow authorized reservation lookup by caller, Sandbox UID and key;
  distinguish reserved-but-unattached from a confirmed runner session and make
  the app re-materialize a missing Thread from runner state. Do not broaden
  transcripts/agent reads to solve this reconciliation case.
- Discoveries from `ListSessions` can race app Open. Both must agree on the
  service UUID as the new Thread's id, while existing legacy (sandbox, native
  runner ID) mappings remain unchanged. A failed or interrupted Open must not
  produce a falsely healthy Thread; ambiguous outcome stays explicit.

## Remaining audit

1. Reconcile each boundary above against current implementation and tests before opening
   more identity work. Do not treat the old service migration/image rollout as pending.
2. Verify coverage for authorized lookup, server-side cwd expansion, response loss before
   and after service reservation, app mapping loss, reload, default drift, discovery racing
   Open, old sessions, resume, follow and command. Keep secrets out of sessionStorage.
3. Record demonstrated gaps in the task DAG; close covered requirements rather than
   repeating a rollout or a full-history scan. Any actual contract/schema change needs
   its own targeted tests and rollout review.
