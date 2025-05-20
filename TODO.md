# Gatelet TODO

This file lists outstanding tasks required to finish the Home Assistant API integration project described in `ha-api-task.txt`.

## Remaining work

Key-in-path and challenge-response authentication are implemented and tested.
The server accepts webhooks and lists them through the LLM-friendly UI. The
remaining items below track what is still needed to fully implement the plan in
`ha-api-task.txt`.

- Finalize the human admin interface:
  - List and invalidate active sessions
  - Manage login keys (create and revoke)
  - Expose log inspection pages
- Connect to the Home Assistant API and display entity state and history.
- Provide reporter scripts to send device events to Gatelet.
- Add configuration options for test database connections.
- Resolve existing TODO comments in the code (e.g. login redirect,
  integration filtering).
