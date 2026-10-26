# Crossplane Inline migration batches

## Merge sequence

1. Expand the shared cluster diagnostics role to read Crossplane objects, including
   Provider packages, revisions, runtime configs, ProviderConfigs and Workspaces.
   Grant no core Secret reads or access to the PostgreSQL state backend.
2. Migrate `gatus-sso`, `forgejo-claude`, and `alloy-otlp-bearer-token` together.
   Factor the existing Inline Workspace construction and configure Kubernetes identities.
3. Migrate the five remaining active Forgejo roots together: `haku-state`,
   `budget-ledger`, `cpap-data`, `finance-agent`, `forgejo-agentydragon-repos`.
   This batch builds on batch 2 and remains draft until its live handoff is verified.

## Handoff and verification

Each replacement uses the existing PostgreSQL backend/schema and OpenTofu `default`
workspace. No state export, import, password rotation, or repository recreation is
part of a migration. Keep native HCL resource addresses and legacy `removed` blocks.

Flux prunes each old tofu-controller Terraform CR with resource destruction disabled
before the replacement Workspace's Kustomization runs. The replacement has Orphan
deletion policy and Observe/Create/Update management policies. Those policies prevent
Workspace deletion from destroying infrastructure; HCL edits can still delete resources.

After merging batch 2, verify:

- `authentik-tf` and `forgejo-gitops` reached their new revision and pruned the three old
  Terraform CRs. No old runner remains active for those roots.
- Each new Workspace reports Synced=True and Ready=True for its current generation.
  Inspect provider diagnostics for unexpected recreation, missing state, or denied access.
- Gatus OIDC login and the Alloy rotator's existing consumer remain healthy. Claude's
  existing credentials continue to authenticate through their current consumers.
- Existing Forgejo SSH-key and Route 53 Workspaces stay Ready after the provider runtime
  rollout. Their backend, source, variables and lifecycle policies are unchanged.

For batch 3 also verify the haku Workspace before dependent Forgejo Workspaces, preserve
`forgejo_codex` for `forgejo-agentydragon-repos`, and check existing repository identities
and credential consumers. Do not mark the second migration PR ready until batch 2's
handoff has been observed. Keep broader SSO/access, CI/bootstrap, parked roots, and roots
with executable/mixed-format dependencies for subsequent work.

## Recovery

If a replacement fails, leave the old Terraform CR absent while diagnosing. Reverting a
migration without first stopping the replacement would reintroduce two controllers for
one state. To return ownership, first pause Crossplane reconciliation and remove its
Workspace with Orphan policy, verify it no longer owns the state, then restore the old
Terraform CR. Keep the original schema and `default` workspace throughout.
