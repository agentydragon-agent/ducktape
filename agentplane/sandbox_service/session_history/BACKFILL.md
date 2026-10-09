# One-off Session Event import (not Thread unarchive)

The `backfill_image` copies app `event_log` / `event` records into Sandbox Service's
`session_history` / `session_event`. It preserves app Event-log UUIDs, the complete
proto-JSON EventEntry semantics (including native packets), checks contiguous
source cursors and rejects conflicting destination bytes. No fold tables or app
rows are changed. Already-reserved sessions keep the Service's private `r-UUID`
runner locator; legacy rows without a reliably recorded Sandbox UID get `NULL`
and are **not** eligible for shadow runner polling. Do not fabricate a UID based
only on a currently matching Sandbox name.

This is not a continuously running reconciler. The example Kubernetes Job at
`agentplane/plans/session_history_backfill_job.yaml` is
**deliberately excluded** from Flux's kustomization: it must not launch when
merely merging/deploying an image. Before using it, pin a built image, verify
Sandbox Service history schema migration and ingress defaults, and review DB
Secret names and network grants for that cluster. Give the Job a bounded retry budget
for infrastructure failures, but fail immediately on importer data conflicts (exit
code 2 via `podFailurePolicy`). This is an import Job, not a Sandbox bootstrap retry.

Run the Job while app ingestion remains active. It takes a bounded high-water
cursor **per session**, committing every 128 Events. A restarted Job begins with
the destination's `last_cursor`, validates the first and checkpoint Event against
the app, and skips the previously imported prefix. It never replays a whole
multi-million-Event Session merely to reach its last committed batch. The
skipped interior is NOT verified by this fast path: independently compare all
canonical app and Service Event bytes before cutover. Logs report per-Session
checkpoint, ceiling and periodic Event rates; monitor Job failures and stalled
progress rather than assuming a Running pod is making progress. Re-run to close live-writing gaps and compare every session's latest
app and Service cursors/bytes, including deleted sandboxes and the handoff
window. Do **not** enable the shadow ingester or switch app reads on the
strength of the first import. Current legacy sessions with a NULL Sandbox UID
need a separate verified-incarnation strategy before their app ingestion is
retired. Proto-JSON does not retain unknown wire fields; compare the
canonical serialized messages the app actually stored, not original runner
wire bytes, for imported historical events.
