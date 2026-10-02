# Parked standalone Codex workspaces

The generator stays in `cluster/cdk8s/agent_workspaces.py`; its reproducible
namespace, quota, Codex SandboxTemplate, warm pool, and janitor are rendered here.
The last image pin is preserved in `image-pins/`. Flux no longer deploys this tree
or advances that pin. The workspace image and `devinfra/ws` client are retained.

## Retirement

The existing `agent-workspaces-app` Flux owner temporarily reconciles the empty
`cluster/generated/retired/agent-workspaces` directory, pruning its namespace and
warm pool. Do not merely suspend that owner: suspension leaves existing Pods alive.
It deliberately does not depend on a successful sandbox-controller upgrade.

Read-only preflight on 2026-10-02 at 21:18 UTC found no SandboxClaims;
`codex-xqxds` was an unclaimed `codex` warm-pool Sandbox. Its 10 GiB PVC,
`workspace-codex-xqxds`, was owned by that Sandbox. **The operator explicitly
approved deleting this workspace's data.** `shutdownPolicy: Retain` does not
protect a PVC from owner/namespace deletion. Other namespaces and their PVCs are
not part of this retirement.

After merging, verify the namespace, Sandbox, Pod and PVC are gone and the Flux
owner is Ready with an empty inventory. Only then remove the temporary empty owner
and directory in a follow-up. Do not force-remove finalizers if deletion stalls.
The shared `agent-sandbox-system` controller remains active for Agentplane.

The canonical LiteLLM key in `tf/gitops/litellm-keys` is deliberately retained for
revival; its namespace reflection becomes unused. Consider retiring that key
separately after confirming no surviving consumers. This change does not claim
that backing storage has been securely erased.

## Revival

Restore the call to `agent_workspaces.agent_workspaces_app` in manifest generation,
remove the retirement call, and move this output/pin back under the active roots.
Restore `agent-workspaces` in the Forgejo image SecretStore consumer list and
`agent-workspace` in the image-automation roster. Regenerate and validate before
merging; reviving the namespace creates a fresh warm workspace, not the deleted data.
