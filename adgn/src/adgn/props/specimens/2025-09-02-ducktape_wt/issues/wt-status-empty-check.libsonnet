local I = import '../../specimens/lib.libsonnet';

I.issueOneOccurrence(
  rationale= |||
    Empty-check on a Pydantic BaseModel is ineffective; the code never enters the “no status” branch.

    Observed:
    - In worktree_service._show_all_worktrees_status, the code does:
        all_status = await daemon_client.get_status([])
        if not all_status:
            click.echo("🤷 No worktrees found")
            return
      But get_status returns a Pydantic BaseModel (StatusResponse). Pydantic models are always truthy,
      so `if not all_status` is never true — even when there are zero results.

    Correct intent:
    - Test the actual contents, e.g. `if not all_status.results:` (or `len(all_status.results) == 0`).
    - Optionally also guard against None (defensive) if the API can return None, but the current StatusResponse
      contract makes that unnecessary.

    Why this matters:
    - The UI path meant to inform the user that “no worktrees were found” will never run, causing confusing empty
      screens or later errors when the code assumes non-empty results.

    Acceptance criteria:
    - Replace `if not all_status:` with an explicit check of the results mapping, e.g. `if not all_status.results:`.
    - Keep the user message, but only emit it when the results mapping is empty.
    - Prefer named-field checks over truthiness on typed objects throughout the status codepath to avoid similar bugs.
  |||,
  filesToRanges={
    'wt/wt/server/worktree_service.py': [[497, 512]],
    'wt/wt/shared/protocol.py': [[268, 292]],
  },
)
