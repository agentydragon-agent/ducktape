# Gatelet TODO

This file lists outstanding tasks required to finish the Home Assistant API integration project described in `ha-api-task.txt`.

## Remaining work

Key-in-path and challenge-response authentication are implemented and tested.
Webhook storage and browsing work, and the admin login with key management pages
is available. The tasks below track what is still needed to fully implement the
plan in `ha-api-task.txt`.

- Finish the human admin interface:
  - ~~List and invalidate active admin sessions~~ (done)
  - ~~List and invalidate active LLM sessions~~ (done)
  - Expose log inspection pages
- Expand the Home Assistant integration with history and trend views for
  configured entities
- Provide reporter scripts to send device events to Gatelet
- Resolve remaining TODO comments in the code (e.g. redirect after login)
