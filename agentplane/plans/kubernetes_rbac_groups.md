# Reusable Kubernetes RBAC grant groups

Status: **design open; no new Kubernetes authority approved.** The [task DAG](task_dag.md)
tracks `KUBERNETES_RBAC_POLICIES` (decision), `KUBERNETES_RBAC_POLICY_BINDINGS`
(implementation after the decision), and `MANAGED_SA_RBAC` (later accounts without a
Sandbox). This plan records the problem, candidate designs and checks, not a choice of controller.
Existing [agent RBAC documentation](../../cluster/docs/agent_rbac.md) describes deployed/static
ownership; it remains the source for current grant scope.

## Why this is needed

The current [managed grant catalog](../sandbox_service/kubernetes_grants.py) maps a launch-time
name to one concrete RoleBinding or ClusterRoleBinding template. A preset in
[`agent_access_profiles.py`](../../cluster/cdk8s/agent_access_profiles.py) expands shared diagnostics
into many per-namespace selections; the [Sandbox creation form](../app/frontend/sandboxes.tsx)
presents that large list instead of one understandable diagnostics choice. At launch, Sandbox
Service [resolves and stores](../sandbox_service/provisioning.py) concrete selections, and its
[binding reconciler](../sandbox_service/kubernetes_bindings.py) maintains the resulting bindings
for that Sandbox ServiceAccount (SA). Adding a namespace or changing a preset's selections later
does **not** update those existing Sandboxes. Edits to a referenced Kubernetes Role's _rules_ do
affect every existing binding to that Role; this is separate from updating which roles/namespaces
a group includes. The large form and duplicated assignments are the immediate problem; update
propagation to existing SAs is a preference, not an unconditional requirement.

## Desired experience and constraints

- Define a named, subject-free group such as `low-privilege-cluster-diagnostics` containing the
  approved role references and namespace scope. Select one name in a preset or the create form;
  do not present hundreds of individual namespace grants as the normal choice. Kubernetes may
  still require one underlying RoleBinding per namespace/SA.
- Assign it to an SA. A preset supplies defaults for **new** Sandboxes, but editing a preset must
  not silently reassign already-running Sandboxes. An authorized operator must also be able to
  add or revoke one binding for one existing SA at runtime without changing shared groups or
  other SAs. A private singleton group through the _same_ assignment mechanism is acceptable;
  two distinct implementation paths are not required. Overlapping assignments combine
  additively, and removing one must not destroy the other's access.
- **Prefer live group associations:** changes to a group's constituent roles or eligible
  namespaces reconcile for all currently assigned SAs, including removals. **Acceptable
  alternative:** expand once at assignment (Sandbox creation or a later runtime assignment).
  Then existing expanded binding membership remains unchanged until an explicit update; UI and
  docs must make that snapshot semantics clear. Changes to the rules of a referenced Role still
  take effect under either model. Choose this consciously, including the operational cost of
  updating existing assignments.
- Preserve namespace-by-namespace scoping and reviewed namespace opt-in. Do not replace
  namespaced RoleBindings with a broader ClusterRoleBinding for convenience. Existing Role
  definitions and static bindings have their own GitOps/service owners; a new reconciler must
  own only the objects delegated to it. Policy names, assignment origin, expanded scope and reconciliation failures
  must be inspectable. Check actual effective permission with the SA; catalog membership is not
  proof of access.
- Define authorization, audit, revocation, cleanup and same-name SA replacement behavior for
  assignments. An SA cannot grant itself arbitrary RBAC by naming a powerful role. Existing
  Sandboxes with snapshotted concrete grants require an explicit migration decision; do not
  retroactively enroll them because a preset changes. New app/Sandbox Service DB persistence is
  under the archive-ownership scheduling hold in the [task DAG](task_dag.md).

## Candidate mechanisms and prior art

### Agentplane-owned definition and assignment

A Kubernetes CR for the group, plus a binding/assignment (another object or durable state on a
managed Sandbox), could name existing Role/ClusterRole references and explicit namespaces or an
approved namespace selector. A controller would expand the group for assigned SAs, watch changes
to the group, assignments and eligible namespaces if live semantics are selected, and reconcile
only its own generated RoleBindings/ClusterRoleBindings. Existing Sandbox Service binding
reconciliation supplies naming, conflict detection and cleanup patterns, but today its source
of truth is a concrete launch snapshot. A cluster-scoped definition can own namespaced generated
bindings; an assignment attached to a Sandbox must still account for cluster-scoped and
cross-namespace bindings and Sandbox deletion. Do not have two controllers own the same binding.

This can express subject-free reusable groups and independent per-SA membership directly, at
the cost of operating a privileged fan-out controller. The design must specify what happens to
bindings on definition deletion, namespace declassification, failed partial reconcile and
recovery after restart, without creating transient excess privileges or adopting Flux objects.

### Fairwinds RBAC Manager

[RBAC Manager](https://github.com/FairwindsOps/rbac-manager/blob/master/docs/introduction.md) is
an Apache-2.0 operator that reconciles a cluster-scoped
[`RBACDefinition`](https://github.com/FairwindsOps/rbac-manager/blob/master/docs/rbacdefinitions.md)
to native RoleBindings/ClusterRoleBindings. Its documented examples assign a named
Role/ClusterRole to subjects in fixed namespaces or namespaces matching a label selector;
namespace changes and removal of previously generated bindings are part of its reconciliation.
This is close prior art for the namespace fan-out, ownership and revocation problem. It does
not supply separate, subject-free policy and assignment objects: `rbacBindings` combine subjects
with role references and namespace scope. Runtime membership would require patching the
subjects in a definition or generating definitions from another source of truth; Flux and a
runtime writer should not both edit that same subject list.

**Important compatibility gap for dynamically created Sandbox SAs:** in the inspected upstream
[source parser](https://github.com/FairwindsOps/rbac-manager/blob/master/pkg/reconciler/parser.go),
every `ServiceAccount` subject is also added to RBAC Manager's desired SAs. Its
[SA reconciler](https://github.com/FairwindsOps/rbac-manager/blob/master/pkg/reconciler/reconciler.go)
compares ownership (see the [matcher](https://github.com/FairwindsOps/rbac-manager/blob/master/pkg/reconciler/matcher.go))
and may try to create an already-existing SA; an SA owned by Sandbox Service
is not a clean reference-only match. A RoleBinding might still be produced despite an SA-create
conflict; do **not** treat that as a supported integration. We have not established whether a
supported bindings-only mode exists in the version we would deploy. Static `User`/`Group`
subjects are a simpler fit; the existing static public-coder group and a per-Sandbox SA are
_different_ identities. RBAC Manager could be useful for the former without solving the latter.
Do not transfer SA ownership, duplicate the controller's binding names, or replace existing
Flux bindings without an explicit migration. An isolated test with an externally owned SA,
namespace addition/removal and definition deletion would answer the compatibility question.

### Kyverno generation, GitOps and native RBAC aggregation

Kyverno generate rules could produce bindings from eligible namespaces and subjects. This repo
[retired a Kyverno-generated diagnostics-binding path](../../cluster/docs/agent_rbac.md#namespace-reader-migration-kyverno-to-gitops)
in favor of Flux-owned bindings. That does not prove Kyverno cannot implement this requirement,
but reintroducing it needs a clear owner, dynamic SA membership/definition update contract and
reliable generated-resource cleanup. Flux/cdk8s generation works for fixed subjects and reviewed
changes but does not by itself handle runtime-managed Sandbox SAs or their operator-requested
one-SA additions. Native aggregated ClusterRoles combine _rules_, not the RoleBindings across
selected namespaces or the assignment of those bindings to SAs.

## Decision and implementation checks

Compare the mechanisms against **two existing managed Sandbox SAs sharing one group** and a
third SA with a one-off binding. Show the create form's compact selection, then add and remove
an eligible namespace, widen/narrow a referenced Role, change the group membership, revoke the
one-off and shared assignments independently, delete a Sandbox, and restart the controller.
For both snapshot and live semantics, state exactly which existing SAs change after each step,
including same-name SA replacement, partial failures and owner/Flux conflicts. Show how an
operator inspects both intent and expanded grants, and verify representative allowed and denied
requests with the affected SAs. If selecting RBAC Manager, first prove that an externally owned
Sandbox SA can be bound without RBAC Manager trying to own/create/delete it; do not test with a
production SA or credentials. Only after the policy shape is reviewed should
`KUBERNETES_RBAC_POLICY_BINDINGS` implement it. `MANAGED_SA_RBAC` then extends the chosen
assignment/one-off model to SAs with no Sandbox owner, with separate lifecycle and expiry.
