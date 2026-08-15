# Temporary elevated Kubernetes access for Haku — landscape and decision record

**Status:** research; no access broker is deployed by this document.

This records the options reviewed for an operator-approved request such as:

> Grant Haku these explicitly stated Kubernetes `PolicyRule`s for two hours.

The requirements are deliberately narrower than generic human Kubernetes access:

1. Haku is an adversarial workload at the trust boundary. It may request access, but must
   never be able to grant or renew its own access.
2. The approver sees and accepts a meaningful, bounded permission scope, subjects, and expiry.
   A reviewed named role/profile is acceptable for an initial deployment when it resolves to a
   documented, versioned permission set (or immutable policy hash). Showing literal API groups,
   resources, resource names, and verbs remains the preferred experience for a bespoke broker,
   but is a design goal rather than a hard adoption requirement.
3. The first target cohort is the Haku OIDC group `oidc-ksbx-groups:haku` plus the two
   existing Haku ServiceAccounts (`haku-sandbox/haku` and
   `haku-claude-sandbox/haku-claude`). This intentionally does not distinguish individual
   Haku jobs yet.
4. Sandboxes retain opaque placeholder credentials. When a credential is necessary, it
   stays behind an egress/credential-substitution proxy; it must not become a kubeconfig,
   bearer, or client certificate the sandbox can use outside that boundary. This constrains
   the **sandbox-facing interface**, not the implementation behind the proxy: a layered
   design may exchange the placeholder for an integration- or lease-specific short-lived
   credential at a trusted hop.
5. The solution must be usable without buying a product. Mature open-source components are
   welcome; an operator-reviewed Haku Console workflow remains the authority.

The current permanent Kubernetes boundary is documented in [the Haku security model](security.md)
and the cohort's namespace-local binding is in
[`cluster/k8s/haku/rbac/rolebinding-haku.yaml`](../../cluster/k8s/haku/rbac/rolebinding-haku.yaml).

## Executive decision

No reviewed project is a completely drop-in fit. In particular, upstream Kube JIT cannot express
the initial Haku cohort: its request schema accepts only `userEmails`, and its controller emits
every requested subject as Kubernetes `kind: User`. It cannot create the required OIDC `Group` or
`ServiceAccount` subjects. An adapter cannot repair that after the fact.

The preferred path therefore remains a small, Haku Console-integrated lease broker/reconciler. Its
first profile set can use narrow, named roles appropriate for namespace-scoped RoleBindings. The
Console records the selected role/profile's immutable version or resolved-permissions hash,
approver, reason, expiry, and audit trail before the independent enforcer materializes it.

A maintained Kube JIT fork remains a potential way to avoid writing the lifecycle controller from
scratch, but only after it adds typed Kubernetes subjects and removes the unsafe upstream chart
binding. The bespoke broker is still required for capabilities outside that model, including
arbitrary rules, cluster-scoped grants, or stronger per-lease identities. Both approaches preserve
placeholder-only sandboxes.

### Credential layering is compatible with the placeholder boundary

“Placeholder-only” must not be read as “the existing substituted ServiceAccount token is the
only credential model we can use.” It means the sandbox has no reusable Kubernetes credential
and cannot bypass the trusted request path. A compatible layered route can instead be:

```text
sandbox -> opaque placeholder / lease handle -> Haku egress proxy
        -> optional credential or policy gateway -> Kubernetes API
```

Behind the proxy, the gateway can hold a platform session, exchange the opaque handle for a
short-lived per-lease credential, or execute a narrowly structured operation and return only its
result. The Console lease remains the approval authority in every variant. The gateway must not
offer a route that the sandbox can call with a raw credential or use to mint/renew its own access.

This makes identity platforms such as Teleport, Pinniped, SPIRE, Paralus, or an adapted
infrabroker potentially compatible **components**. It does not make them automatic replacements
for a bounded, approver-visible permission scope and the independent reconciliation requirements
below.

## Options reviewed

“Maturity” below is a maintenance/adoption signal, **not** a security audit or endorsement.
Repository popularity and release history are a research snapshot from 2026-08-15 and will age.

| Project                                                                              | License / maturity signal                                                                                                                                 | What it provides                                                                                                                                                                      | Fit for Haku temporary elevation                                                                                                                                                                                                                                                                                                                                                                                        | Result                                                                                                                                                        |
| ------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [Teleport](https://github.com/gravitational/teleport)                                | AGPL-3.0 source; large, actively maintained project (20k+ GitHub stars; current `v18.10.0` release at review time)                                        | Identity-aware proxy for Kubernetes and other infrastructure, short-lived credentials, audit, roles, and access requests                                                              | Technically strong for proxy-held short-lived identities. A Haku proxy can be layered in front of Teleport, so it need not expose a Teleport credential to a sandbox. Teleport-role/resource selection is now an acceptable approval shape if the selected role/policy version is recorded. Full JIT reviews/resource requests remain Enterprise Identity Governance features.                                          | **Compatible layered component, but do not adopt for this feature under the no-purchase constraint.** Revisit if a broader zero-trust platform is wanted.     |
| [Paralus](https://github.com/paralus/paralus)                                        | Apache-2.0; CNCF Sandbox project, 1.2k+ GitHub stars; maintained but still `v0.x` releases                                                                | Kubernetes access-management control plane with SSO, RBAC, audit, dynamic revocation, and JIT ServiceAccount creation                                                                 | A Haku proxy adapter could keep Paralus credentials behind the sandbox boundary. Its user/service access-management model is more compatible if the Console approval records the selected permission profile and version. It still adds a substantial access/credential control plane and needs a concrete integration review.                                                                                          | **Potential layered component, not a narrow fit.** Evaluate only if adopting a general cluster access manager.                                                |
| [infrabroker](https://github.com/luisgf/infrabroker)                                 | GPL-3.0; very small but active project (10 GitHub stars; `v3.1.2` at review time); its own HA documentation says it is deliberately single-instance today | AI-agent-focused SSH and Kubernetes broker; per Kubernetes operation it mints an in-memory, short-lived bound ServiceAccount token and returns only the operation result to the model | This is the closest discovered project to the no-credential-in-agent goal. It mediates a fixed set of structured `k8s_*` operations under broker policy rather than granting Haku a general, temporary RBAC lease. Adopting it would replace/duplicate Haku Console's tool and approval plane, and its single-instance availability model is unsuitable for the proposed high-power boundary without substantial work.  | **Most useful implementation/design reference for Model B, not an adoption candidate yet.**                                                                   |
| [Kube JIT](https://github.com/samirtahir91/kube-jit)                                 | Apache-2.0; small project (11 GitHub stars; `v1.0.2` released in 2025)                                                                                    | Web/API/controller access-request system, IdP/team approval routing, temporary Kubernetes RBAC, and expiry                                                                            | Its controller can run independently of its UI/API, but its CRD accepts only `userEmails` and its binding code unconditionally emits `kind: User`. It cannot grant the Haku OIDC group or either Haku ServiceAccount; its Helm chart also binds its manager to `cluster-admin`. A Haku-side adapter cannot correct either flaw without a controller/image fork.                                                         | **Reject upstream as deployable enforcement.** A maintained fork could still be a lifecycle-controller candidate after typed-subject and RBAC hardening work. |
| [Pinniped](https://github.com/vmware-tanzu/pinniped)                                 | Apache-2.0; established and active (700+ GitHub stars; `v0.47.0` at review time)                                                                          | Kubernetes identity/login broker for OIDC and other external identities, with Kubernetes-native credential exchange                                                                   | A credible open-source building block for a proxy-held credential exchange. It has no JIT approval workflow or temporary-RBAC reconciliation, so Haku would still need the Console lease broker. It changes the inner Kubernetes authentication route, which is acceptable only if the outer placeholder boundary and no-bypass invariant are retained.                                                                 | **Strong credential-component candidate only; not a JIT access product.**                                                                                     |
| [SPIRE](https://github.com/spiffe/spire)                                             | Apache-2.0; CNCF graduated project, production maturity, 2.4k+ GitHub stars                                                                               | Workload attestation and short-lived SPIFFE identities/SVIDs                                                                                                                          | Stronger workload identity than a static ServiceAccount bearer, but Kubernetes RBAC does not natively turn SPIFFE SVIDs into the required temporary Kubernetes authorizations. It needs an additional authenticator/proxy plus the same approval and rule-lifecycle system.                                                                                                                                             | **Relevant identity building block, not a direct Kubernetes JIT solution.**                                                                                   |
| [akcess](https://github.com/viveksinghggits/akcess)                                  | Apache-2.0; small project (67 GitHub stars); latest release `v0.0.4` was 2022                                                                             | CLI creates Roles, RoleBindings, CSRs, and a kubeconfig from explicitly supplied resource/verb flags; supports a duration                                                             | Its literal resource/verb input is close to the desired approval payload, but its core workflow distributes a kubeconfig/client credential to its caller. A wrapper could theoretically conceal that credential, but akcess provides no broker/proxy integration or reason to add this older direct-credential workflow.                                                                                                | **Reject as an adoption candidate.** Useful as a small implementation reference only.                                                                         |
| [jit-engine](https://github.com/ttauveron/jit-engine)                                | MIT; 1 GitHub star, no releases; explicitly describes itself as a reference implementation                                                                | DB-backed grants, approvals, append-only audit, reconciliation, and a Kubernetes executor                                                                                             | Architecturally similar to the desired Console-DB/reconciler design. Its Kubernetes executor binds a subject to an existing Role/ClusterRole, which is acceptable when the approved payload pins the role/policy revision. It is not mature enough to place on the privilege boundary.                                                                                                                                  | **Do not deploy.** Borrow the state-machine/reconciliation ideas if useful.                                                                                   |
| [kube-escalate](https://github.com/layer87-labs/kube-escalate)                       | No recognized GitHub license metadata at review time; new `v0.3.0` project with very limited adoption                                                     | kubectl plugin that creates an annotated temporary RoleBinding or ClusterRoleBinding; controller currently reaps only annotated **ClusterRoleBindings**                               | It resolves the caller through `SelfSubjectReview` then always binds that caller as a Kubernetes `User`. Giving Haku its required create/bind authority would permit self-escalation, and it cannot create the required one-grant group-plus-ServiceAccount cohort. More seriously, its namespace RoleBinding plugin path is not watched by the current operator, so it does not actually enforce expiry for that path. | **Reject.** The privilege boundary and the currently incomplete namespace-expiry implementation are incompatible.                                             |
| [Argo CD Ephemeral Access](https://github.com/argoproj-labs/argocd-ephemeral-access) | Apache-2.0; active Argo project, 100+ GitHub stars and recent releases                                                                                    | Temporary Argo CD AppProject-role elevation                                                                                                                                           | It governs Argo CD authorization, not Kubernetes API RBAC.                                                                                                                                                                                                                                                                                                                                                              | **Out of scope.**                                                                                                                                             |
| [RBAC Manager](https://github.com/FairwindsOps/rbac-manager)                         | Apache-2.0; established, actively maintained project (1.6k+ GitHub stars)                                                                                 | Declarative management of Kubernetes ServiceAccounts and RoleBindings through CRs                                                                                                     | Useful for durable, GitOps-managed RBAC. It has no approval workflow or expiry/revocation protocol, regardless of whether approval selects a role or literal rules.                                                                                                                                                                                                                                                     | **Not a lease broker.** Do not use as the authority for Haku escalation.                                                                                      |

### Adjacent projects screened

The search also found projects that are not meaningful alternatives to a general temporary-RBAC
broker:

- [Kube-Argus](https://github.com/manishchaudhary101/kube-argus) is an active Apache-2.0
  dashboard with an approval-gated temporary **pod exec** feature. It is useful for that narrow
  operational action, not arbitrary Kubernetes API permissions.
- [Just-in-time Access Controller](https://github.com/ItsThatDude/jit-access-controller) and
  [jitverno](https://github.com/m-augustine/jitverno) are small/early CRD-controller efforts.
  The former was examined more closely below; it has useful policy/approval concepts but is not
  deployable unchanged for Haku. Neither has enough adoption, documentation, or an appropriate
  credential model to displace the focused broker design.
- Commercial PAM/JIT products exist as a separate market, but are intentionally not candidates
  under the no-purchase constraint. This review does not claim to be a complete vendor catalog.

### Compatibility re-check of the closest controller alternatives

The first pass classified several projects by their advertised temporary-access features. A source
review is necessary here: a controller that can expire a binding is not automatically able to grant
the required subjects, and it must not require the requesting workload to create its own binding.

#### Just-in-time Access Controller: useful concepts, but another user-only grant engine

[`ItsThatDude/jit-access-controller`](https://github.com/ItsThatDude/jit-access-controller)
has a more promising declarative model than upstream Kube JIT on its _policy_ side:
`AccessPolicy.spec.requesters` and `approvers` are typed `rbacv1.Subject` values, and a policy can
restrict duration, roles, or literal `PolicyRule`s. It also has native approval CRs.

That flexibility stops before enforcement. Its
[`AccessRequestBaseSpec`](https://github.com/ItsThatDude/jit-access-controller/blob/main/api/v1alpha1/common_request_types.go)
records a single string `subject` (and optional source `groups`), and an approved grant records
that same single string. The
[`createRoleBinding`](https://github.com/ItsThatDude/jit-access-controller/blob/main/internal/processors/grants.go)
implementation then unconditionally constructs:

```go
rbacv1.Subject{Kind: "User", Name: status.Subject, APIGroup: "rbac.authorization.k8s.io"}
```

It therefore has the same material compatibility failure as upstream Kube JIT: it cannot preserve
the Haku OIDC `Group` subject or represent either required `ServiceAccount`, much less issue the
fixed three-subject cohort in one approval. Its namespace path also rejects a `ClusterRole` role
reference, even though Kubernetes itself permits a namespace `RoleBinding` to reference a
`ClusterRole`; that would rule out the phase-one reviewed ClusterRole-profile approach.

Its generated manager role is also unsuitable unchanged. It has broad cluster-wide create/delete
access to RoleBindings and ClusterRoleBindings and grants `create`, `delete`, `bind`, and
`escalate` for Roles and ClusterRoles without a reviewed `resourceNames` allowlist. A fork would
need a typed target-subject list, a revised grant/status API, binding-generation and test changes,
ClusterRole-in-RoleBinding support, and a new capability role. That is at least as much security-
critical work as the Kube JIT fork, so it is **not** the preferred fork basis.

#### kube-escalate: a TTL/reaper reference, not an authority boundary

[`layer87-labs/kube-escalate`](https://github.com/layer87-labs/kube-escalate) has a compact,
understandable expiry loop: it labels a binding, records an RFC3339 expiry annotation, installs a
finalizer, and requeues at the expiry instant. That lifecycle code is a useful small reference.

Its architecture is intentionally self-service, however. The
[`Escalate`](https://github.com/layer87-labs/kube-escalate/blob/main/internal/plugin/escalate.go)
plugin calls `SelfSubjectReview` and creates a binding whose sole target is the calling identity as
`kind: User`. It needs the calling client to have authority to create the relevant RoleBinding or
ClusterRoleBinding (and, where needed, RBAC `bind` authority). That authority cannot be given to
Haku or a sandbox safely, regardless of Console approval elsewhere.

There is an additional implementation discrepancy worth treating as a blocker, rather than relying
on the README diagram: the plugin has an `--namespace` path that creates a `RoleBinding`, but the
current [operator reconciler](https://github.com/layer87-labs/kube-escalate/blob/main/internal/operator/controller.go)
watches only `ClusterRoleBinding` objects. Namespace-scoped plugin grants are thus not scheduled
for TTL deletion by the released controller. Do not use this project for Haku's namespaced phase,
even behind an adapter, until that is fixed and independently reviewed.

#### Telekom k8s-breakglass: a full authorization gateway, not a RoleBinding controller

[`telekom/k8s-breakglass`](https://github.com/telekom/k8s-breakglass) is materially more capable
than a TTL controller, but solves a different layer. Its approved
[`BreakglassSession`](https://github.com/telekom/k8s-breakglass/blob/main/api/v1alpha1/breakglass_session_types.go)
causes its authorization service/webhook to treat an authenticated **user** as having a configured
temporary `grantedGroup`; the escalated group is then granted RBAC in the target cluster. It does
not make temporary native RoleBindings for a supplied list of Kubernetes subjects.

That can be a strong future Model B-style architecture: a trusted Haku-facing proxy could use a
session-aware authorization gateway, so expiry is checked on every request instead of relying only
on eventual RoleBinding deletion. But it would require adopting and operating its OIDC, API,
webhook, session, and cluster configuration stack, and adapting its per-user group-injection model
to Haku's OIDC-group plus ServiceAccount cohort. The existing ServiceAccounts do not naturally map
to a human/OIDC breakglass session. It is therefore **not a phase-one replacement** for a small
Console lease reconciler, but is the best reviewed option to revisit if strict inline expiration
and a general authorization gateway become requirements.

### Conditional composition: Haku Console + a maintained Kube JIT fork

The Kube JIT operator explicitly documents that it can run without its API and web UI, and be
integrated with another approval system through its `JitRequest` CRD and status callback. This
would make it a useful lifecycle component **after a maintained fork**, not an upstream component
to deploy unchanged.

```text
Haku request -> Console approval + durable lease/outbox
             -> narrowly privileged Haku-to-Kube-JIT adapter
             -> approved JitRequest CRD -> maintained Kube JIT operator fork -> temporary RoleBinding(s)
             -> status callback / watch -> Console audit state

Console revocation/expiry -> adapter deletes JitRequest -> operator removes RoleBinding(s)
```

The adapter, not a sandbox and not a general Haku tool, is the only client allowed to create or
delete `JitRequest`s. It creates them only after consuming a committed Console approval/outbox
record. The Console remains the system that decides whether to issue or revoke a lease; the forked
controller becomes the independent Kubernetes enforcement/reaping component.

The fork must first replace upstream `userEmails: []string` with validated typed Kubernetes
`subjects: []rbacv1.Subject` and copy those subjects into the generated RoleBindings. That is
necessary to represent the initial fixed cohort: `oidc-ksbx-groups:haku` as a `Group`, plus
`haku-sandbox/haku` and `haku-claude-sandbox/haku-claude` as `ServiceAccount`s. This is not
optional and cannot be solved by a Console adapter alone.

After that change, the first profile set can be limited to pre-reviewed ClusterRole names applied
through namespace RoleBindings. No ClusterRoleBinding or cluster-scoped grant is required for this
phase. The adapter must independently restrict fixed subjects, approved role/profile versions,
namespace allowlists, maximum duration, and a fixed internal callback endpoint. It must not give
Haku write access to `JitRequest` or `KubeJitConfig`.

- The upstream Helm chart is **not deployable as-is at this trust boundary**: its manager
  `ClusterRoleBinding` binds the operator ServiceAccount to Kubernetes `cluster-admin`; its source
  tree separately contains a narrower generated manager `ClusterRole`, but the chart does not bind
  it. A fork/hardening pass must at least
  replace that binding with a reviewed capability role, pin the image rather than use `latest`,
  and review controller behavior. The first deployment may intentionally give it broad
  cluster-wide `RoleBinding` lifecycle authority if it needs to serve many namespaces, but it
  should still receive only the permissions it uses and a tightly named `bind` allowance for the
  approved ClusterRole profiles—not unrelated Kubernetes API authority. It is an enforcement
  engine, not an approval boundary.

If this composition passes that review, it avoids writing a reaper/controller from scratch while
keeping Haku Console's manual approval queue, audit record, and placeholder-facing proxy model.
The bespoke lease broker remains necessary only for capabilities the controller cannot safely
express (for example, arbitrary rules, cluster-scoped grants, or a stronger per-lease identity).

#### Deployment footprint

Only the Kube JIT **operator** is relevant; do not deploy its upstream API, web UI, or PostgreSQL
stack. This deployment section applies to the maintained fork, not the unsafe upstream image. The
upstream operator Helm chart renders 21 Kubernetes objects: three CRDs, one Deployment, one
ServiceAccount, nine CRD aggregation roles, leader-election RBAC, metrics resources, and the
manager binding. A separate `KubeJitConfig` custom resource supplies the allowed role names and
namespace regular expression.

That is an upper bound, not a recommended manifest set. A hardened fork can remove the optional
CRD aggregation/metrics resources, pin the operator image, and replace the upstream
`cluster-admin` binding with:

- cluster-scoped read/write access only for Kube JIT's own CRDs and namespace discovery;
- `RoleBinding` lifecycle access across the target namespaces, plus `bind` restricted by
  `resourceNames` to the reviewed ClusterRole profiles; and
- namespace-local leader-election RBAC for the operator namespace.

The simple option is one reviewed cluster-scoped capability role for the operator: it is broad in
namespace reach but materially narrower than `cluster-admin`. The stronger option uses a
namespace-local Role/RoleBinding pair for each target namespace; it reduces compromise blast
radius but adds two objects per namespace. Either option is roughly a low-teens base object set
plus a NetworkPolicy. An optional external adapter would add one small Deployment,
ServiceAccount/RBAC, configuration, and egress policy. Alternatively, a reviewed Console
background worker can be the adapter, avoiding that extra workload while keeping the adapter's
Kubernetes credential out of `haku-sandbox`.

#### Console integration shape

One new **in-process Haku Console MCP server**, named `kube-jit`, is sufficient as the
Agent-facing surface. Its tools should be small:

- `list_access_profiles` and `get_grant` / `list_grants` are read-only discovery/status tools;
- `request_namespaced_grant` takes a profile, allowed namespace, duration, and justification; and
- `revoke_grant` removes an existing lease.

The two mutation tools use Haku Console's existing MCP approval queue: an Agent submits the tool
call, the trusted Console UI shows the normal approval card, and only an Operator approval causes
the tool to commit a grant/revocation record. No second approval product or separate MCP deployment
is needed.

The MCP tool is only the entrance, not the Kubernetes authority. Console implementation still
needs a grant/outbox database migration, profile validation, tool schemas/tests, and an adapter
worker that creates or deletes `JitRequest`s idempotently after the approval commit. That worker
may be a reviewed Console background worker or the small separate adapter described above; it must
be the only principal with write access to Kube JIT CRDs. This is moderate integration work, with
the Kube JIT chart hardening and least-privilege RBAC review likely exceeding the MCP-tool code.

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

### Model A — future custom lease of native RBAC on the existing Haku identities

If Kube JIT is not adopted or a capability outside its namespace-RoleBinding model is needed, keep
the current identity/request route and use a bespoke broker. The broker creates:

- a generated `Role` plus `RoleBinding` for namespace-scoped rules, or
- a generated `ClusterRole` plus `ClusterRoleBinding` for genuinely cluster-scoped rules,

either from literal approved rules or from an approved named profile. For a profile, the Console
records its name, source, resolved permissions, and immutable version/content hash at approval
time. The broker should materialize that resolution into a lease-specific role where practical;
if it instead binds a pre-existing role, it must continuously verify the pinned revision and revoke
or require re-approval on drift.

Each binding has the three fixed cohort subjects. Haku continues to send its placeholder
credential to its forced proxy route. In the simplest deployment the proxy substitutes the current
shared credential; in a layered deployment it can instead forward to a trusted gateway that holds
the appropriate inner identity. Nothing reusable reaches a sandbox in either case.

The Console's lease record must include, at minimum:

```text
lease ID; approval scope (canonical PolicyRule[] or profile name/version);
resolved-permissions SHA-256; scope; fixed subjects; requested-by; approved-by;
approval/tool-call reference; reason; issued-at; expires-at;
desired/observed/revoked state
```

The generated Kubernetes objects carry `managed-by`, lease ID, `expires-at`, and the resolved
permissions hash. The broker compares that hash before accepting an object as its own.

The Haku normal identity must **not** receive permission to create/update/delete Roles,
ClusterRoles, RoleBindings, ClusterRoleBindings, `TokenRequest`s, or to use the RBAC `bind`,
`escalate`, or `impersonate` verbs. Only the independently deployed broker/reconciler receives the
narrow authority needed to materialize an approved lease.

### Model B — proxy-held, lease-specific identity

For high-risk future leases, add a short-lived identity that exists only behind the proxy:

1. The broker creates a per-lease ServiceAccount and RBAC objects representing the approved scope.
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
- [infrabroker README](https://github.com/luisgf/infrabroker/blob/main/README.md),
  [Kubernetes API](https://github.com/luisgf/infrabroker/blob/main/docs/API.md), and
  [HA assessment](https://github.com/luisgf/infrabroker/blob/main/docs/HA.md).
- [Kube JIT README](https://github.com/samirtahir91/kube-jit/blob/main/README.md),
  [operator README](https://github.com/samirtahir91/kube-jit/blob/main/controller/kube-jit-operator/README.md),
  [JitRequest's user-only schema](https://github.com/samirtahir91/kube-jit/blob/main/controller/kube-jit-operator/api/v1/jitrequest_types.go#L26-L52),
  [controller's forced `User` subjects](https://github.com/samirtahir91/kube-jit/blob/main/controller/kube-jit-operator/internal/controller/utils.go#L192-L228),
  [upstream Helm manager binding](https://github.com/samirtahir91/kube-jit/blob/main/controller/kube-jit-operator/charts/kube-jit-operator/templates/manager-rbac.yaml), and
  [operator RBAC source](https://github.com/samirtahir91/kube-jit/blob/main/controller/kube-jit-operator/config/rbac/role.yaml).
- [Pinniped README](https://github.com/vmware-tanzu/pinniped/blob/main/README.md).
- [SPIRE README](https://github.com/spiffe/spire/blob/main/README.md).
- [akcess README](https://github.com/viveksinghggits/akcess/blob/master/README.md).
- [jit-engine README](https://github.com/ttauveron/jit-engine/blob/main/README.md) and
  [Kubernetes executor](https://github.com/ttauveron/jit-engine/blob/main/plugins/kubernetes/executor.go).
- [kube-escalate architecture](https://github.com/layer87-labs/kube-escalate/blob/main/docs/architecture.md).
- [Argo CD Ephemeral Access README](https://github.com/argoproj-labs/argocd-ephemeral-access/blob/main/README.md).
- [RBAC Manager README](https://github.com/FairwindsOps/rbac-manager/blob/master/README.md).
- [Kube-Argus README](https://github.com/manishchaudhary101/kube-argus/blob/master/README.md) and
  [Just-in-time Access Controller README](https://github.com/ItsThatDude/jit-access-controller/blob/main/README.md).
