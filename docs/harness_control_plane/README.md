# Harness Control Plane

Status: **proposal**. “Harness Control Plane” is a descriptive working name, not a final product
name and not a Haku component.

This document set proposes a Kubernetes-hosted control plane for coding agents. The required first
adapters run native Claude Code and Codex harnesses in Pod or sandbox-backed workloads. One
multi-mode `harness-bridge` binary supervises the selected harness and speaks its structured machine
protocol. A central PostgreSQL-backed server owns durable threads, workload lifecycle, recovery
decisions, the common timeline, and the web UI.

Native harnesses are the default because they preserve provider behavior and, for Claude, support
the required subscription-compatible path. A direct LLM API agent loop is documented as an optional
later adapter, not the baseline.

The design deliberately rejects terminal keystrokes and pane scraping as its correctness boundary.
It also evaluates A2A 1.0 as a future public harness-neutral interface while keeping the private
bridge/recovery stream separate.

## Documents

- [Architecture and sandbox lifecycle](architecture.md)
- [Claude Code and Codex protocol adapters](provider_protocols.md)
- [Common harness protocol and timeline vocabulary](common_protocol.md)
- [A2A fit and protocol layering](a2a.md)
- [Rerunnable protocol and recovery experiments](experiments.md)

## Fixed first-version choices

- Native Claude Code and Codex adapters are both required.
- One bridge executable has per-provider modes.
- PostgreSQL is the central durable store.
- The common protocol covers orchestration, messages, turns, steering, interrupts, operation
  progress, native provenance, and recovery evidence.
- Native frames remain available for diagnosis and reprojection.
- A direct LLM loop is optional and must emit the same common protocol.

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
