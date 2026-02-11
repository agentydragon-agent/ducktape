# MiniCodex UI/Protocol Migration — Pending Items

- Frontend approval UX
  - Add a clear transcript/system note after a decision:
    - approve → note that tool call was approved
- deny_continue → surface policy_denied_continue error in transcript/UI; tool is not executed
- deny_abort → surface policy_denied error and abort the turn
- E2E coverage for approval decisions
- Pending → approve/deny_continue/deny_abort → assert transcript and agent behavior (no handler injection)
- CI: UI build step
  - Add vite build to CI and assert server/static/web artifacts exist
