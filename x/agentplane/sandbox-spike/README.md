# Sandbox proxy and workload identity spike

This disposable experiment tests a standalone Agent Sandbox v0.5.5 Pod containing an uncredentialed
runner and a credentialed fixed-operation proxy. A separate verifier validates the synthetic upstream
credential, a projected audience-scoped ServiceAccount token, the live Pod UID and IP, and the Pod's
Sandbox owner before accepting the operation.

The experiment proves credential exclusion and workload authentication, but it deliberately does not
claim same-Pod network confinement. Kubernetes NetworkPolicy and Cilium select the Pod, not an
individual container: once the proxy sidecar may reach the verifier, the runner shares that L3/L4
route. See [the observed evidence and recommendation](evidence.md).

The eventual choice is recorded in [ADR: credentialless Sandbox egress](../plans/adr_sandbox_proxy_gateway.md).

## What this spike was asked to answer

Create a practical, disposable proof—not a production identity framework—for the following eventual
Agentplane capability:

- an Agent/runner must not receive a real upstream credential;
- a small per-Sandbox proxy should expose only an explicitly granted operation;
- the proxy may hold a short-lived, audience-scoped Kubernetes Pod token;
- a trusted upstream gateway should verify that token against Kubernetes and identify the live Pod and
  its Sandbox owner before authorizing the operation; and
- the real upstream credential should be held and substituted only at that trusted gateway.

The proof had to test the actual pinned Agent Sandbox and cluster rather than assume that a Sandbox CR,
NetworkPolicy, ServiceAccount, SPIFFE, or service mesh automatically supplies the desired guarantees.

## Scope and acceptance

This is a completed security-boundary experiment, not a production identity framework or an Agentplane
runtime task. Its acceptance boundary is the evidence below: a standalone Sandbox creates the intended
runner/proxy Pod; only the proxy receives the synthetic Secret and Pod-bound token; the fixed operation
works through the authenticated gateway; direct, forged, copied, stale, and replayed proofs are rejected;
and restart, rotation, replacement, and suspension behavior is recorded. The evidence must distinguish
what is proven from what is unsupported, blocked by the environment, or inferred.

The spike deliberately does not implement Claude/Codex driving, Agentplane Thread/Input/Turn persistence,
production credential provisioning, warm pools, a generic identity or fencing protocol, a service mesh,
or stronger runtime isolation. In particular, it does not claim that a sidecar plus NetworkPolicy can
prevent direct runner TCP access within the same Pod; the trusted gateway's application authentication is
the enforcement boundary.

## Constraints and things deliberately avoided

The experiment used two standalone, non-warm-pooled Sandboxes in a disposable namespace, with no native
Claude/Codex dependency, Agentplane persistence, Haku Console dependency, Authentik integration,
production credential, cluster-wide SPIRE/service-mesh installation, or stronger runtime installation.
It avoided generic forwarding, `CONNECT`, arbitrary destinations, caller-selected credentials, forged
identity headers, production-template edits, and treating source IP, labels, or a shared ServiceAccount
as sufficient identity by themselves.

The key network constraint was tested explicitly: Kubernetes NetworkPolicy and Cilium select the Pod
network identity, not an individual sidecar container. Therefore a proxy sidecar cannot, by itself,
make the runner's direct TCP route disappear while preserving the same route for the sidecar. The
accepted boundary is instead application authentication at the gateway: direct runner traffic may
reach the gateway, but it cannot present the hidden valid Pod token and is rejected.

## Run

Use an admin kubeconfig against a disposable cluster or namespace. The script creates the
`agentplane-sandbox-spike` namespace and one uniquely named TokenReview ClusterRole/binding, runs all
positive, attack, restart, rotation, and suspension checks, then removes everything even when a check
fails.

```bash
./x/agentplane/sandbox-spike/run_proofs.sh
```

The script refuses to reuse an existing namespace. A manual cleanup, if the client is interrupted
before its exit trap runs, is:

```bash
kubectl delete -k x/agentplane/sandbox-spike --ignore-not-found
```

No production credential is used. `manifests/secret.example.yaml` contains only an obviously fake
value. The scripts never print authorization headers, the synthetic value, or projected tokens.

## Results

The live proof passed on Kubernetes v1.35.1 with Agent Sandbox v0.5.5 and Cilium:

- only the proxy received the synthetic Secret and projected Pod-bound token;
- the verifier authenticated the namespace, ServiceAccount, Pod UID, current Pod IP, and Sandbox owner;
- copying a token between Sandboxes, forged headers, invalid credentials, and replayed requests failed;
- proxy/runner restart, Secret reload, and Sandbox suspend/resume behaved as expected;
- Pod replacement changed the Pod identity and invalidated the old bound token; and
- direct runner TCP access was **not** blocked because the runner and proxy share the Pod network
  identity, but direct unauthenticated operations were rejected by the verifier.

The complete classification of proven, unsupported, environment-blocked, and inferred results is in
[evidence.md](evidence.md). The short version is: Secret exclusion plus Pod/Sandbox authentication is
usable; same-Pod route confinement is not available from NetworkPolicy/Cilium alone.

## Shape

```text
Sandbox A or B Pod                 verifier Deployment
  runner                            TokenReview + Pod/Sandbox lookup
    no Secret/token mounts          synthetic credential comparison
    fixed local client              timestamp + in-memory nonce check
  proxy
    synthetic Secret
    Pod-bound projected token
    fixed POST /operate API
```

The runner and proxy use separate mount sets, PID namespaces, and writable `emptyDir` volumes. They
still share a network namespace, Pod IP, ServiceAccount identity, kernel, node, and resource envelope.
The verifier's source-IP check is combined with TokenReview and a live Pod lookup; source IP alone is
not treated as identity.

## Resulting deployment architecture

The spike points to a two-proxy design for a credentialed production route; it does not implement
this external gateway:

```text
runner/Agent
  -> unauthenticated fixed-operation request to its local sidecar
  -> sidecar attaches its hidden audience-scoped Pod token
  -> trusted external gateway authenticates and authorizes the live Pod/Sandbox
  -> gateway makes the allowlisted upstream request and adds any real upstream credential
```

Cilium policy permits the Sandbox Pod to reach only DNS and the trusted gateway, while only the
gateway may reach the protected upstream. Because runner and sidecar share a Pod network identity,
the runner can still open TCP directly to the gateway. The gateway therefore rejects every request
without the sidecar-held token; this is application-level enforcement, not proof that the runner has
no route.

The local sidecar exposes only the capability intentionally granted to the Agent. The gateway remains
the final authority: it validates the token audience, ServiceAccount, live Pod UID/source IP, Sandbox
owner, destination, method, path, redirects, and private-address exclusions before issuing a request.
It must not become an arbitrary forward proxy, `CONNECT` tunnel, or signing oracle. A public origin
such as `http://example.com` needs no upstream credential, but follows the same authenticated and
authorized route; credentialed origins add the real credential only at the gateway.

## Files

- `manifests/`: standalone Sandboxes, verifier, scoped RBAC, Secret, and NetworkPolicies actually
  applied by the proof
- `runner/runner.py`: runner observations and positive/negative request client
- `proxy/proxy.py`: fixed-operation credential injector; not a forward proxy or arbitrary signer
- `verifier/verifier.py`: bounded upstream verifier with Pod/Sandbox correlation and replay check
- `run_proofs.sh`: fail-fast reproduction and cleanup
- `evidence.md`: observed results, unsupported properties, limitations, and recommendation
