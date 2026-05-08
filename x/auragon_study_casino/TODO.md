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

- [ ] Drop `pycrdt` from `requirements_bazel.txt` once alembic 0004 has run on
      the live database. Until then it's still needed as the migration's
      decoder for any pre-cutover `doc.update_blob` it encounters.

## Notes

- Pre-cutover rows in `game_events` (`source="client_reported"`) and
  `ledger_events` (`source="legacy_client_sync"`) stay readable forever; the
  Literal unions in `events.py` keep both source values so old rows
  deserialize. Do not write a migration that rewrites them.
- PVC backups live in `backups/` (gitignored — personal data); deploy a
  fresh backup before any future destructive migration.
