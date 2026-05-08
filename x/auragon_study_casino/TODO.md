# Study Casino TODO

## Server authority rollout

- [x] Stage 1: add server-authoritative action endpoints, append-only
      `ledger_events`, state snapshots, and an `observe` shim while keeping
      the existing Y.Doc state as the replicated projection.
- [x] Stage 2: migrate the frontend so balance-changing operations call server
      actions instead of mutating `balance` or `prize_log` directly.
- [x] Stage 3 (2026-05-08): verified at backup
      `backups/20260508T100203Z/casino-auragon.db` that the cutover at
      2026-05-07 22:49 produced 122 `server_action` ledger rows and 54
      `server_resolved` game events with zero new `legacy_client_sync` or
      `client_reported` rows since. Dropped the `STUDY_CASINO_AUTHORITY_MODE`
      flag and the `POST /game-events` client-reported intake — direct
      economy syncs now always return `rule="server_authority"`.
- [ ] Stage 5: plan a separate CRDT removal migration. Both prereqs cleared
      on 2026-05-08 against `backups/20260508T100203Z/casino-auragon.db`:
      (a) restore test — fresh study-casino pod read the backup cleanly, all
      HTTP endpoints returned the expected counts (78 game_events, 155
      ledger_events, 1 state_snapshot, 52 blackjack_hands, alembic 0003);
      (b) projection parity — replaying all 155 ledger rows from the
      `initial_authority_adoption` snapshot (credits=0, tokens=578) lands at
      credits=1, tokens=1195 with zero chain breaks, matching the current
      Y.Doc canonical balance exactly; prize_log empty on both sides.
      The legacy Y.Doc `active` map and the `frontend/src/sync.js` migration
      shim that drains it stay until the CRDT removal migration ships.

## Cleanup after enforcement

- [x] Remove legacy `POST /game-events` client-reported settle support.
- [x] Remove frontend direct balance helpers used only by legacy casino flows.
- [x] Document the authoritative economy/event model in `README.md`.

## Notes

- Pre-cutover rows in `game_events` (`source="client_reported"`) and
  `ledger_events` (`source="legacy_client_sync"`) stay readable forever; the
  Literal unions in `events.py` keep both source values so old rows
  deserialize. Do not write a migration that rewrites them.
- PVC backups are tracked in `cluster/k8s/TODO.md`; do not plan CRDT removal or
  destructive state migrations until backup and restore have been tested.
