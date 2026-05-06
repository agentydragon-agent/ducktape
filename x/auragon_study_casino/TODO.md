# Study Casino TODO

## Server authority rollout

- [x] Stage 1: add server-authoritative action endpoints, append-only
      `ledger_events`, state snapshots, and `STUDY_CASINO_AUTHORITY_MODE=observe`
      while keeping the existing Y.Doc state as the replicated projection.
- [x] Stage 2: migrate the frontend so balance-changing operations call server
      actions instead of mutating `balance` or `prize_log` directly.
- [ ] Stage 3: verify live event logs show no new legacy client-reported casino
      settlements from the current UI, then flip `STUDY_CASINO_AUTHORITY_MODE`
      to `enforce`.
- [ ] Stage 4: reject stale clients that try to sync direct `balance` or
      `prize_log` changes, while still allowing non-economy Y.Doc sync.
- [ ] Stage 5: only after restore-tested backups and projection parity checks,
      plan a separate CRDT removal migration.

## Feature flags

- [ ] Keep `STUDY_CASINO_AUTHORITY_MODE=observe|enforce` until stale clients are
      no longer expected.
- [ ] Add a live verification note before enabling `enforce`, including current
      `game_events`, `ledger_events`, and state snapshot counts.

## Current status

- 2026-05-06: server-authoritative action implementation is committed locally
  and ready for CI/deploy verification. The app should remain in observe mode
  until the deployed pod proves that current UI flows produce `ledger_events`
  and `game_events.source = "server_resolved"` without new legacy casino
  settlements.
- PVC backups are tracked in `cluster/k8s/TODO.md`; do not plan CRDT removal or
  destructive state migrations until backup and restore have been tested.

## Next live notes

- Record the deployed image tag and pod name after Flux rolls out the CI-built
  image.
- Record `alembic_version`, `game_events`, `ledger_events`, `state_snapshots`,
  and `blackjack_hands` row counts from the live SQLite databases.
- Exercise one current UI casino flow after deploy and confirm the count delta
  appears in `ledger_events` plus a `server_resolved` `game_events` row.
- If any `legacy_client_sync` ledger rows appear from the current UI, keep
  observe mode and fix the remaining direct client mutation path before
  enabling `enforce`.

## Cleanup after enforcement

- [ ] Remove legacy `POST /game-events` client-reported settle support once
      server-resolved casino history is the only path in use.
- [x] Remove frontend direct balance helpers used only by legacy casino flows.
- [x] Document the authoritative economy/event model in `README.md`.
