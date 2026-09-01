# Harness Control Plane

Status: **proposal**. “Harness Control Plane” is a descriptive working name, not a final product
name and not a Haku component.

This document set proposes a Kubernetes-hosted control plane for coding agents. The required first
adapters run native Claude Code and Codex harnesses in Pod or sandbox-backed workloads. One
multi-mode `harness-bridge` binary supervises the selected harness and speaks its structured machine
protocol. A central PostgreSQL-backed server owns durable Threads, workload lifecycle, recovery
decisions, and the common timeline; the web UI consumes that API and may deploy separately.

The motivating product is a fleet of reliable headless Agents that can use both Claude and ChatGPT
subscription-backed routes, run for days or longer, receive streaming updates, and eventually
delegate to and communicate with other Agents. Native harnesses are the default because they
preserve provider behavior, work through the existing LiteLLM -> CLIProxyAPI Messages/Responses
paths, and avoid making metered direct APIs the mandatory baseline. CLIProxyAPI, not this control
plane or its workloads, owns consumer login and token refresh. The Claude Agent SDK is a wrapper
around the Claude binary rather than a separate agent loop; this design drives the stream/control
wire directly. A direct LLM API agent loop is documented as an optional later adapter, not the
baseline.

The design deliberately rejects terminal keystrokes and pane scraping as its correctness boundary.
It evaluates A2A 1.0 only as a future opaque agent-to-agent facade; the rich harness-neutral common
timeline and private bridge/recovery stream remain internal.

## Documents

- [Main design: problem, constraints, decisions, alternatives, and sandbox lifecycle](architecture.md)
- [Claude Code and Codex protocol adapters](provider_protocols.md)
- [Common harness protocol and timeline vocabulary](common_protocol.md)
- [Implementation reuse and pinned prior art](implementation_reuse.md)
- [A2A fit and protocol layering](a2a.md)
- [Rerunnable protocol and recovery experiments](experiments.md)

## Fixed first-version choices

- Native Claude Code and Codex adapters are both required.
- One bridge executable has per-provider modes.
- PostgreSQL is the central durable store.
- Runtime is one Pod/bridge incarnation; a monotonically increasing runtime generation is the
  Sandbox-scoped ordinal and fencing epoch for the n-th authorized incarnation.
- The common protocol covers orchestration, messages, turns, steering, interrupts, operation
  progress, native provenance, and recovery evidence.
- Native frames remain available for diagnosis and reprojection.
- Suspension starts as an explicit idle-only operator action; Sandbox disposal is explicit and
  confirmed rather than retention-window driven.
- The bridge uses a simple append-only PVC log for reconnect replay rather than a separately bounded
  overflow policy.
- A direct LLM loop is optional and must emit the same common protocol.

The orchestrator, web UI, model-capability/router layer, and future stateless MCP authorization
gateway should be separately deployable. This proposal owns only orchestration/runtime/logging; it
does not bind tool RBAC or approval escalation to Thread, provider-continuity, or Sandbox concepts.

A future integrated Agent Console can compose those smaller services into one application for
Threads, Runtimes, Sandboxes, MCP connections, approvals, grants, and traces without making
them one deployment or authority.

**Thread** is the shared UI, API, and storage noun. In v0 one Runtime serves one Thread, and the
same product Thread maps across Runtime generations to one durable Codex native thread or one Claude
resume identity. A later Codex app-server may host several Agents, but each Agent still owns a
separate Thread; only its Sandbox/Runtime placement is shared.

## Evidence standard

These documents separate three levels of confidence:

- **Native contract**: stated by a provider's version-pinned protocol documentation or schema.
- **Repository evidence**: implemented or measured in the current Ducktape tree, but not necessarily
  a provider compatibility promise.
- **Experiment required**: plausible behavior that must not become a recovery guarantee until the
  pinned-harness experiment suite passes.

Provider protocol surfaces change. Every production image records exact Claude Code, Codex, bridge,
and sandbox-controller versions, and provider upgrades rerun the compatibility suite before
rollout.
