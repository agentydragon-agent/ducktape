@README.md

# Agent Guide for `agent_server/`

## Runtime Containerization

- Evaluation runs in Docker using one-off containers
- Host-side timeouts are enforced; if a command times out the session container is restarted before the next call

## Approval Policy

Policies are standalone Python programs executed in Docker:

- **Input**: `{name: "<server>_<tool>", arguments: {...}}`
- **Output**: `{decision: "allow|deny_continue|deny_abort|ask", rationale?: str}`

The active policy lives behind MCP resource `resource://approval-policy/policy.py`. Proposals are
managed via the approval policy server.

### Policy Evaluation

- The policy middleware calls a private tool `decide({name, arguments}) -> {decision, rationale}`
  hosted on the `policy_reader` server
- Policy source is evaluated in a sandboxed container via `policy_eval.runner` (network disabled,
  read-only rootfs, memory/CPU limited)
- See `docker/AGENTS.md` for image build and environment variables

### Testing Policy Decisions (Advisory)

- Optional: expose `policy_reader.decide` to agent/human tokens for testing
- Advisory only: does not create approval items or alter enforcement
- Suggested UI affordance: "Test decision" action next to tool payload inspectors

## Development

Part of the ducktape Bazel workspace. See root `AGENTS.md` for build instructions.
