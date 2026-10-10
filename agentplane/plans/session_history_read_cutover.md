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
Service. #9723 removed the temporary rollout override/test.

**Complete: explicit raw-table retirement (#9725).** Both primary app databases
reached `0024_retire_app_raw_history`; retained app `event`/`feed_state`, their local
indexes/triggers, the rejection function and fence column are retired. Their ORM
models and compatibility writes are removed. Old-schema setup exists only in historical
migration tests. Public identities, current projections/checkpoints, operator metadata,
Sandbox Service history and runner storage remain outside this deletion's scope.
See the [bounded rollout evidence and incident](#raw-history-retirement-evidence).

The retirement is not reversible by Alembic downgrade. Restoring a pre-retirement
backup is required for rollback; an empty replacement archive is not equivalent.
No temporary rollout gate, further backfill or full-history verification remains for
this migration. Future schema changes still require their own compatibility plan.

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

The deployment-only follow-up #9705 restored `self.env.replicas.strategy` and removed
the migration-specific Recreate regression test: staging returned to RollingUpdate;
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

The deployment-only follow-up #9723 restored environment-specific strategy and removed
#9715's temporary regression test: staging uses RollingUpdate and testing Recreate.
It landed before raw-table retirement, causing the overlap described below. Public identities, checkpoints, service-owned locator bindings
and retained history were not removed. Raw app archive-table retirement is separate.

Downgrade still requires coordinated app shutdown. Migration downgrade recreates
compatibility values from public UUIDs, not discarded private locator copies, and
supports #9707-or-later public-ID readers only. Restoring deployment strategy is
not a schema rollback.

### Raw-history retirement evidence

On 2026-10-10 at 07:49 America/Los_Angeles, bounded postflight checks confirmed:

- Testing 1/1 and staging 2/2 updated/Ready on image
  `devel-20261010144538-f7d256c`, with no old app replicas remaining.
- Both primary app databases reported `0024_retire_app_raw_history`.
- `event`, `feed_state`, `reject_fenced_app_ingestion()`, the old fence column and
  the previously retired locator column were absent.
- Two active staging checkpoints advanced between samples, by 384 and 10 cursor
  positions. Bounded replacement-Pod startup log samples had no matching errors.
- No backfill or full-history scan was repeated. The normal environment strategies
  were already restored by #9723; no further strategy patch is needed.

#### Staging rollout overlap incident

#9723 merged before #9725's image deployed. GitOps restored staging's RollingUpdate
strategy while the old app image still mapped `raw_ingestion_fenced_at_cursor`.
The new Pod's migration dropped that column while an old replica was still running.
The old replica's bounded logs contained `UndefinedColumnError` naming that column.
Testing retained Recreate and did not have the same strategy overlap.

The old staging replica subsequently exited. The final replica inventory, current
replacement logs and advancing checkpoints establish recovery, not proof that no
requests failed during the overlap. Request impact was not quantified. This was
not a successfully coordinated stop, and must not be recorded as one.

The emergency suggestion to patch staging back to Recreate was superseded when the
migration and rollout completed; it is not a remaining operator action. For future
breaking migrations, preserve the prerequisite strategy until schema rollout is
verified, and gate its restoration on that evidence rather than merge or image-build
completion. This record does not claim such automated gating has been implemented.
