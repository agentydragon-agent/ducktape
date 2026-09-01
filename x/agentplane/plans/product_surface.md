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

## Decisions deliberately left open

- Authentik forward-auth versus Agentplane's own OIDC session handling;
- REST event polling versus SSE versus WebSocket for the first client;
- whether the API and UI ship in one Agentplane deployment or as separate deployments;
- PostgreSQL schema and migration packaging;
- whether a future internal runner boundary benefits from gRPC; and
- which provider controls are exposed in the first UI.

These are requirements and design questions, not a priority ordering. The immediate implementation
constraint remains: prove the shared protocol and both native adapters before building broad API or
UI machinery.
