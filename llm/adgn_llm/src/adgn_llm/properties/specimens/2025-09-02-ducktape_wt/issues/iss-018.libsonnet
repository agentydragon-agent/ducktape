local I = import '../../specimen_issues.libsonnet';

// iss-018: No dead code — WorktreeService helpers (service path not used in prod)
I.issueOccurrencesFromLines(
  rationale=|||
    WorktreeService.{create_worktree, execute_post_creation_script} are dead. Only call sites are in test code.

    Likely cause: responsibilities were moved from client to server (triggered by JSON‑RPC), but Service methods were left behind.

    Evidence to demonstrate:
    1) Only call sites are in tests: rg -n "WorktreeService\.create_worktree\(|execute_post_creation_script\(" wt/ -g '!wt/tests/**'
    2) Trace the prod path in wt_server for worktree_create (JSON‑RPC) — CLI "wt -c" → client handlers.handle_create_worktree →
    daemon_client.create_worktree (JSON‑RPC) → server handle_client_request(...) → _handle_worktree_create_request(..., writer)
    3) Tracer: add temporary log/exception in WorktreeService.create_worktree; exercising worktree creation from CLI should not fire it.

    Recommendation:
    - Delete WorktreeService.create_worktree and execute_post_creation_script; keep only JSON‑RPC server path.
    - Start post-creation script only from within server (_run_post_creation_script_streaming), never from client
    and make tests target the prod path.
  |||,
  properties=['no-dead-code'],
  linesByFile={
    'wt/wt/server/worktree_service.py': [
      [98, 164, 'WorktreeService.create_worktree'],
      [299, 380, 'WorktreeService.execute_post_creation_script'],
    ],
  },
)
