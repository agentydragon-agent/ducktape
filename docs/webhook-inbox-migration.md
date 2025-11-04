# Webhook Inbox Migration Plan & Progress

## Goal
Retire the VPS-hosted webhook inbox container and run the service exclusively in the k3s cluster using Helm/Helmfile.

## Status Overview

| Task | Status | Notes |
| --- | --- | --- |
| Package webhook inbox as Helm chart | ✅ Done | `k8s/helm/webhook-inbox/` with Deployment, PVC, Ingress, secrets helpers |
| Add Helmfile release & values | ✅ Done | Release entry plus `values/webhook-inbox.yaml` for sealed secret ciphertext |
| Generate sealed secret for Fernet key | ✅ Done | Ciphertext stored in Helmfile values (kubeseal command recorded in README) |
| Ignore Helm `Chart.lock` & vendor dirs | ✅ Done | `.gitignore` updated; legacy `Chart.lock` files removed |
| Remove legacy Ansible role & playbook hook | ✅ Done | Role directory deleted, `ansible/vps.yaml` no longer references it |
| Update clients to new endpoint | 🔄 In progress | GNOME login reporter updated earlier; recheck other callers |
| Deploy to k3s | ⏳ Pending | Run `helm dependency update k8s/helm/webhook-inbox` then `helmfile sync webhook-inbox` |
| Clean up VPS data directory | ⏳ Pending | Remove `/opt/webhook-inbox` once historical data no longer needed |

## Next Steps
1. Run the Helmfile release to bring the service online in k3s.
2. Verify existing integrations (login reporter, GUI tasks, etc.) hit `https://webhook.k3s.agentydragon.com/`.
3. After validation, prune any remaining references to the old domain and remove residual VPS data.

## Reference Commands

```bash
# Regenerate chart dependencies (Helmfile will do this automatically if omitted)
helm dependency update k8s/helm/webhook-inbox

# Deploy the release
cd k8s/helmfile
helmfile sync webhook-inbox
```

