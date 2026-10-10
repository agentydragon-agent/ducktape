# App archive cutover and schema retirement

## Current status (2026-10-10 PDT)

Archive backfill, writer handoff, service-backed raw reads and UI projection cutover
are complete in testing and staging. The app consumes service history unconditionally;
there is no supported app raw-reader/writer fallback or opt-in rollout flag. Raw read
authorization and explicit lag/error behavior remain required. Public UUIDs are not
read authorization. Runner journals remain execution evidence, not app-owned archives.

The six empty staging Sessions were excluded from further verification by the operator.
Do not repeat backfill or a full historical scan. Historical staged switch instructions
are removed here; git history retains the deployment procedure and earlier design.
Accepted bounded evidence follows. New schema work is not blocked on an already
completed archive-ownership capstone, but retains its own contract/security reviews.

## Runtime cleanup acceptance

Migration agent evidence, 2026-10-09 (PDT): staging's 55 retained Sessions have
handoff receipts and checkpoint coverage. The flags and import Jobs are retired.
Testing subsequently completed the same handoff: 142 matching app/service histories,
142 fences, 142 preserved summaries and zero nonempty projections behind their final
raw cursor. Indexed watermarks showed service coverage of every retained prefix;
recent app logs showed no projection-stalled or reconciliation errors.

The operator accepted new-session/live-use behavior after creating the staging
`haku` Session (`31d54d02-d197-4fc7-b9be-37b4a177ec2d`). Read-only checks found service
and app projection cursors both at 42,086, app raw cursor zero, a zero-origin fence,
and active projection state with no feed error. This is staging live-use evidence,
not a claim of a new testing Sandbox acceptance run. Together with testing's retained
handoff and the operator's acceptance, it releases the runner-copy deletion hold.

Mandatory service-backed archive readers (#9659), runner-copy loop removal (#9660),
and the subsequent runtime/test port are complete. The service projection coordinator
remains lease-fenced and discovers new Sessions. No full-history scan was repeated.
Raw-table schema retirement remains explicit work below, not an implicit part of
those code removals.

### Runtime retirement rollout evidence

The merged #9660 image (`52b4e8e`) was checked Ready in testing (1/1) and staging
(2/2). Testing still had 142 matching fenced histories and service coverage. The live
staging `haku` Session advanced to cursor 54,132 in both service and app projection,
with app raw cursor zero, active state and no feed error. App logs from all three
replicas showed no projection-stalled, reconciliation-failed or error lines in the
checked ten-minute window.

Subsequent cleanup retired the remaining raw writer helpers and handoff tool, and
made checkpoint and ThreadHistorySummary reads unconditional. Their obsolete ORM
models and compatibility fence remained until the explicit schema retirement below.

## Post-cutover schema cleanup

Completed: runtime raw writers/read fallbacks and handoff tooling were retired;
per-Session leases replaced Sandbox ownership; #9707/#9712 removed app locator
lookups and the physical locator column. Authoritative bindings remain in Sandbox
Service. #9723 removes the temporary locator-retirement rollout override/test.

**In flight: explicit raw-table retirement.** Migration `0024_retire_app_raw_history`
deletes retained app `event` and `feed_state` rows, their indexes/triggers, the obsolete
`reject_fenced_app_ingestion()` function, and `raw_ingestion_fenced_at_cursor`.
It removes the ORM models/compatibility writes; old-schema setup exists only in
historical migration tests. Public identities, current projection tables/checkpoints,
operator metadata, Sandbox Service history and runner storage are untouched.

This destructive retirement is not reversible by Alembic downgrade. Restore a
pre-retirement backup for rollback rather than fabricating an empty archive. Do not
merge until CI passes and the app-only Recreate strategy is verified live: older
replicas still map the fence column. If #9723 has restored RollingUpdate, deploy a
separate strategy prerequisite first. Do not bundle that prerequisite with the schema
image. After a coordinated stop and migration, verify revision/table absence, readiness
and bounded projection progress, then remove temporary strategy/test again. No scan
or backfill is part of acceptance.

Still unfinished:

- Rename `EventLog`/`event_log` to an app-side Session reference with its foreign keys.
- Audit `sandbox`, `harness`, `model`, `cwd`, and duplicate summary/model/activity
  fields against real consumers. Keep useful UI projections, not competing authorities.
- Inventory remaining migration-only tools and grants before deleting them.
- Reconcile the new-Session identity checklist against deployed CreateSession and tests.
- Squash Alembic only once the final schema settles; historical migrations remain valid
  upgrade paths until then.

### Session-lease cutover evidence

The per-Session ownership cutover (#9692) completed on 2026-10-10. The temporary
app-only Recreate prerequisite (#9698) stopped old owners before migration; Sandbox
Service, runners and their storage were unchanged.

Bounded live checks at 04:53–04:55 America/Los_Angeles verified:

- Testing was 1/1 Ready and staging 2/2 Ready on the f5273a6 app image; all three
  migration init containers exited zero.
- Both app databases reported `0022_session_projection_lease`, with
  `session_projection_lease` present and `sandbox_ingestion` absent.
- Testing had 142 active leases; staging had 58. Multiple Sessions in one Sandbox
  held independent leases.
- Two active staging projection checkpoints advanced between samples, by 135 and
  3,584 cursor positions. Bounded log samples from both staging replicas and testing
  had no matching error, exception or stalled lines. No archive scan was performed.

The deployment-only follow-up restores `self.env.replicas.strategy` and removes the
migration-specific Recreate regression test: staging returns to RollingUpdate;
testing retains its normal Recreate strategy. This is not a schema rollback.
A binary rollback across the ownership-scope change still requires stopping the app
and downgrading the lease schema first.

### Locator-column retirement evidence

#9712 deployed on 2026-10-10 after the app-only Recreate prerequisite #9715.
Bounded live checks at 07:06–07:07 America/Los_Angeles verified:

- Testing 1/1 and staging 2/2 updated/Ready on app image
  `devel-20261010140400-9333ed3`; all migration init containers exited zero.
- Both primary app databases reported `0023_drop_app_runner_locator`.
- `event_log.session_id` and its local unique constraint were absent.
- Two active staging checkpoints advanced between samples, by 384 and 13 cursor
  positions. Bounded startup logs from all three app Pods had no matching error,
  exception or traceback lines. No full-history scan or backfill was performed.

The deployment-only follow-up restores environment-specific strategy and removes
#9715's temporary regression test: staging returns to RollingUpdate and testing
retains Recreate. Public identities, checkpoints, service-owned locator bindings
and retained history were not removed. Raw app archive-table retirement is separate.

Downgrade still requires coordinated app shutdown. Migration downgrade recreates
compatibility values from public UUIDs, not discarded private locator copies, and
supports #9707-or-later public-ID readers only. Restoring deployment strategy is
not a schema rollback.
