# Props Backend TODO

## High Priority (Blocking User Visibility)

- [x] **Fix "0 definitions" bug**
  - Fixed: Now queries all critic definitions, not just those with stats rows

- [x] **Fix Active Runs visibility during validation jobs**
  - Fixed: `/active` endpoint now queries both registry and database for IN_PROGRESS runs

- [x] **Add structured logging**
  - Added: Configurable via PROPS_LOG_LEVEL and PROPS_LOG_FILE env vars
  - Logs to stderr (always) and file (if configured)
  - Logs app startup/shutdown, job creation, run progress

- [ ] **Show incomplete runs properly**
  - Don't count incomplete runs in stats aggregates
  - Add "X runs in progress" indicator when applicable
  - Query: `SELECT COUNT(*) FROM agent_runs WHERE status = 'IN_PROGRESS'`

## Medium Priority (UX Improvements)

- [ ] **Use WebSocket for live updates**
  - WS endpoint exists: `WS /api/runs/{run_id}/stream`
  - Frontend currently polls; switch to WS for run detail view
  - Consider WS for active runs list too (broadcast channel)

- [ ] **Add runs browser/table view**
  - New page: Full `agent_runs` table with filters
  - Columns: ID, type, definition, model, status, created_at, example info
  - Click through to run detail (existing RunDetail.svelte)
  - Filter by: status, agent_type, definition, split

- [ ] **Add train/valid split control to trigger form**
  - ValidationRunTrigger.svelte needs split selector
  - Backend: `POST /api/runs/validation` needs split parameter
  - Query examples by split when selecting

- [ ] **Improve status display**
  - Replace single-letter codes (Z, S, C) with descriptive labels
  - Full words or tooltips: "Zero Recall", "Max Turns", "Context Exceeded"

## Lower Priority (Polish)

- [ ] **Stats display improvements**
  - Move total available count to subheader: "Valid Partial (N=171)" instead of "5/171" per row
  - Per-row just shows evaluated count: "5" not "5/171"
  - Full 95% CI display: "45.2% [38.1% - 52.3%]" or "45.2% ±7.1%"
  - Longer column names: "Zero Recall", "Max Turns", "Context Exceeded" (not Z/S/C)

- [ ] **Migrate `props stats` to frontend**
  - All metrics from CLI `props stats` should be in web UI
  - Tables: definition leaderboard (done), by-example, by-occurrence
  - Include props stats subcommands: `critic-leaderboard`, `example`, `occurrence`

- [ ] **Live rollout display**
  - Overall view: grid of validation jobs with progress bars
  - Per-rollout: Timeline of runs (critic->grader pairs)
  - Real-time status updates via WS

## Future

- [ ] **Consolidate to `props/{core,backend,frontend}`** with single global `.envrc`

- [ ] **Ground truth update workflow**
  - Infrastructure exists: `GraderTypeConfig.canonical_issues_snapshot` stores TPs/FPs used at grading time
  - Detection exists: `props/src/props/grader/staleness.py:identify_stale_runs()` compares stored vs current
  - CLI uses it: `props stats` includes "Grader Run Staleness Check" section
  - **BUG:** Staleness check marks everything as stale
    - Root cause: Comparing `expect_caught_from` which is test coverage metadata, not grading content
    - Semantic staleness should compare: TP/FP IDs, rationales, occurrence locations (files + line ranges)
    - `expect_caught_from` is irrelevant for "did the issues change?" - it's about which file sets trigger detection
    - Fix: Compare only the fields that affect grading decisions, exclude `expect_caught_from`
  - **TODO for frontend/API:**
    - Fix staleness detection logic first
    - Expose `/api/stats/stale-runs` endpoint
    - Show stale run count/list in dashboard
    - Add "regrade stale runs" action button
  - **Optimization ideas:**
    - Timestamp-based: Compare `updated_at` on GT vs `canonical_issues_snapshot_time` on grader run (cheaper than full content)
    - Sync-time marking: When `props sync` updates GT, immediately mark affected grader runs as stale (no comparison at query time)
    - Incremental regrading: Instead of full regrade, append system message to existing run:
      "Ground truth updated for: TP-123, FP-456. Update affected grading decisions and resubmit."
      Preserves existing work, just patches the delta. Requires tracking which TPs/FPs each decision references.

- [ ] **Definitions browser page**
  - Separate page/table for managing definitions
  - Filter by agent type
  - View definition details (tarball contents, Dockerfile)
  - Click through to runs for a definition

---

## Component Status

| Component | Status | Notes |
|-----------|--------|-------|
| `App.svelte` | Works | Main layout, tabs |
| `RunList.svelte` | Partial | Shows active runs but may be empty when jobs running |
| `RunDetail.svelte` | Works | Events timeline, polling |
| `ValidationRunTrigger.svelte` | Partial | Missing split selector, no progress feedback |
| `DefinitionsTable.svelte` | Partial | Missing definitions with no runs |
| Runs browser | Missing | No way to see all historical runs |
| WS integration | Missing | Endpoint exists, UI doesn't use it |

## API Endpoints Status

| Endpoint | Status | Notes |
|----------|--------|-------|
| `GET /api/stats/overview` | Partial | Missing definitions with no stats |
| `GET /api/stats/definitions` | Works | Lists all definitions |
| `GET /api/runs/active` | Partial | Returns empty during job execution? |
| `GET /api/runs/jobs` | Works | In-memory job tracking |
| `POST /api/runs/validation` | Partial | Missing split parameter |
| `GET /api/runs/{id}` | Works | Run detail |
| `GET /api/runs/{id}/events` | Works | Paginated events |
| `WS /api/runs/{id}/stream` | Works | Exists but unused by frontend |
| `GET /api/runs` (browse all) | Missing | Need to add |

## Key Files

**Backend:**
- `src/props_backend/app.py` - FastAPI setup, lifespan
- `src/props_backend/routes/runs.py` - Runs API + WebSocket
- `src/props_backend/routes/stats.py` - Stats API

**Frontend:**
- `../props_frontend/src/App.svelte` - Main layout
- `../props_frontend/src/components/RunList.svelte` - Active runs
- `../props_frontend/src/components/RunDetail.svelte` - Run details + events
- `../props_frontend/src/components/ValidationRunTrigger.svelte` - Trigger controls
- `../props_frontend/src/components/stats/DefinitionsTable.svelte` - Leaderboard
- `../props_frontend/src/lib/api/client.ts` - Typed API client
