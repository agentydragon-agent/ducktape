# Crossplane Inline migration batches

## Merge sequence

1. Expand the shared cluster diagnostics role to read Crossplane objects, including
   Provider packages, revisions, runtime configs, ProviderConfigs and Workspaces.
   Grant no core Secret reads or access to the PostgreSQL state backend.
2. Migrate `gatus-sso`, `forgejo-claude`, and `alloy-otlp-bearer-token` together.
   Factor the existing Inline Workspace construction and configure Kubernetes identities
   (application-root migration, PR #12105).
3. Migrate the five remaining active Forgejo roots together: `haku-state`,
   `budget-ledger`, `cpap-data`, `finance-agent`, `forgejo-agentydragon-repos`.
   This Forgejo migration builds on the application-root migration and remains draft
   until that migration's live handoff is verified (PR #12109, stacked on PR #12105).

## Handoff and verification

Each replacement uses the existing PostgreSQL backend/schema and OpenTofu `default`
workspace. No state export, import, password rotation, or repository recreation is
part of a migration. Keep native HCL resource addresses and legacy `removed` blocks.

Flux prunes each old tofu-controller Terraform CR with resource destruction disabled
before the replacement Workspace's Kustomization runs. Old and new Kustomizations
share one ExternalArtifact, with the new output in a separate nested path. Flux's
built-in dependency check then requires the old owner to have applied the current
artifact revision, rather than accepting Ready from an earlier revision. The replacement has Orphan
deletion policy and Observe/Create/Update management policies. Those policies prevent
Workspace deletion from destroying infrastructure; HCL edits can still delete resources.

Every OpenTofu Workspace Kustomization uses a health-check expression that requires
both `Synced=True` for the Workspace's current generation and `Ready=True`. The
generation check applies to Synced; Ready has no observed-generation requirement.
This prevents Flux's generic kstatus check from treating `Synced=True` alone as Ready
when the Workspace has not reported `Ready=True`.

Keep the five legacy `tf-gitops-*` ArtifactGenerator outputs while the old
tofu-controller Terraform CRs finalize. tofu-controller resolves the CR's source before
normal finalization even when destruction is disabled, so removing an artifact early
can strand its CR. A `CLEANUP` tombstone in `generate_manifests.py` lists the retained
artifacts and the removal gate. Remove them only after all five legacy Terraform CRs
(`haku-state`, `budget-ledger`, `cpap-data`, `agentydragon-repos`, and `finance-agent`)
are absent and all five replacement Workspaces report `Ready=True` plus
current-generation `Synced=True` after PR #12109 rolls out. This artifact cleanup is a
separate follow-up; the migration does not recreate the legacy Terraform CRs.

After merging the application-root migration, verify:

- `authentik-tf` and `forgejo-gitops` reached their new revision and pruned the three old
  Terraform CRs. No old runner remains active for those roots.
- Each new Workspace reports Synced=True and Ready=True for its current generation.
  Inspect provider diagnostics for unexpected recreation, missing state, or denied access.
- Gatus OIDC login and the Alloy rotator's existing consumer remain healthy. Claude's
  existing credentials continue to authenticate through their current consumers.
- Existing Forgejo SSH-key and Route 53 Workspaces stay Ready after the provider runtime
  rollout. Their backend, source, variables and lifecycle policies are unchanged.

For the Forgejo migration also verify the haku Workspace before dependent Forgejo
Workspaces, preserve `forgejo_codex` for `forgejo-agentydragon-repos`, and check existing
repository identities and credential consumers. Do not mark the Forgejo migration PR
ready until the application-root migration's handoff has been observed. Keep broader
SSO/access, CI/bootstrap, parked roots, and roots with executable/mixed-format
dependencies for subsequent work.

## Recovery

If a replacement fails, leave the old Terraform CR absent while diagnosing. Reverting a
migration without first stopping the replacement would reintroduce two controllers for
one state. To return ownership, first pause Crossplane reconciliation and remove its
Workspace with Orphan policy, verify it no longer owns the state, then restore the old
Terraform CR. Keep the original schema and `default` workspace throughout.
