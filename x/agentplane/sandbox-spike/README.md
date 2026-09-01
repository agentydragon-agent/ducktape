# Sandbox proxy and workload identity spike

This disposable experiment tests a standalone Agent Sandbox v0.5.5 Pod containing an uncredentialed
runner and a credentialed fixed-operation proxy. A separate verifier validates the synthetic upstream
credential, a projected audience-scoped ServiceAccount token, the live Pod UID and IP, and the Pod's
Sandbox owner before accepting the operation.

The experiment proves credential exclusion and workload authentication, but it deliberately does not
claim same-Pod network confinement. Kubernetes NetworkPolicy and Cilium select the Pod, not an
individual container: once the proxy sidecar may reach the verifier, the runner shares that L3/L4
route. See [the observed evidence and recommendation](evidence.md).

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
