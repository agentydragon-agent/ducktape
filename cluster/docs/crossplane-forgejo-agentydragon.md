# Crossplane OpenTofu ownership spike

This spike moves `tf/gitops/forgejo-agentydragon` from tofu-controller to Upbound's
`provider-opentofu`. That root manages the four SSH public keys on the Forgejo
`agentydragon` account.

The Crossplane `Workspace` uses the same `forgejo_agentydragon` PostgreSQL schema and
`default` OpenTofu workspace as the existing tofu-controller `Terraform` object. It does
not import or copy state. The existing root is removed from the `forgejo-gitops` bundle;
tofu-controller's CRD defaults `destroyResourcesOnDeletion` to `false`, so pruning that CR
leaves both the Forgejo keys and remote state in place. The Crossplane Kustomization depends
on `forgejo-gitops`, so it starts only after Flux has completed that handoff. The two
controllers therefore do not reconcile the same state at once.

Crossplane manages `Observe`, `Create`, and `Update`. OpenTofu can create, change, and remove
resources as the HCL changes. `Delete` is omitted and the Workspace has
`deletionPolicy: Orphan`, so deleting the Crossplane object will leave the Forgejo keys and
backend state intact for recovery or a later owner.

The Workspace uses provider-opentofu's Inline source. cdk8s combines the root's
ordinary `.tf` files from Bazel runfiles into `spec.forProvider.module`. Edit the
native Terraform files and regenerate manifests in the same PR. The existing Flux
push path applies the changed spec, triggering Crossplane reconciliation without a
Git module download. Periodic drift plans continue. See the
[source-trigger design and Remote-to-Inline cutover](crossplane-opentofu-artifact-triggers.md).

The root's Kubernetes Secret data source runs under the provider's Kubernetes
identity, not tofu-controller's `tf-runner` service account, so the provider's actual
Secret access remains part of live validation.

After merge, verify that `forgejo-gitops` becomes Ready after pruning the Terraform CR, then
that `crossplane-forgejo-agentydragon` becomes Ready while observing the four existing keys
from the existing state. Confirm the provider's first plan is a no-op and subsequent edits
to this root reconcile through Crossplane. That establishes the operational ownership move;
per-root RBAC remains follow-up work for evaluating a broader tofu-controller migration.
