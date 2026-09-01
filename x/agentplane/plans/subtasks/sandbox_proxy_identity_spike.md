# Subtask: research and prove sandbox egress proxy and workload identity

Status: **standalone research/experimentation task**; needed support for a future credentialed Agentplane
deployment, not a requirement for the first harness-driver slice.

## Agent task packet

**Mission:** determine what sandbox composition the current pinned Agent Sandbox and cluster can actually
support, then commit the smallest runnable manifests and evidence needed to reproduce it.

**Primary question:** can we create one disposable, per-agent Sandbox whose runner has no real upstream
credential and whose traffic is forced through a small proxy that can authenticate the intended workload?

**Do not assume the answer is yes.** A useful result may be a proof that secret isolation works but workload
identity or direct-egress confinement does not. Record that as a product decision, not as a failed demo.

## Smallest useful outcome

Create one standalone, non-warm-pooled Agent Sandbox workload with an inner runner and a small per-sandbox
egress proxy. Prove, with a synthetic credential and a test verifier, that:

- the runner/Agent can reach an allowed upstream operation only through the proxy;
- the proxy can use a real credential without mounting or returning it to the runner;
- the verifier can authenticate which sandbox/workload is connected; and
- the result and limitations are explicit for Sandbox identity, Thread binding, freshness, and secret
  exclusion.

This is a security-boundary experiment, not an Agentplane harness-driver or product-API task.

## P0 behavior for this spike

The experiment must answer these questions with evidence:

1. Can a standalone `Sandbox` or `SandboxClaim` create the required Pod shape from a Sandbox CR?
2. Can a Kubernetes Secret be mounted only into the proxy container, with no Secret mount, ServiceAccount
   token, or credential-bearing environment variable in the runner container?
3. Can NetworkPolicy/CNI configuration deny direct runner egress while allowing the proxy's required
   upstream route?
4. Can the upstream verifier authenticate the proxy/workload using the strongest practical current
   mechanism—compare the available Agent Sandbox identity path, Pod-bound identity, and SPIFFE/SPIRE if
   available rather than assuming one?
5. Can two separately created Sandboxes be distinguished, and does the verifier reject a proof or credential
   copied from Sandbox A when presented from Sandbox B?
6. What happens after proxy restart, runner restart, Sandbox suspension/resume if available, Pod replacement,
   Secret rotation, and stale/replayed requests?

## Preferred test shape

```text
standalone Sandbox (one per experiment identity; no warm pool)
├── runner: fake Agent/native-harness-shaped client
│   ├── no Secret volume
│   ├── no ServiceAccount token
│   └── no direct route to protected upstream
└── proxy: small fixed-purpose egress gateway
    ├── read-only Secret volume with synthetic upstream credential
    ├── workload identity client, if available
    └── narrow operation API on localhost or another sandbox-only route
```

The proxy must not be a generic HTTP forwarder or signing oracle. Use one or two fixed synthetic operations
with explicit origin, method, path, and payload validation. The upstream test verifier should record the
authenticated workload identity and whether the request was accepted; it must never log the synthetic
credential.

A Secret reference in the PodSpec is not itself evidence that the runner cannot read the Secret. The test
must inspect the runner's environment and filesystem, attempt only permitted local observations, and verify
that the runner has no Kubernetes API authority. Do not weaken cluster safeguards to make the test pass.

## Identity comparison

Test and document the best mechanism actually available in the pinned cluster, at minimum:

- ordinary Kubernetes ServiceAccount/TokenReview only if a token is deliberately provisioned for the test;
- the Agent Sandbox identity or routing mechanism, if the controller exposes one;
- SPIFFE/SPIRE X.509-SVID/mTLS if the cluster has it or can run it in an isolated disposable test setup.

For each mechanism, state exactly what is authenticated:

- namespace/ServiceAccount;
- Pod UID;
- Sandbox or SandboxClaim;
- proxy workload;
- Agentplane Agent/Thread; and
- request freshness.

Do not call a source label, source IP, forwarded header, or shared ServiceAccount identity “Sandbox
identity” without an independent verifier and an explicit trust argument.

## Required attack and lifecycle checks

The spike must attempt and record results for:

- direct runner connection to the protected upstream;
- arbitrary destination through the proxy;
- forged or modified forwarded identity fields;
- copying an identity proof or token from Sandbox A to Sandbox B;
- replaying an accepted application request;
- use of a stale proof after expiry, Thread archive, or Sandbox replacement;
- runner access to proxy environment, mounted paths, `/proc`, shared volumes, local sockets, and crash/log
  output to the extent permitted by the test boundary;
- proxy restart and Secret rotation/reload; and
- Pod replacement or suspension/resume if supported by the chosen Sandbox mode.

A failure of availability or proxy integrity may be acceptable for this slice if the Agent cannot extract the
real credential or turn the proxy into an unrestricted egress/signing oracle. Report those properties
separately.

## Execution sequence

1. Inspect the pinned Agent Sandbox CRDs, controller version, and current repository templates. Confirm the
   actual fields for a standalone `Sandbox`, `SandboxTemplate`, sidecar containers, volumes, lifecycle, and
   network-policy ownership before writing manifests.
2. Inspect the target cluster's CNI/NetworkPolicy support and available identity services. Do not install a
   cluster-wide identity system, service mesh, or CNI change as part of this task.
3. Build the smallest disposable test images or reuse existing images where adequate: a runner that makes
   fixed HTTP test calls, a constrained proxy, and an upstream verifier. The proxy and verifier must have
   bounded logging and must never print credential material.
4. Commit manifests for a namespaced, non-warm-pooled Sandbox with runner and proxy sidecar, a synthetic
   Secret, the required NetworkPolicy, and the verifier route. Prefer sidecar-local communication so a
   Service is not needed unless the experiment proves one is required.
5. Apply only the disposable resources, run the positive and negative tests, inspect the resulting Pod,
   mounts, environment, routes, and controller status, then clean up the live experiment without deleting
   unrelated resources.
6. Record results in `evidence.md`, separating **proven**, **unsupported**, **blocked by environment**, and
   **inferred** claims. Commit the manifests, test harness, and evidence together so another agent can rerun
   the experiment.

If a required cluster capability is unavailable, commit the best faithful manifests plus the exact observed
blocker. Do not replace a missing identity or network guarantee with a forged header, source-IP assertion, or
an unreviewed cluster-wide installation.

## Dependencies

- Pinned Agent Sandbox version and its actual `Sandbox`/`SandboxClaim`/`SandboxTemplate` PodSpec behavior.
- A disposable test namespace with no production credentials.
- A synthetic upstream service/verifier that can inspect mTLS identity or a test assertion without logging
  credential material.
- Current cluster CNI/NetworkPolicy behavior.
- Agent Sandbox roadmap and any Agent Gateway implementation that is actually present.

Do not depend on the native Claude/Codex binaries, Agentplane persistence, Haku Console, Authentik, or a
production credential.

## Write surface

Prefer a short experiment directory and an evidence memo, for example:

```text
x/agentplane/sandbox-spike/
  README.md                 # exact run and cleanup instructions
  manifests/
    namespace.yaml          # disposable only, if needed
    sandbox-template.yaml   # or standalone Sandbox podTemplate
    sandbox.yaml
    secret.example.yaml     # placeholder only; never real Secret data
    network-policy.yaml
    verifier-route.yaml     # only if a route/Service is actually needed
  proxy/
  verifier/
  tests/
  evidence.md
```

The exact layout may differ, but the committed result must include the manifests actually used, the image
build/run instructions for any custom proxy or verifier, and the observed evidence. Keep manifests and tests
small and disposable. Do not modify the existing production `agent-workspaces` or Haku templates merely to
make the experiment easier; copy the relevant shape into a clearly named test namespace.

Do not add a production identity library, generic policy engine, credential registry, Thread persistence
schema, or driver-protocol changes. Do not commit credentials, raw Secret data, HTTP Authorization headers,
or private user data. An example Secret must contain only an obviously fake placeholder and must not be
usable against LiteLLM, GitHub, or another real service.

The agent must make a normal repository commit containing the experiment artifacts and evidence. The commit
message should identify the experiment and should not mix unrelated cleanup or Agentplane implementation.

## Acceptance test and evidence

The task is complete when a reviewer can run or inspect one reproducible test that shows:

- the Sandbox CR creates the intended runner/proxy Pod;
- only the proxy receives the synthetic Secret;
- direct egress is denied and the allowed proxy operation succeeds;
- the verifier identifies the actual workload using the tested mechanism;
- cross-Sandbox copying and the defined replay/lifecycle cases have explicit results; and
- the evidence memo clearly labels what is **proven**, **unsupported**, **blocked by environment**, or merely
  **inferred**.

The memo must end with a recommendation among:

- proceed with Secret-mounted proxy sidecars;
- use a trusted external gateway instead;
- use a runner-mediated one-shot handoff as a temporary fallback; or
- require a stronger runtime such as Firecracker/Kata before treating the Agent as hostile.

The recommendation must include the exact remaining gap, not just “use SPIFFE/SPIRE.”

## Explicit non-goals

Do not implement in this spike:

- Claude/Codex native protocol driving, capture, replay, steering, interrupt, or resume;
- Agentplane Thread/Input/Turn/Event persistence or API;
- warm pools or pre-warmed Sandbox adoption;
- production credential provisioning or rotation automation;
- a generic Agent/Thread identity or fencing protocol;
- a service mesh solely to make the demo look complete;
- Firecracker integration unless the experiment establishes that ordinary container/sidecar isolation is
  insufficient and a separate follow-up is approved; or
- claims that a successful mTLS handshake proves Thread identity or anti-replay.
