# Agentplane P0 task DAG

This is a sequencing aid for the first native-harness slice, not a workflow engine or a second
architecture. A node is complete only when its evidence exists.

## Outcome

For Claude and Codex, a real harness can be launched, driven through its native protocol, observed
through its upstream model exchange, and run again from a deterministic replay with assertions for
native output, tool I/O, and workspace effects.

## Current status

- **S0 is complete:** the sandbox proxy and workload-identity spike has committed manifests and live
  evidence. It informs later credentialed egress work but does not gate the native capture path.
- **Native capture is complete on PR #15:** one agent delivered the Claude and Codex captures, replay
  tests, steering/interrupt evidence, idle resume evidence, and upstream disconnect/reconnect evidence.
  The capture branch still needs to be integrated into the branch behind PR #5342.
- **Next:** integrate the capture branch, then implement the thin shared stdio protocol and both
  provider adapters.

## DAG

```mermaid
flowchart TB
    classDef completed fill:#dcfce7,stroke:#15803d,color:#14532d,stroke-width:2px
    classDef captureComplete fill:#fef3c7,stroke:#b45309,color:#78350f,stroke-width:2px
    classDef next fill:#dbeafe,stroke:#1d4ed8,color:#1e3a8a,stroke-width:2px
    classDef milestone fill:#ede9fe,stroke:#6d28d9,color:#4c1d95,stroke-width:2px
    classDef deferred fill:#f3f4f6,stroke:#6b7280,color:#374151

    S0["Sandbox proxy/identity<br/>completed evidence"]:::completed
    A["Native capture + replay<br/>Claude and Codex"]:::captureComplete
    I["Integrate capture branch<br/>into PR #5342"]:::next
    B["Shared stdio protocol<br/>+ both provider adapters"]:::next
    C["Standalone Agentplane service seam<br/>records, runner bridge, REST/SSE"]:::next
    D["First functioning credentialless Agentplane<br/>live updates, persisted history, honest outcomes"]:::milestone
    E["Separate conversation app/UI<br/>Thread naming, archive, timeline, live control"]:::next
    F["Secure egress integration<br/>fixed sidecar + trusted external gateway"]:::deferred
    G["Credentialed production readiness<br/>freshness, replay, rotation, failure semantics"]:::deferred
    H["Reliability hardening<br/>only from observed failures"]:::deferred
    J["Explicit Haku Console integration"]:::deferred

    A --> I --> B --> C --> D
    D --> E
    D --> F --> G
    D --> H
    D --> J
    S0 -. informs .-> F

```

Legend: green is completed evidence already accepted as a separate spike; amber is completed native
capture work that is still awaiting integration into PR #5342; blue is the next focused work; purple is
the first functioning-product milestone; gray is downstream or deferred work.
See [S0 sandbox proxy and identity evidence](../sandbox-spike/README.md).

This overview intentionally uses one box for the native capture package and one box for the shared
protocol/adapters. The detailed provider/scenario matrix and acceptance evidence remain in
[`experiments.md`](experiments.md) and the [capture task packet](subtasks/capture_native_harness_wires.md).

## Gates

- Do not start F until at least one real baseline/tool path works for each provider.
- Do not add a shared provider abstraction before D and E expose an actual common behavior.
- Do not add persistence, common timeline, Kubernetes lifecycle, or recovery machinery to unblock a
  node in this DAG.
- If a node fails because the provider lacks a capability, record the provider-specific result and
  continue; do not expand the framework to make the matrix look complete.
- If the implementation has more artifact bookkeeping than native-driving logic, stop and cut it.

## Evidence by node

- **S0:** live sandbox/proxy evidence, including the proven credential boundary and the unsupported
  same-Pod route-confinement result.
- **Native capture + replay:** real Claude and Codex launch, baseline/tool driving, steering/interrupt,
  idle resume, upstream reconnect behavior, exact transcripts, and replay tests.
- **Integrate capture branch:** PR #15's captured implementation is present on the branch behind PR
  #5342, with its original provider-specific evidence intact.
- **Shared protocol + adapters:** one stdio contract whose commands/events are justified by captured
  native frames, exercised through both real providers.
- **Standalone service seam:** the smallest API/service path that starts a runner, accepts an Input,
  streams events, persists enough history for refresh, and reports an honest terminal outcome.
- **First functioning Agentplane:** end-to-end credentialless operation through the standalone service
  and separate conversation app.
- **Deferred branches:** secure egress, credentialed readiness, reliability hardening, and explicit
  Haku Console integration each require their own observed evidence and acceptance test.

## Deferred branch

Only after I, and only if a concrete product need remains, investigate:

- multiple pending inputs and dequeue;
- active-turn process death and side-effect reconciliation;
- central/bridge reconnect;
- Pod replacement and Sandbox suspension;
- PostgreSQL Thread/Input/Turn persistence;
- a neutral bridge protocol and UI projection; and
- authentication, fencing, approvals, credential delivery, subscriptions, and external-event
  adapters.
