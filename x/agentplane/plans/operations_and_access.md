# Agent operations, approvals, and cross-agent data access

Status: **design discussion; v0 product decisions recorded, implementation contract still open**.
This note prevents the next approval feature from turning Agentplane into a monolith before the
remaining lifecycle, data-handling, and authority boundaries are settled.

## Why the current “ask” name is provisional

Haku Console's `tool_call` is a useful precedent but is too narrow as the Agentplane product noun:
an operation may invoke an MCP server, use HTTP egress, request Kubernetes authority, read a
trajectory, or ask another service to do work. Conversely, a human approval is only one possible
outcome of an operation and is not the operation itself.

Working vocabulary:

- **ActionRequest**: an agent-originated intent to invoke a named capability with structured input.
- **Decision**: an authorization disposition over an ActionRequest.
- **Execution/Attempt**: one concrete run of an allowed ActionRequest.
- **Delivery**: the machine-readable receipt, state update, result, denial, or pending event sent
  back to the originating Thread.
- **DecisionProvider / Decision Authority**: the component that evaluates and issues a final
  Decision, whether automatically, through a human action, or through an LLM judge.

The accepted product noun is **`ActionRequest`** (or simply `Request` in a scoped API), and the
UI can use “action”. It says “the agent intends this effect”
without claiming that a harness-level tool call, an authorization decision, or an execution has
already happened. `Operation` remains a reasonable internal term for an adapter operation, but it is
too easy to confuse with implementation-level calls. Do not use “ask” or “tool call” in this wire
contract.

A human approval is not a different request shape. Every ActionRequest has the same capability,
arguments, provenance, and correlation fields whether the eventual decision is automatic, human,
LLM-assisted, or denied. The request is submitted to the hub; the decision route is an explicit
recorded transition, not a schema branch known by the agent in advance.

The accepted v0 model separates all three concerns: ActionRequest (intent), Decision
(authorization disposition), and Execution/Attempt (a concrete run). This is slightly more
machinery than one status field, but it matches the desired distinction between waiting for a
decision, being denied, and actually running.

### Accepted v0 decisions

- The product noun is **`ActionRequest`**; do not use “ask” or “tool call” in this contract.
- An ActionRequest is one logical intent, with bounded execution attempts beneath it.
- The request shape is invariant: the agent does not choose a different schema based on whether the
  request is expected to be auto-allowed or human-reviewed.
- After a final `allow` Decision, the Action Hub automatically dispatches the request. There is no
  agent self-approval or universal `commit` step in v0.
- An LLM judge is allowed to issue the final Decision when that provider is implemented and returns
  a decision. If it abstains or refers the request, the request remains `decision_pending` and can
  follow another route; the hub does not downgrade a judge's final verdict to a mere suggestion.
- V0 records Decision issuer and provenance, but does not require cryptographic signing. Signing can
  be added when Decisions cross a trust boundary or replay protection requires it.

## Semantics to settle before implementation

### What an ActionRequest means

An ActionRequest is one logical agent intent, with retries and execution attempts beneath it. A
transient transport retry must not become a new human decision, while each concrete attempt remains
auditable.

Every ActionRequest should preserve the upstream adapter payload as the evidence-bearing body. A
normalized mirror of every MCP argument or provider-specific field is not justified yet.

### Lifecycle

Use one immutable request payload plus separate decision and execution projections:

```text
ActionRequest accepted
  -> decision_pending
  -> allowed              [Decision: allow]
  -> denied               [Decision: deny]

allowed
  -> dispatching -> running
running
  -> succeeded | failed | cancelled

decision_pending
  -> cancelled | withdrawn
```

`decision_pending` means no authority has issued a final disposition yet; the UI may explain that
this is waiting on policy, an LLM judge, or a human, but those are routes, not request schemas.
`allowed` is an authorization result, not a claim that execution has started. `denied` is an
authorization outcome; `failed` means execution began and did not complete; `cancelled` means an
actor withdrew work. Reserve `rejected` for hub-level refusal before a valid request exists (bad
schema, missing identity, or duplicate idempotency key), rather than using it interchangeably with
policy denial.

The durable evidence is an append-only sequence containing the ActionRequest, Decision event(s),
and Execution/Attempt event(s). The hub can maintain a current projection for UI and agent delivery,
but it must not collapse “pending decision,” “denied,” and “running” into one overloaded queue state.

Potential `expired` state is deliberately undecided. Haku's current approval machinery has no
expiry, while credentials and execution attempts may still have independent time limits. Do not add
an expiry state merely because it is conventional.

Remaining questions for Rai:

- Can the originating agent continue while an ActionRequest is `decision_pending`?
- Is the Decision delivered as a later Thread input only, or may a blocked native turn be resumed?
- Is withdrawal agent-controlled, operator-controlled, or both?
- Does one allow Decision authorize all bounded retries, or must a retry be reauthorized after a
  failure class changes?
- Is a standing grant a different object, or a Decision that creates a reusable grant?

The v0 direction is otherwise fixed: submission returns a receipt immediately and never blocks the
agent; a later Decision is delivered as an event/input; withdrawal is available before execution
starts; one allow Decision covers one logical ActionRequest and its bounded retry attempts; standing
authority is a separate grant owned by the existing grants/access machinery; and an allowed request
automatically dispatches with explicit `dispatching` and `running` events.

### Agent-facing UX

The agent-facing result should be a stable machine envelope independent of whether the adapter is
HTTP, Kubernetes, host execution, or MCP. It should distinguish at least:

```json
{
  "kind": "action_receipt",
  "request_id": "ar_...",
  "state": "decision_pending",
  "decision_route": "human",
  "capability": "mcp:github.search_repositories",
  "input": { "...": "..." },
  "message": "The operator has been notified; continue other work.",
  "decision": null
}
```

The final shape is open. In particular, decide whether the agent receives the full input again,
which could contain sensitive data, or only a redacted/reference form. The human UI needs the full
reviewable operation; the agent may need less.

The ActionRequest should be usable for an MCP server without making MCP the core abstraction:

```text
Agent Thread -> Action Hub -> Decision Authority -> MCP Executor -> MCP server/tool
                         -> Decision / result / Execution events
```

An MCP adapter owns server discovery, tool schema, transport, and MCP-specific errors. The policy
authority decides access and approval; Agentplane does not become an MCP registry or a universal
protocol translator.

## Authority boundary

Keep the hub, decision issuers, and executors separate even if the first deployment colocates them:

- **Agentplane runtime**: Sandbox and Thread lifecycle, native runner protocol, and delivery to a
  Thread when a product layer asks it to deliver an event.
- **Action Hub / Action Coordinator**: accepts and durably records ActionRequests, validates
  correlation/idempotency, routes them to a DecisionProvider, persists Decision artifacts, dispatches
  allowed requests to an Executor, and delivers state changes. It is the durable coordinator, not
  the policy authority. V0 artifacts carry issuer and provenance fields but do not require
  cryptographic signatures.
- **DecisionProvider / Decision Authority**: evaluates a request and issues an allow, deny, or
  referral/pending result. The provider may be an automatic policy evaluator, an LLM judge, or a
  human-review adapter. A final Decision names its issuer, basis, request reference, constraints,
  and provenance. When an LLM judge is implemented as the selected provider, its final allow/deny
  result is authoritative; an abstention/referral remains pending rather than becoming an implicit
  denial. Cryptographic signing is deferred from v0 and can be added when the artifact crosses a
  trust boundary or replay protection requires it.
- **Execution adapter / Executor**: MCP/HTTP/Kubernetes/host-specific invocation and result
  translation. It receives an allowed request and creates one or more bounded Execution/Attempt
  records; it does not reinterpret approval policy.
- **Integration/conversation app**: current operator-facing review and presentation, if it owns the
  first Action UX. Human action should enter through a DecisionProvider rather than directly mutating
  hub state.
- **Trajectory store**: durable event evidence and request references, without becoming the policy
  engine or decision issuer.

This gives the requested independent rollout seam: the hub can remain stable while a policy evaluator,
LLM judge, or human-review surface is replaced. The first vertical slice may implement the interfaces
in one deployment, but it must preserve the boundaries and record the issuer of every final Decision.
The hub consumes the Decision result; it does not silently convert a provider's final verdict into a
mere recommendation.
Do not add a generic controller, policy DSL, or MCP gateway until one real consumer requires it.

## Data access and cross-agent reads

Reading a Thread or trajectory is not the same permission as invoking an external tool. A future
cross-agent read needs a policy over at least:

```text
requesting principal
  -> target principal / Thread / data scope
  -> operation (list metadata, search text, read events, read raw frames)
```

Raw frames and search results can carry private data, so “can read the Thread record” is not enough
as a future policy statement. The system may need separate scopes for metadata, derived summaries,
full events, raw native frames, and content-bearing payloads. Do not implement those scopes before a
real cross-agent read consumer establishes the minimum useful boundary.

Agentplane currently has no durable **Agent** entity. A Sandbox is runtime infrastructure and a
Thread is interaction context; neither is a sufficient long-lived identity for statements such as
“Haku may read Public Coder's past conversations.” Before cross-agent reads, decide whether an Agent
is:

- an integration-app-owned identity that may own multiple Sandboxes and Threads;
- an authorization principal supplied by an external access controller; or
- both, with a stable product identity linked to an opaque authorization principal.

Recommendation: keep Agent identity separate from authorization principal, as with the existing
runtime vocabulary. Let the integration app or Agent Console own the mapping from product Agent to
opaque access principal; let the access authority decide read permissions. Agentplane should expose
stable Thread/Sandbox references and enforce a decision at its read boundary, not invent a global
identity and permission registry.

Cross-agent reads are therefore a later design package with two prerequisites:

1. a stable Agent identity and ownership model; and
2. a data-scope/read-policy contract owned outside Agentplane runtime.

Until then, T3 search is scoped to the caller's own authorized trajectory surface, and no API should
pretend that a Sandbox name is an Agent identity.

## MCP and access gating questions

Before wrapping MCP servers, decide:

- whether the MCP server is trusted infrastructure or runs inside the Sandbox;
- whether policy gates server reachability, individual tool calls, or both;
- whether tool schemas and arguments are visible to the operator and to the agent;
- whether an approval authorizes one tool call, a server/tool pair, or a parameterized grant;
- how server-originated content is labeled and protected from prompt injection;
- whether MCP results are copied into the Thread, the trajectory, or both;
- how retries and duplicate tool calls are correlated.

Recommendation: begin with a trusted adapter outside the Sandbox, individual structured tool
invocations, explicit capability names, and one-operation decisions. Let the MCP server remain the
execution authority for its own semantics; let the access authority gate the adapter before it
calls the server.

## Implementation gates

Do not implement the first approval feature until the remaining gates are resolved:

- pending-turn behavior and later-input delivery;
- single-request versus standing-grant semantics;
- the minimum machine envelope and sensitive-field handling; and
- whether the first MCP adapter belongs in the integration app or an external access/adapter layer.

The v0 product decisions already accepted are the `ActionRequest` noun, logical-intent durability,
automatic dispatch after allow, authoritative final decisions from an implemented LLM judge, and no
cryptographic signing requirement in v0.

After those choices, the first implementation should be one end-to-end adapter and one acceptance
scenario, not a universal access framework.
