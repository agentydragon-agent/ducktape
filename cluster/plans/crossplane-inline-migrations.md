# Crossplane inline migration status

The application roots (`gatus-sso`, `forgejo-claude`, and
`alloy-otlp-bearer-token`) and five Forgejo roots (`haku-state`, `budget-ledger`,
`cpap-data`, `finance-agent`, and `forgejo-agentydragon-repos`) have completed their
handoffs to Crossplane OpenTofu Workspaces. The SSO/access roots and Forgejo registry
Terraform root were also migrated. Each Workspace uses its existing PostgreSQL schema
and OpenTofu `default` workspace; state export/import, credential rotation, and
infrastructure recreation were not part of these migrations.

## Retired gates and source artifacts

This change removes the empty Flux Kustomizations that owned the retired Terraform
objects, plus ArtifactGenerator entries for Terraform roots whose handoffs have
completed. Before removing those entries, live checks confirmed the old Terraform
objects were absent and replacement Workspaces were Ready and Synced for their current
generations.

The `authentik-tf` and `forgejo-gitops` Kustomizations are no longer used as prune gates.
Their ArtifactGenerator sources remain because the nested Workspace directories still
consume files from those source trees. The five legacy Forgejo `tf-gitops-*` source
artifacts have been removed after the old Terraform objects were absent and all five
replacement Workspaces were current and healthy.

GitLab's attempted inline migration was rolled back by PR #12133 after its generated
Terraform version file was found missing. The original Terraform owner is restored and
Ready at its current generation. Its GitOps and Terraform Kustomizations had applied
the same artifact revision before the empty Workspace prune gate was removed. The
GitLab Terraform module, state, credentials, and native resource addresses remain.

The LiteLLM `litellm-keys-tf` Kustomization remains because it applies the BuildBuddy
credential used by the live-test key sync. The retired `litellm-keys` Terraform source
is no longer included; the separate `litellm-buildbuddy-sync` source and executable
remain.

The GitHub roots (`github-branch-protection`, `github-secrets-sync`, and
`flux-webhook-token`) are Ready and Synced under Crossplane. Their retired Terraform
source artifacts and empty `github-tf` gate can be removed after the gate's live
`deletionPolicy: Orphan` is confirmed. Keep the `github-tf` artifact: the three nested
Workspace Kustomizations still consume it.

## Reconciliation and recovery

Active Workspaces keep Orphan deletion policy and Observe/Create/Update management
policies so deleting a Workspace does not destroy its managed infrastructure. HCL
changes can still delete resources. Workspace Kustomizations use a health check that
requires `Synced=True` for the current generation and `Ready=True`.

If a future replacement fails, keep the old Terraform object absent while diagnosing.
To return ownership, pause Crossplane reconciliation, remove the Workspace with Orphan
policy, verify it no longer owns the state, then restore the old Terraform object. Keep
the original state schema and `default` workspace throughout.

Other parked roots and roots with executable or mixed-format dependencies remain
outside these completed migrations.
