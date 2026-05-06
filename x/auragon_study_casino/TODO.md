# Study Casino TODO

## Server authority rollout

- [ ] Stage 1: add server-authoritative action endpoints, append-only
      `ledger_events`, state snapshots, and `STUDY_CASINO_AUTHORITY_MODE=observe`
      while keeping the existing Y.Doc state as the replicated projection.
- [ ] Stage 2: migrate the frontend so balance-changing operations call server
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

## Cleanup after enforcement

- [ ] Remove legacy `POST /game-events` client-reported settle support once
      server-resolved casino history is the only path in use.
- [ ] Remove frontend direct balance helpers used only by legacy casino flows.
- [ ] Document the authoritative economy/event model in `README.md`.
