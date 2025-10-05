# MiniCodex UI/Protocol Migration — Pending Items

- Frontend approval UX
  - Add a clear transcript/system note after a decision:
    - approve → note that tool call was approved
    - deny_continue → show injected function_call_output preview from decision mapping
    - deny_abort → note that the turn was aborted
- E2E coverage for approval decisions
  - Pending → approve/deny_continue/deny_abort → assert transcript and agent behavior
- CI: UI build step
  - Add vite build to CI and assert server/static/web artifacts exist
