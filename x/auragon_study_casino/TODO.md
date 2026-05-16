# Study Casino TODO

## Server authority rollout

- [x] Stage 1: add server-authoritative action endpoints, append-only
      `ledger_events`, state snapshots, and an `observe` shim while keeping
      the existing Y.Doc state as the replicated projection.
- [x] Stage 2: migrate the frontend so balance-changing operations call server
      actions instead of mutating `balance` or `prize_log` directly.
- [x] Stage 3 (2026-05-08): cutover at 2026-05-07 22:49 produced 122
      `server_action` ledger rows and 54 `server_resolved` game events with
      zero new `legacy_client_sync` / `client_reported` rows since. Dropped
      the `STUDY_CASINO_AUTHORITY_MODE` flag and the `POST /game-events`
      client-reported intake — direct economy syncs now always return
      `rule="server_authority"`.
- [x] Stage 5 (2026-05-08): CRDT removal. `pycrdt` and `yjs`/`y-indexeddb`
      are gone (the alembic 0004 migration keeps a transient pycrdt
      dependency at upgrade time only — see follow-ups). The Y.Doc layer
      was replaced with the relational schema documented in `README.md`.
      Active-session timer state moved from a Y.Map to client `localStorage`;
      sync is REST + a thin WebSocket fan-out of `{"type":"state_changed"}`.

## Cleanup follow-ups

- [x] Drop `pycrdt` from `requirements_bazel.txt`. (Done as part of the
      Postgres migration: the alembic 0001-0004 chain was deleted entirely
      since live SQLite DBs are migrated to Postgres by
      `migrate_sqlite_to_postgres.py`, not by alembic.)

## After Postgres migration — possible refactors

These are not required, just nice-to-haves surfaced during the
2026-05-16 SQLite→Postgres cutover. Defer until there's a real need.

- [ ] Push `username` into the `ServerActionMutator` signature instead of
      passing via closure. Today every endpoint's mutator captures `username`
      from the enclosing scope; making it an explicit parameter of the
      mutator callable would surface the user-scoping dependency at every
      ORM-row construction and helper invocation.
- [ ] Replace the SELECT-then-INSERT lazy-seed in `SqlStore._ensure_user`
      with a dialect-aware upsert (`INSERT ... ON CONFLICT DO NOTHING`)
      so first-touch by two concurrent requests can't race. Current
      behavior is fine for a single-replica deployment.
- [ ] Reconsider whether the casino actually needs multi-tenancy. The
      shared-schema refactor was driven by symmetry with other CNPG apps
      in the cluster; if auragon stays the only user, the `user_id`
      column adds friction without value and could be dropped.
- [ ] The CNPG cluster is provisioned with `instances: 2` (VPS-HA) but
      the app deployment is still `replicas: 1`. The DB can survive a
      single VPS loss; the app cannot. Decide whether to bump the app
      to `replicas: 2` with proper Postgres-backed session state, or
      accept the asymmetry.
- [ ] `data_dir` setting (the SQLite-fallback path) can be removed once
      we're confident no env in the wild still relies on it. Today the
      production deployment still passes `STUDY_CASINO_DATA_DIR=/data`
      because the Phase A image hasn't been rolled.
- [ ] Consider migrating the `*_at_ms` columns from `BigInteger` (Unix
      milliseconds) to Postgres `TIMESTAMP WITH TIME ZONE`. Today the
      columns are bigints because the wire format (`/state` JSON,
      frontend) uses ms-since-epoch integers, and changing the column
      type would force either a JSON schema change or a model-layer
      adapter (datetime in the DB, int on the wire). Defer until there's
      a real reason — e.g. needing time-range queries that bigint
      indexes don't serve well.

## Notes

- Pre-cutover rows in `game_events` (`source="client_reported"`) and
  `ledger_events` (`source="legacy_client_sync"`) stay readable forever; the
  Literal unions in `events.py` keep both source values so old rows
  deserialize. Do not write a migration that rewrites them.
- PVC backups live in `backups/` (gitignored — personal data); deploy a
  fresh backup before any future destructive migration.
