# Agentplane service boundaries

The integration app is a user-facing composition layer, not a backend dependency.
See [the dependency rule](docs/service_boundaries.md) and [Sandbox Service plan](plans/sandbox_service.md).

- Do not add backend-service imports of `agentplane.app`, calls to its APIs, reads of its private
  tables, or requirements for its process, browser session, or app-issued identity to be available.
  Backend functionality needed by another service must be extracted into its owning service or a
  neutral shared package, not exposed through a temporary app-owned backend API.
- The app calls independent services; those services do not call back into the app to operate.
  This includes v1, startup, background recovery, provisioning, and backend-required prompt/context
  construction. Operator approval still belongs to its backend authority; the app presents it.
- Notification v1 depends on the minimum Sandbox Service extraction, not the integration app.
  The Sandbox Service owns sandbox lifecycle and access to runner sessions; notifications owns
  subscriptions/inboxes, and runners own native execution and canonical command/Event evidence.
- Current backend responsibilities inside the app are extraction work, not a precedent for new
  dependencies. Distinguish planned boundaries from what is already implemented.
- Acceptance for an extracted backend path must exercise it with the integration app unavailable.
  Do not add another command queue, event authority, or credential issuer as an incidental refactor.
