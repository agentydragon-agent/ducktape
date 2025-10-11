# loop control server (agent-only loop tools)

A tiny FastMCP server that provides neutral loop control tools independent of any specific UI. Its purpose is to let the agent yield or coordinate turns without coupling to the UI server.

## Tools (server `loop`; model sees `mcp__loop__*`)



- `yield_turn({}) -> {ok}` → exposed as `mcp__loop__yield_turn`
  - Signal the agent loop to yield control. Safe to allow unconditionally in policy.

Server name: `loop` → tools exposed to the model as `mcp__loop__yield_turn`. See also <overview.md> and <../vision.md>.

## Wiring

- Mount via the Compositor as a proxy so tools appear under `mcp__loop__*`:
  - In‑proc loop app: `Compositor.mount_inproc("loop", control_app)`
  - Remote loop service: `Compositor.mount_server("loop", spec)` (typed HTTP/stdio)
- Do not attach directly to the manager; keep a single aggregation surface via the Compositor.
- Where to wire: build the control FastMCP app next to the UI app and hand it to the Compositor during startup.

## Policy

- Agent‑only: expose Loop Control only on the agent automation connection. Do not surface it to the Human UI. If a shared Compositor is used, gate visibility by bearer scope and/or filter tools list on the human token.
- Allowlist: mark `loop.yield_turn` as always allowed for the agent token.

## Notes

- Deprecates `ui.end_turn` on the UI server. Keep UI’s `end_turn` for transition, but prefer `loop.yield_turn` in prompts and handler injections.
- Pairs well with handler‑injected chat reads: the orchestrator can synthetically insert a `loop.yield_turn` after injecting chat read tool results to immediately hand control back to the model.
- Yield semantics are owned by the orchestrator/handlers: `yield_turn` transitions into a sleep_until_user state defined by Loop Control. The policy middleware does not define wake semantics; approvals do not wake. See the overview for details.
