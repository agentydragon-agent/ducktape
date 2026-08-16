# Haku temporary Kubernetes access worker

`haku-kube-jit` is a separate deployment from `haku-console` on purpose. The Console is the
approval/audit and durable-lease authority; this worker is the native-RBAC enforcement projection.
A Console API crashloop must not prevent expiry/revocation reconciliation.

Each approved lease records the exact canonical `PolicyRule[]`, not a predefined role name. The
worker creates a lease-named, labelled `Role` and a `RoleBinding` from that Role to the fixed Haku
cohort. It deletes both on expiry, revocation, authoritative-record mismatch/orphaning, policy-hash
drift, or when it cannot reconfirm the Console record before the confirmation deadline.

## Deliberate high-trust boundary

Kubernetes requires the principal that creates a Role containing permissions it lacks to hold RBAC
`escalate` and `bind`. Since per-lease Role names are dynamic, Kubernetes cannot reduce this using
`resourceNames`. The worker therefore has `escalate` on namespaced Roles in only
`haku-sandbox` and `haku-claude-sandbox`; its independently reviewed code rejects wildcards,
Secrets, RBAC-management resources, and `bind`/`escalate`/`impersonate` rules before persisting a
lease. Neither Haku nor the Console API ServiceAccount receives this Kubernetes authority.

This is still operational rather than mathematically hard expiry: Kubernetes API or worker outages
can delay deletion. Catastrophic permissions need future inline authorization or short-lived
per-lease credentials.
