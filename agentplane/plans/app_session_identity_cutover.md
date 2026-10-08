# App use of Sandbox Service-owned Session IDs

Status: draft cutover checklist; do not deploy an app using `CreateSession` until the
service migration/image rollout, read-only reconciliation, and new/legacy integration tests
pass. This changes **new session identity**, not raw Session Event authority or the
separate existing-history backfill.

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
  service has reserved the public ID. Today the browser expands it from its
  client-minted `s-*` ID; blindly changing only the Open RPC would put files in
  a directory named for the wrong identity. Test both defaults and overrides.
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

## Readiness and rollout

1. Verify migration `0002_session_open_reservations`, current Sandbox Service
   image and migration image are installed and both replicas are Ready. Staging rollout for commit `8af0d0a` reached 2/2 Ready (generation 45)
   on 2026-10-08; migration `0002` was previously verified. Confirm again before merge.
2. Finish lookup, server-side cwd expansion, and app/browser changes. Exercise
   response loss before and after service reservation, app mapping loss, reload,
   default drift, ingestion racing Open, old sessions,
   resume, follow and command. Preserve secrets out of sessionStorage.
3. Only make the app cutover PR ready after staging service rollout and CI. The
   app deploy must not assume that the raw Event-log/Thread history backfill or
   service-side ingestion has happened. Backfill remains a separate operation.
