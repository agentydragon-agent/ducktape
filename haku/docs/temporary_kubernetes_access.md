# Temporary elevated Kubernetes access for Haku — landscape and decision record

**Status:** research; no access broker is deployed by this document.

This records the options reviewed for an operator-approved request such as:

> Grant Haku these explicitly stated Kubernetes `PolicyRule`s for two hours.

The requirements are deliberately narrower than generic human Kubernetes access:

1. Haku is an adversarial workload at the trust boundary. It may request access, but must
   never be able to grant or renew its own access.
2. The approver sees and accepts the **exact** API groups, resources, resource names,
   verbs, scope, subjects, and expiry. A named role is not an adequate substitute.
3. The first target cohort is the Haku OIDC group `oidc-ksbx-groups:haku` plus the two
   existing Haku ServiceAccounts (`haku-sandbox/haku` and
   `haku-claude-sandbox/haku-claude`). This intentionally does not distinguish individual
   Haku jobs yet.
4. Sandboxes retain opaque placeholder credentials. When a credential is necessary, it
   stays behind an egress/credential-substitution proxy; it must not become a kubeconfig,
   bearer, or client certificate the sandbox can use outside that boundary.
5. The solution must be usable without buying a product. Mature open-source components are
   welcome; an operator-reviewed Haku Console workflow remains the authority.

The current permanent Kubernetes boundary is documented in [the Haku security model](security.md)
and the cohort's namespace-local binding is in
[`cluster/k8s/haku/rbac/rolebinding-haku.yaml`](../../cluster/k8s/haku/rbac/rolebinding-haku.yaml).

## Executive decision

No reviewed project is a drop-in fit. The preferred path is a small, Haku Console-integrated
lease broker:

```text
Haku request -> Console approval + durable database lease
             -> independent reconciler/reaper
             -> generated temporary Role/ClusterRole + RoleBinding/ClusterRoleBinding
             -> existing Haku proxy-mediated Kubernetes request path
```

The broker's request contains literal Kubernetes `PolicyRule`s. After approval it creates a
fresh, lease-named Role or ClusterRole from those rules and binds it to the fixed Haku cohort.
The Haku Console database stores the immutable approved payload, approver, reason, expiry, and
an audit trail; Kubernetes holds only generated enforcement objects with a lease ID, expiry, and
canonical rules hash.

This is smaller and easier to audit than installing a second identity platform, preserves
placeholder-only sandboxes, and gives the approver the exact-rule semantics required here.

## Options reviewed

“Maturity” below is a maintenance/adoption signal, **not** a security audit or endorsement.
Repository popularity and release history are a research snapshot from 2026-08-15 and will age.

| Project                                                                              | License / maturity signal                                                                                          | What it provides                                                                                                          | Fit for Haku temporary elevation                                                                                                                                                                                                                                                                                                                                        | Result                                                                                                                              |
| ------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| [Teleport](https://github.com/gravitational/teleport)                                | AGPL-3.0 source; large, actively maintained project (20k+ GitHub stars; current `v18.10.0` release at review time) | Identity-aware proxy for Kubernetes and other infrastructure, short-lived credentials, audit, roles, and access requests  | Technically strong for proxy-held short-lived identities, but full JIT reviews/resource requests are Enterprise Identity Governance features. It would also make Teleport a new access plane that all privileged Haku Kubernetes traffic must traverse. Standard requests grant Teleport roles/resources, not an arbitrary, approved Kubernetes `PolicyRule[]` payload. | **Do not adopt for this feature under the no-purchase constraint.** Revisit only if a broader zero-trust access platform is wanted. |
| [Paralus](https://github.com/paralus/paralus)                                        | Apache-2.0; CNCF Sandbox project, 1.2k+ GitHub stars; maintained but still `v0.x` releases                         | Kubernetes access-management control plane with SSO, RBAC, audit, dynamic revocation, and JIT ServiceAccount creation     | A credible open-source platform, but it owns the access/credential control plane. It would replace or substantially rework Haku's existing proxy-mediated model, and its documented model is user/service access management rather than Haku Console approving arbitrary native RBAC rules for a fixed cohort.                                                          | **Not a narrow fit.** Worth a separate evaluation only if adopting a general cluster access manager.                                |
| [akcess](https://github.com/viveksinghggits/akcess)                                  | Apache-2.0; small project (67 GitHub stars); latest release `v0.0.4` was 2022                                      | CLI creates Roles, RoleBindings, CSRs, and a kubeconfig from explicitly supplied resource/verb flags; supports a duration | Its literal resource/verb input is close to the desired approval payload, but its core output is a distributed kubeconfig/client credential. That directly conflicts with the placeholder-only sandbox constraint. Its Kubernetes dependencies target the 2022 era.                                                                                                     | **Reject.** Useful as a small implementation reference only.                                                                        |
| [jit-engine](https://github.com/ttauveron/jit-engine)                                | MIT; 1 GitHub star, no releases; explicitly describes itself as a reference implementation                         | DB-backed grants, approvals, append-only audit, reconciliation, and a Kubernetes executor                                 | Architecturally similar to the desired Console-DB/reconciler design. Its Kubernetes executor binds a subject to an existing Role/ClusterRole; it does not generate a temporary role from exact rules. It is not mature enough to place on the privilege boundary.                                                                                                       | **Do not deploy.** Borrow the state-machine/reconciliation ideas if useful.                                                         |
| [kube-escalate](https://github.com/layer87-labs/kube-escalate)                       | No recognized GitHub license metadata at review time; new `v0.3.0` project with very limited adoption              | kubectl plugin plus controller that deletes annotated temporary RoleBindings/ClusterRoleBindings                          | It requires the requesting client to create the binding and only binds existing roles. Giving Haku those create/bind permissions would permit self-escalation. Its own design also accepts that expiry waits for operator recovery.                                                                                                                                     | **Reject.** The privilege boundary is incompatible.                                                                                 |
| [Argo CD Ephemeral Access](https://github.com/argoproj-labs/argocd-ephemeral-access) | Apache-2.0; active Argo project, 100+ GitHub stars and recent releases                                             | Temporary Argo CD AppProject-role elevation                                                                               | It governs Argo CD authorization, not Kubernetes API RBAC.                                                                                                                                                                                                                                                                                                              | **Out of scope.**                                                                                                                   |
| [RBAC Manager](https://github.com/FairwindsOps/rbac-manager)                         | Apache-2.0; established, actively maintained project (1.6k+ GitHub stars)                                          | Declarative management of Kubernetes ServiceAccounts and RoleBindings through CRs                                         | Useful for durable, GitOps-managed RBAC. It has no approval workflow, exact-payload lease semantics, or expiry/revocation protocol.                                                                                                                                                                                                                                     | **Not a lease broker.** Do not use as the authority for Haku escalation.                                                            |

### Teleport in more detail

Teleport is the only reviewed option that materially improves the _credential_ side of this
problem. Its Kubernetes Service proxies requests to the Kubernetes API and uses Kubernetes
impersonation headers for permitted users, groups, or ServiceAccounts. Teleport checks its own
role policy before forwarding. A standard flow is:

```text
workload/client -> Teleport-authenticated request -> Teleport Kubernetes Service
                -> impersonated Kubernetes user/group -> Kubernetes API + native RBAC
```

A short-lived Teleport identity can therefore expire even if a Kubernetes RoleBinding were to
linger. It also provides audit events and can proxy more than Kubernetes.

However, it does not remove the need for a carefully designed authority:

- the Teleport Kubernetes Service needs `impersonate` permission for every Kubernetes identity it
  may project;
- privileged Haku traffic must not retain a bypass around the Teleport proxy;
- Haku would need a Teleport workload identity or an iron-proxy-to-Teleport bridge, which is a
  second credential system to operate;
- requests normally select predeclared Teleport roles or resources. Supporting an approver-visible
  arbitrary Kubernetes rule list would still require a Haku-side broker to generate and manage a
  Teleport role/policy;
- Teleport's own documentation calls full Access Requests, resource requests, reviews, and dual
  authorization Enterprise features. Community Edition permits a limited CLI role-request flow,
  with approval by an Auth Service administrator, not the desired Haku Console approval path.

Teleport remains a good future platform decision if the operator wants one identity-aware gateway
for Kubernetes, hosts, databases, MCP, and agent workloads. It is not the economical or minimal
implementation for this one control.

## Recommended design

### Model A — lease extra native RBAC on the existing Haku identities

For the first implementation, keep the current identity/request route. The broker creates:

- a generated `Role` plus `RoleBinding` for namespace-scoped rules, or
- a generated `ClusterRole` plus `ClusterRoleBinding` for genuinely cluster-scoped rules.

Each binding has the three fixed cohort subjects. The Role/ClusterRole contains only the exact
approved rules; it never references a shared role whose content could drift. Haku continues to
send its placeholder credential to its forced proxy route, and the proxy substitutes the same
current real credential. Nothing new reaches a sandbox.

The Console's lease record must include, at minimum:

```text
lease ID; canonical PolicyRule[]; scope; fixed subjects; requested-by;
approved-by; approval/tool-call reference; reason; issued-at; expires-at;
rules SHA-256; desired/observed/revoked state
```

The generated Kubernetes objects carry `managed-by`, lease ID, `expires-at`, and the rules hash.
The broker compares that hash before accepting an object as its own.

The Haku normal identity must **not** receive permission to create/update/delete Roles,
ClusterRoles, RoleBindings, ClusterRoleBindings, `TokenRequest`s, or to use the RBAC `bind`,
`escalate`, or `impersonate` verbs. Only the independently deployed broker/reconciler receives the
narrow authority needed to materialize an approved lease.

### Model B — proxy-held, lease-specific identity

For high-risk future leases, add a short-lived identity that exists only behind the proxy:

1. The broker creates a per-lease ServiceAccount and exact generated RBAC objects.
2. It obtains a bounded ServiceAccount token using `TokenRequest` and stores it only in the proxy
   side of the trust boundary.
3. The sandbox still supplies an opaque lease handle/placeholder. The proxy maps it to the
   lease-specific credential and substitutes it only for the Kubernetes API route.
4. At expiry the proxy refuses to substitute the token, and the broker deletes the identity and
   RBAC objects.

This gives stronger expiry than Model A: even if cleanup is temporarily delayed, an expired
credential can no longer authorize a new Kubernetes request. It does add credential rotation,
proxy session mapping, and a second identity lifecycle, so it is not the first implementation.

### Lifecycle and failure requirements

Kubernetes RBAC has no TTL condition. An `expires-at` annotation is not enforcement on its own.
The broker needs all of the following:

- Console/database writes are the approval and desired-state authority; no CRD or GitOps manifest
  provides a second path to create a lease.
- A dedicated, separately deployed reconciler runs with leader election and at least two replicas.
  Normal Haku Console pod rolls do not affect already-materialized Kubernetes objects.
- An independent expiry reaper deletes managed objects past their stamped expiry even when the
  Console API or database is unavailable. While the database is unavailable, issuing and renewing
  leases fails closed.
- On startup, the reconciler sweeps generated objects, removes expired/orphaned ones, and recreates
  missing objects only for active leases with a matching immutable record.
- Revocation deletes Kubernetes enforcement objects before marking the lease revoked.
- Alert if a high-risk lease is active while the reconciler/reaper is unhealthy, or if any managed
  binding remains past expiry.

Model A offers operationally robust, but not cryptographically hard, expiry: if every enforcement
worker is unavailable at deadline, a binding can remain effective until a reaper recovers. Model B
or an inline authorization proxy is required before treating expiry as a strict security boundary.
Neither model undoes data already read, long-lived workload changes, or effects an elevated caller
created before expiration.

## Source material

- Teleport [feature matrix](https://github.com/gravitational/teleport/blob/master/docs/pages/feature-matrix.mdx),
  [Kubernetes access controls](https://github.com/gravitational/teleport/blob/master/docs/pages/enroll-resources/kubernetes-access/controls.mdx),
  and [Access Requests](https://github.com/gravitational/teleport/blob/master/docs/pages/identity-governance/access-requests/access-requests.mdx).
- [Paralus README](https://github.com/paralus/paralus/blob/main/README.md).
- [akcess README](https://github.com/viveksinghggits/akcess/blob/master/README.md).
- [jit-engine README](https://github.com/ttauveron/jit-engine/blob/main/README.md) and
  [Kubernetes executor](https://github.com/ttauveron/jit-engine/blob/main/plugins/kubernetes/executor.go).
- [kube-escalate architecture](https://github.com/layer87-labs/kube-escalate/blob/main/docs/architecture.md).
- [Argo CD Ephemeral Access README](https://github.com/argoproj-labs/argocd-ephemeral-access/blob/main/README.md).
- [RBAC Manager README](https://github.com/FairwindsOps/rbac-manager/blob/master/README.md).
