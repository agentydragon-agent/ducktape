# Agentplane

Status: **focused proposal**. “Agentplane” is the deliberately boring working name for the native
harness bridge/controller; it is not a Haku implementation refactor.

Agentplane runs native Claude Code and Codex harnesses in replaceable Kubernetes workloads and
speaks their structured machine protocols. The first useful slice is a provider-specific capture and
replay experiment: drive real harnesses, capture native and upstream LLM exchanges, and prove the
driving loop with tests.

## Documents

- [Focused architecture](architecture.md)
- [Claude and Codex protocol notes](provider_protocols.md)
- [Deferred common protocol notes](common_protocol.md)
- [Implementation reuse and prior art](implementation_reuse.md)
- [A2A suitability evaluation](a2a.md)
- [Focused experiments](experiments.md)
- [P0 implementation task DAG](task_dag.md)
- [First orchestrator task DAG](orchestrator_dag.md)
- [Product-surface inventory](product_surface.md)
- [Sandbox egress identity option survey](sandbox_egress_identity_research.md)
- [Capture native Claude/Codex wires](subtasks/capture_native_harness_wires.md)

## v0 scope

Required:

- native Claude Code and Codex drivers;
- real stdin/stdout protocol traffic, never PTY/tmux integration;
- messages, tool calls/results, streaming output, interrupts, and steering where supported;
- provider-native resume after an idle process restart where supported;
- upstream LLM request bodies and streamed response capture;
- deterministic fake-model replay through real harnesses; and
- small, hand-authored behavior assertions with synthetic workspaces.

Not required for the capture slice:

- PostgreSQL or a common Thread/Turn/Input schema;
- neutral operation projection or UI timeline;
- Kubernetes reconciliation or Service management;
- runtime-generation/fencing identities;
- artifact promotion, checksum manifests, custom DLP scanning, or package-integrity metadata;
- credentials, OAuth, approvals, MCP routing, subscriptions, or external-event adapters.

## Design boundaries

- Kubernetes/Agent Sandbox owns Claim, Sandbox, Pod, PVC, readiness, suspension, and workload
  lifecycle.
- Native harnesses own native history, execution semantics, and native resume.
- The bridge owns native process supervision and protocol I/O.
- A future central service may own product interaction state and a user-facing timeline while
  consuming those observations.

Use natural Pod UID and process start/exit evidence first. Do not require `restartPolicy: Never`,
mutual TLS, or a separately injected runtime-generation identity for v0. A separately managed
Kubernetes Service may be useful for a central-initiated channel, but the Sandbox CR is not assumed
to create one automatically.

## Evidence standard

The first fixtures preserve complete ordered native frames and the upstream model bodies/chunks.
They omit HTTP headers, cookies, environment variables, credentials, and private user data. Use
ordinary repository secret checks and a small obvious-token guard rather than building a promotion or
DLP subsystem.

The native transcript and model transcript are the evidence. Do not add redundant body lengths,
SHA fields, timestamps, parsed copies, checksum files, or manifest inventories. File order supplies
ordering; provider-native ids remain in the provider transcript.

The common protocol and central persistence model are intentionally deferred until the captures show
what Claude and Codex actually have in common.
