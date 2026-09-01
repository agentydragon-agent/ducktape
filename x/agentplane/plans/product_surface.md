# Agentplane product-surface inventory

This document records desired capabilities without assigning priority or implementation sequence. The
orchestrator DAG decides sequencing only after native-driver evidence exists.

## Product shape

Agentplane should be a standalone, headless orchestrator service. A separate UI or integration app
should consume its API and own the user-facing presentation.

```text
Claude/Codex native adapters
          |
    shared stdio driver protocol
          |
   standalone Agentplane service
      |                 |
 user/control API     live events
      |                 |
 separate Agentplane UI / integration app
          |
 Kubernetes deployment behind Authentik
```

Agentplane and Haku Console remain separate products. Haku Console integration, if wanted later,
is an explicit client/adapter relationship rather than shared runtime, database, or frontend code.

## Desired capabilities

### Deployment and access

- Run Agentplane as its own Kubernetes deployment/service.
- Provide a stable externally reachable route for the UI/API.
- Put the route behind Authentik for private access.
- Keep runner Pods, PVCs, readiness, and workload lifecycle under the Kubernetes/Agent Sandbox
  boundary.
- Make the service's health, readiness, and provisioning failures visible to its clients.

### User/control API

The service should eventually expose a deliberate API for the app in front of it, including:

- create or launch a conversation/Thread;
- list Threads;
- retrieve a Thread timeline and current status;
- submit Inputs;
- observe live assistant, tool, provisioning, and terminal events;
- interrupt or steer where the provider supports it;
- assign or change a user-facing name; and
- archive and unarchive Threads.

Archiving should initially mean “remove from the active view while retaining history,” not deletion
or an automatic retention policy.

The API should expose stable Agentplane concepts such as Thread, Input, Turn, Event, status, and
outcome. It should not require clients to understand native Claude or Codex frame shapes.

### Separate UI / integration app

A separate app in front of Agentplane should eventually provide:

- Thread launch and provider selection;
- names and archive controls;
- active/archive views;
- transcript and tool-activity display;
- live progress and terminal outcome;
- honest unavailable/failed/uncertain states; and
- controls for supported interrupt/steering operations.

The first UI may be intentionally small. Its value is proving that the API supports a real user
workflow, not demonstrating a complete dashboard.

## API transport direction

### Recommended starting point

Use ordinary REST with an OpenAPI contract for resource reads and commands, plus SSE or WebSocket for
live Thread events. This is the lowest-friction choice for a browser-facing app, easy to inspect and
replay, and sufficient for one Agentplane service with runner adapters behind it.

Keep the API implementation independent of Haku Console's existing routes and models. The API can
start in the same repository as Agentplane while remaining a distinct package and deployment.

### gRPC question

gRPC is worth reconsidering if Agentplane later has independently deployed runner workers, needs
strongly typed bidirectional streaming between services, or develops non-browser clients that benefit
from generated stubs. It is not necessary to make the first standalone service runnable and would
add browser gateway, schema, and operational complexity before those requirements exist.

A useful future option is REST/OpenAPI at the user boundary and gRPC internally, but that should be
introduced only after a concrete internal service boundary or streaming limitation appears. Do not
make the native stdio driver protocol resemble gRPC merely for symmetry.

## Deferred Haku Console-adjacent capabilities

Haku Console already contains or may eventually provide capabilities that Agentplane could consume,
but they are deliberately not on the current schedule:

- Agent credential management and egress-time credential substitution;
- user-approved tool calls;
- per-Agent auto-approval policy; and
- explicit integration between the Agentplane API and Haku Console authority.

These should not leak into the first Agentplane service as accidental dependencies. When they become
important, define an explicit integration contract and ownership boundary first.

## Deferred sandbox-bound request identity

A useful future capability would let a downstream MCP server or Kubernetes service authenticate that
a request came from the specific Agent or Thread running in a specific sandbox, while ensuring the
Agent never receives the real credential.

A possible future flow is:

```text
integration app requests Thread + selected MCP server/credential binding
        |
Agentplane records the binding and starts the Thread's sandbox
        |
sandbox-side runner or Agent Gateway obtains a non-secret, scoped identity proof
        |
proxy/service validates the proof as belonging to this Thread/sandbox
        |
proxy substitutes the real credential only at the egress/service boundary
```

This is a capability inventory, not a design commitment. The following questions must be answered
before scheduling implementation:

- What authority binds Agent, Thread, Sandbox Claim, Pod, and credential without trusting agent-
  supplied claims?
- Is the proof minted by Agentplane, the Sandbox controller, an Agent Gateway, or a separate
  identity service?
- How does the verifier detect replay, copying to another sandbox, Pod replacement, and stale
  Threads?
- Does the proof identify a Thread, an Agent, a runner instance, or a narrower request capability?
- Where is the real credential substituted, and how do we prove it never reaches the Agent,
  environment, native frames, logs, or workspace?
- Can an MCP server validate the proof directly, or must all such traffic pass through a trusted
  gateway?
- What does Agent Sandbox's roadmap or Agent Gateway actually guarantee, versus merely propose?

A token held in a harness-runner process could be part of the solution only if that runner is a
trusted process isolated from the Agent. Process memory alone is not a security boundary when the
Agent can inspect the same container, user, PID/IPC namespace, filesystem, inherited descriptors, or
local sockets. A future design must establish what prevents the Agent from observing or invoking the
credential-bearing process.

This makes the Agent Sandbox team's roadmap and any Agent Gateway design especially relevant
research inputs. We should inspect their actual guarantees before choosing between a trusted runner,
sidecar, gateway, or another proof mechanism; do not assume the roadmap provides a current product
contract.

When this is eventually scheduled, start with a threat-model and current-roadmap discovery spike,
then a small end-to-end proof of sandbox-bound authentication and secret exclusion. Do not add a
generic identity/fencing protocol to the first orchestrator in anticipation of this work.

### Isolation is a separate boundary from harness driving

The harness driver should not be responsible for protecting egress credentials. Its job is to drive
the native Claude/Codex protocol and record provider behavior. Credential confidentiality belongs to
the sandbox/runner/egress composition around that driver.

A local proxy with an unauthenticated transport can be reasonable in a strongly isolated sandbox:
the placement boundary says which sandbox can reach the proxy, while the proxy enforces a narrow,
non-generic operation policy and substitutes the real credential. But “localhost” or an unauthenticated
socket is not protection when Agent-controlled code shares the proxy's process/container/security
domain. A generic forward proxy would also be an exfiltration oracle: the Agent could ask it to send
the credential to an attacker-controlled destination or abuse a signing operation. The proxy must
therefore constrain destinations, operations, and request shapes, and direct egress must be blocked.

The implementation consequence is deliberate separation: capture and adapter features can be
implemented and tested without solving credential isolation; the later isolation proof can wrap the
same runner/driver seam without changing native harness semantics.

## Decisions deliberately left open

- Authentik forward-auth versus Agentplane's own OIDC session handling;
- REST event polling versus SSE versus WebSocket for the first client;
- whether the API and UI ship in one Agentplane deployment or as separate deployments;
- PostgreSQL schema and migration packaging;
- whether a future internal runner boundary benefits from gRPC;
- which provider controls are exposed in the first UI; and
- the eventual authority and proof format for sandbox-bound request identity.

These are requirements and design questions, not a priority ordering. The immediate implementation
constraint remains: prove the shared protocol and both native adapters before building broad API or
UI machinery.
