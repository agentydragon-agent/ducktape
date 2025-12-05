local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Inconsistent session management: sync_detector_prompts() and sync_model_metadata()
    don't take a session parameter, while sync_snapshots_to_db() and sync_issues_to_db() do.
    This forces sync_all() to open a session for only 2 of 4 operations, then call the
    other 2 outside the session context.

    All four sync functions should take a session parameter for consistency, allowing
    sync_all() to be written as a single with-block that inlines the FullSyncResult
    construction with all four calls inside the session context.
  |||,
  filesToRanges={'adgn/src/adgn/props/cli_app/cmd_db.py': [[47, 63]]},
)
