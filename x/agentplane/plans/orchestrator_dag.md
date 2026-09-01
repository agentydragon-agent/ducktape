# First functioning orchestrator: task DAG

This is the next-stage product DAG after the native capture task. It is a dependency map, not a
request to build every future Agentplane subsystem.

## Recommended product slice

Build the first orchestrator inside the existing Haku Console deployment shape rather than creating
a second service and web application immediately. Reuse its FastAPI service, PostgreSQL, operator
identity, React shell, live event channel, and Sandbox-claim integration. Put new native bridge and
provider code under `x/agentplane/`; split services only when a concrete deployment boundary requires
it.

The first user-visible outcome is:

> Rai can open a Thread, start one Claude or Codex runner, send an Input, watch the native/model-backed
> response and tool activity arrive in the web UI, and see an honest terminal outcome.

The first slice should work for one provider first, then add the second provider through the same
behavioral contract. It should not wait for multi-Agent collaboration, subscriptions, approvals,
retention policy, or a generalized control plane.

## DAG

```text
A. Native capture task (in progress)
   real provider frames + upstream model exchanges + driver/replay evidence
                         |
                         v
B. Capture review and minimum contract
   choose only the shared operations proven by both providers
   (start/resume, submit, events, interrupt/steer where supported)
          |                         |                         |
          v                         v                         v
C. Minimal product records       D. Runner/bridge seam       E. Sandbox launch seam
   Thread, Input, Turn,          provider driver lifecycle,   one runner Pod/PVC,
   native event, outcome         bidirectional events         observe/restart
          \                         |                         /
           \_______________________|________________________/
                                   v
F. One-provider vertical slice
   create Thread -> start runner -> submit Input -> stream events -> terminal outcome
                                   |
                    +--------------+--------------+
                    v                             v
G. Web UI slice                              H. Second-provider adapter
   Thread list/detail, composer,             same user-visible behavior using
   live timeline, error state,               provider-specific native driver
   interrupt/steer controls
                    \                             /
                     \___________________________/
                                   v
I. First functioning orchestrator
   one Haku Console deployment, one Thread at a time, both providers,
   honest failures, live updates, and an end-to-end test
                                   |
                                   v
J. Narrow hardening from observed failures
   idle native resume, accepted-input recovery, Pod replacement,
   reconnect, queue semantics — only as demanded by evidence
```

## Work packets

### A — Native capture (in progress)

**Owner:** dispatched implementation agent.

**Acceptance:** real Claude/Codex native drivers, upstream request/response capture, compact
transcripts, fake-model replay, and provider-specific assertions. No persistence or orchestrator
framework is required here.

### B — Capture review and minimum contract

**Owner:** TPM/product review plus provider implementation owner.

Read the captures and write a short decision record containing only operations both providers
actually support or explicit provider-specific alternatives. Do not design the full Thread/Turn
schema first.

**Acceptance:** each proposed operation cites a real capture/test; unsupported operations are listed
as such; no speculative queue or recovery semantics are normative.

### C — Minimal product records

Add only the state needed for the first UI slice. Likely records are:

- `Thread`: user-visible identity, provider/harness kind, and current runner reference;
- `Input`: submitted content and accepted/dispatch status;
- `Turn`: start/end and honest terminal outcome; and
- `Event` or native transcript reference: ordered user-visible messages/tool activity needed by the UI.

Do not add a general event-sourcing framework, projection registry, artifact manifest, runtime epoch,
or every future provider field.

**Acceptance:** the database can answer “which Threads exist?”, “what happened in this Thread?”, and
“what is the current active Turn?” after a service restart.

### D — Runner/bridge seam

Build the smallest central-to-runner interface needed by the vertical slice. It must launch the
provider driver, submit one Input, stream native-derived events, and return a terminal outcome.

Keep provider-native ids inside the provider adapter. The central service need not understand Claude
or Codex wire shapes. Do not freeze transport direction or authentication beyond what the first
trusted deployment needs.

**Acceptance:** an integration test drives a runner through the same interface used by the service;
the test proves an Input, streamed events, tool activity, and terminal outcome.

### E — Sandbox launch seam

Connect one runner to the existing Sandbox/Claim/PVC machinery. Reuse Kubernetes/Agent Sandbox for
workload lifecycle; do not create an Agentplane workload controller.

The first deployment may use a known runner image and one known workspace/PVC layout. Service
creation, endpoint stability, and Pod replacement are separate follow-up questions unless the chosen
bridge transport immediately requires them.

**Acceptance:** the service can start one runner, observe readiness, connect to it, and report a clear
failure when provisioning or readiness fails.

### F — One-provider vertical slice

Choose the provider with the lowest current integration risk from the capture evidence. Implement:

1. create/open a Thread;
2. ensure a runner exists;
3. submit one Input;
4. stream assistant/tool events;
5. persist enough state for refresh; and
6. show an honest terminal outcome.

**Acceptance:** one end-to-end test runs the service, runner, fake model, and UI-facing API path. It
must exercise the real bridge seam, not call provider code directly from the API handler.

### G — Web UI slice

Reuse the existing Haku Console frontend patterns. Add only:

- Thread list or one selected Thread route;
- transcript/timeline showing user input, assistant output, tool call/result, and terminal state;
- composer for a new Input;
- live update subscription with reconnect/refetch behavior; and
- visible provisioning, running, failed, and uncertain states.

Do not build a dashboard for every Sandbox, a generic operation-card taxonomy, or settings for future
provider policy.

**Acceptance:** Rai can perform the first functioning workflow from the browser without API tooling.
A browser refresh preserves the Thread and completed response; live updates do not require manual
refresh during a turn.

### H — Second-provider adapter

Port the proven vertical behavior to the other native provider using its own driver. Reuse only
behavior that the capture review established as genuinely common.

**Acceptance:** the same user-visible workflow works for both providers, with provider-specific
limitations visible rather than hidden behind fake equivalence.

### I — First functioning orchestrator

The first product gate is one deployed Haku Console instance where both providers can:

- start a Thread;
- receive an Input;
- produce streamed assistant output;
- perform and display one tool interaction;
- reach and persist a terminal result; and
- expose provider-specific unsupported/failure states honestly.

A single-Thread/single-runner limitation is acceptable. Multi-Agent, subscriptions, and advanced
recovery are not part of this gate.

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

## Parallelism and sequencing

- A can continue independently.
- B should happen immediately after the first useful captures, before broad schema or API design.
- C, D, and E can be designed in parallel after B, but their first implementations should meet at F.
- G should start only once F has a real API/event shape to render.
- H can proceed alongside G after F, but must not force a premature universal abstraction.
- J begins only after I exposes the first real reliability bottleneck.

## Explicit cuts

The following are not blockers for I:

- complete common protocol formalization;
- multi-Agent rooms/delegation;
- subscriptions and external-event adapters;
- credential/approval redesign;
- custom artifact promotion or DLP systems;
- hashes, body lengths, manifests, or generated projections;
- automatic retention/disposal policy;
- mTLS or elaborate control-channel authentication; and
- a separate orchestrator deployment.
