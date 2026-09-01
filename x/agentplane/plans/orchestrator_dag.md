# First functioning orchestrator: task DAG

This is the next-stage product DAG after the native capture task. It is a dependency map, not a
request to build every future Agentplane subsystem.

## Boundary ruling

Agentplane and Haku Console are separate products and implementation boundaries.

For this slice, Agentplane gets its own service, API, persistence, runner bridge, deployment shape,
and web UI. New Agentplane code must not import `haku/console`, reuse Haku Console conversation
routes/tables/frontend modules, or make Haku Console a runtime dependency.

Haku Console may later integrate with Agentplane through an explicit external adapter or enveloped
message path. That is a later integration slice, not a prerequisite for the first orchestrator.
Shared generic libraries are deferred unless a concrete dependency is proven; copying a useful
pattern is acceptable, coupling the products is not.

## Recommended product slice

The first user-visible outcome is:

> Rai can open the standalone Agentplane UI, create a Thread, start one Claude or Codex runner,
> send an Input, watch native/model-backed response and tool activity arrive, and see an honest
> terminal outcome.

The first slice should work for one provider first, then add the second provider through the same
behavioral contract. It should not wait for multi-Agent collaboration, subscriptions, approvals,
retention policy, or a generalized control plane.

## DAG

```text
A. Native capture task (in progress)
   real provider frames + upstream model exchanges + driver/replay evidence
                         |
                         v
B. Shared protocol + both stdio adapters
   one owner derives the thin shared contract from captures,
   wires Claude and Codex to it, and links shared items to native frames
          |                         |                         |
          v                         v                         v
C. Minimal Agentplane records       D. Runner/bridge seam       E. Agentplane runtime seam
   Thread, Input, Turn,             protocol-facing driver      separate service/process,
   native event, outcome             lifecycle over stdio        own config and API boundary
          \                         |                         /
           \_______________________|________________________/
                                   v
F. One-provider vertical slice
   create Thread -> start runner -> submit Input -> stream events -> terminal outcome
                                   |
                    +--------------+--------------+
                    v                             v
G. Standalone web UI                           H. Second-provider integration
   Thread list/detail, composer,               connect the already-proven adapter to
   live timeline, error state,                 Agentplane records/runtime/UI
   interrupt/steer controls
                    \                             /
                     \___________________________/
                                   v
I. First functioning Agentplane orchestrator
   separate Agentplane deployment + separate UI, one Thread at a time, both providers,
   honest failures, live updates, and an end-to-end test
                                   |
                                   v
J. Narrow hardening from observed failures
   idle native resume, accepted-input recovery, Pod replacement,
   reconnect, queue semantics — only as demanded by evidence
                                   |
                                   v
K. Explicit Haku Console integration (deferred)
   adapter/enveloped messages, cross-product links, or selected operator controls;
   no shared internal runtime or persistence authority by accident
```

## Work packets

### A — Native capture (in progress)

**Owner:** dispatched implementation agent.

**Acceptance:** real Claude/Codex native drivers, upstream request/response capture, compact
transcripts, fake-model replay, and provider-specific assertions. No persistence or orchestrator
framework is required here.

### B — Shared protocol and both stdio adapters

Give one agent end-to-end ownership of the shared harness interaction seam. Starting from the native
captures, that agent should:

- define the smallest shared protocol for the proven operations;
- implement both Claude and Codex adapters behind it;
- keep the adapters runnable over stdio, without Kubernetes wiring;
- link each shared protocol item to the native Claude/Codex frame(s) that implement it;
- preserve provider-specific fields and unsupported operations rather than forcing false symmetry;
- drive both adapters through the same scenario corpus; and
- add deterministic fake-model/replay tests plus provider-specific wire assertions.

This is not a general Agentplane protocol, Thread API, database schema, bridge transport, or
lifecycle controller. It is a testable harness-driver seam. The owner is accountable for making the
shared layer genuinely wireable into both providers, not merely documenting an abstract interface.

**Acceptance:** the same shared scenario can be executed against both stdio adapters; tests prove
bidirectional native input/output, model exchange/tool frames where captured, terminal outcomes, and
provider-specific unsupported behavior. The mapping from shared events/commands to native frames is
reviewable in code or compact fixtures. No test imports `haku/console` or requires Kubernetes.

### C — Minimal Agentplane records

Add only the state needed for the first standalone UI slice. Likely records are:

- `Thread`: user-visible identity, provider/harness kind, and current runner reference;
- `Input`: submitted content and accepted/dispatch status;
- `Turn`: start/end and honest terminal outcome; and
- `Event` or native transcript reference: ordered user-visible messages/tool activity needed by the UI.

These records belong to Agentplane's own store. Do not import Haku Console conversation models,
share its database tables, or add a general event-sourcing framework, projection registry, artifact
manifest, runtime epoch, or every future provider field.

**Acceptance:** the Agentplane service can answer “which Threads exist?”, “what happened in this
Thread?”, and “what is the current active Turn?” after its own service restart.

### D — Runner/bridge seam

Build the smallest central-to-runner interface needed by the vertical slice. It must launch the
provider driver, submit one Input, stream native-derived events, and return a terminal outcome.

Keep provider-native ids inside the provider adapter. The Agentplane service need not understand
Claude or Codex wire shapes. Do not freeze transport direction or authentication beyond what the
first separate Agentplane deployment needs.

**Acceptance:** an integration test drives a runner through the same interface used by the
Agentplane service; the test proves an Input, streamed events, tool activity, and terminal outcome.

### E — Agentplane runtime seam

Create a standalone Agentplane process/service boundary with its own configuration, health/readiness,
API, and runner connection path. It may call Kubernetes/Agent Sandbox as an infrastructure authority,
but it must not embed or import Haku Console runtime code.

The first deployment may use a known runner image and one known workspace/PVC layout. Service
creation, endpoint stability, and Pod replacement are separate questions unless the chosen bridge
transport immediately requires them.

**Acceptance:** the standalone Agentplane service can start one runner, observe readiness, connect to
it, and report a clear failure when provisioning or readiness fails.

### F — One-provider vertical slice

Choose the provider with the lowest current integration risk from the capture evidence. Implement:

1. create/open a Thread;
2. ensure a runner exists;
3. submit one Input;
4. stream assistant/tool events;
5. persist enough state for refresh; and
6. show an honest terminal outcome.

**Acceptance:** one end-to-end test runs the standalone Agentplane service, runner, fake model, and
UI-facing API path. It must exercise the real bridge seam, not call provider code directly from the
API handler.

### G — Standalone Agentplane web UI

Build a small UI owned by Agentplane. It may follow proven interaction patterns, but its code and
route/API client remain in the Agentplane namespace and deployment. Do not mount it inside the Haku
Console shell or make the Haku Console SPA its host.

Add only:

- Thread list or one selected Thread route;
- transcript/timeline showing user input, assistant output, tool call/result, and terminal state;
- composer for a new Input;
- live update subscription with reconnect/refetch behavior; and
- visible provisioning, running, failed, and uncertain states.

Do not build a dashboard for every Sandbox, a generic operation-card taxonomy, or settings for future
provider policy.

**Acceptance:** Rai can perform the first functioning workflow from the standalone Agentplane
browser surface without API tooling. A browser refresh preserves the Thread and completed response;
live updates do not require manual refresh during a turn.

### H — Second-provider integration

The shared protocol and both native adapters are already delivered by B. Connect the second provider
to the Agentplane records, runner/runtime seam, deployment, and standalone UI without expanding the
protocol spec unless a real captured requirement demands it.

**Acceptance:** the same standalone Agentplane workflow works for both providers, with
provider-specific limitations visible rather than hidden behind fake equivalence.

### I — First functioning Agentplane orchestrator

The first product gate is one separately deployed Agentplane instance where both providers can:

- start a Thread;
- receive an Input;
- produce streamed assistant output;
- perform and display one tool interaction;
- reach and persist a terminal result; and
- expose provider-specific unsupported/failure states honestly.

A single-Thread/single-runner limitation is acceptable. Multi-Agent, subscriptions, Haku Console
integration, and advanced recovery are not part of this gate.

### J — Hardening from evidence

After I, choose the next failure with the highest user cost. Candidates include:

- idle native resume;
- Input durability and uncertain delivery;
- active-turn interrupt/steering;
- Pod replacement with PVC/native continuity;
- central/bridge reconnect; and
- native queue/dequeue behavior.

Do not implement all candidates in advance. Each gets its own observed failure, smallest test, and
implementation packet.

### K — Explicit Haku Console integration (deferred)

Only after Agentplane works independently should we decide whether Haku Console needs to expose it.
Possible integrations include a link, an enveloped message adapter, or a narrow operator control
surface. Choose one based on a concrete user need; do not merge stores, route ownership, or runtime
lifecycles merely to avoid an HTTP boundary.

## Parallelism and sequencing

- A can continue independently.
- B should happen immediately after the first useful captures, before broad schema or API design;
  one agent should own both the shared layer and both adapters.
- C, D, and E can be designed in parallel after B, but their first implementations should meet F.
- G should start only once F has a real Agentplane API/event shape to render.
- H can proceed alongside G after F, but must not force a premature universal abstraction or
  reopen the shared protocol without new evidence.
- J begins only after I exposes the first real reliability bottleneck.
- K is explicitly downstream of an independently functioning Agentplane; it is not a hidden
  dependency of I.

## Explicit cuts

The following are not blockers for I:

- a protocol broader than the captured Claude/Codex interaction seam;
- multi-Agent rooms/delegation;
- subscriptions and external-event adapters;
- credential/approval redesign;
- custom artifact promotion or DLP systems;
- hashes, body lengths, manifests, or generated projections;
- automatic retention/disposal policy;
- mTLS or elaborate control-channel authentication; and
- Haku Console reuse or a shared Haku Console persistence/runtime boundary.
