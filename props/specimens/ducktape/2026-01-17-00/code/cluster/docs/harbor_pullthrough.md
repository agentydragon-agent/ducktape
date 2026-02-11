# Harbor Pull-Through Cache Strategy

## Summary

Use Harbor as a pull-through cache to avoid upstream registry rate limits and speed up image pulls.

**Recommended Approach**: Talos containerd registry mirrors - transparent, zero manifest changes, built-in fallback.

## Solution: Talos Registry Mirrors

Configure containerd at node level to redirect image pulls through Harbor with upstream fallback:

```yaml
# terraform/01-infrastructure/talos.tf
machine:
  registries:
    mirrors:
      docker.io:
        endpoints:
          - https://registry.test-cluster.agentydragon.com/docker-hub-proxy
          - https://registry-1.docker.io # Fallback
      ghcr.io:
        endpoints:
          - https://registry.test-cluster.agentydragon.com/ghcr-proxy
          - https://ghcr.io
```

**Why this works for turnkey bootstrap**: Fallback endpoints handle Harbor not existing yet. First bootstrap
uses upstream, Harbor deploys, subsequent pulls use cache automatically.

## Alternatives Considered

| Option                   | Verdict         | Reason                                            |
| ------------------------ | --------------- | ------------------------------------------------- |
| Talos Registry Mirrors   | ✅ **Selected** | Transparent, native containerd, built-in fallback |
| Kyverno Image Mutation   | ⚠️ Viable       | Adds dependency, no fallback, observability gap   |
| Custom Admission Webhook | ❌ Rejected     | Over-engineered, reinvents wheel                  |
| ImagePolicyWebhook       | ❌ Rejected     | Complex kube-apiserver config, Talos limitation   |

## Harbor Configuration

**Proxy cache doesn't require SSO** - only Harbor UI login needs OIDC. Pull-through projects are public
with anonymous pull.

### Setup (one-time, persists in Harbor PostgreSQL)

1. Login to Harbor UI as admin
2. Create registry endpoints (Docker Hub, GHCR, Quay, registry.k8s.io)
3. Create proxy cache projects as PUBLIC with anonymous pull
4. Optional: Automate with Harbor Terraform provider

### Declarative Option (terraform/03-configuration)

```hcl
resource "harbor_registry" "dockerhub" {
  provider_name = "docker-hub"
  name          = "dockerhub"
  endpoint_url  = "https://hub.docker.com"
}

resource "harbor_project" "dockerhub_proxy" {
  name        = "docker-hub-proxy"
  public      = true
  registry_id = harbor_registry.dockerhub.id
}
```

## Benefits

- **Rate limit mitigation**: ~80% reduction in upstream pulls
- **Zero manifest changes**: All existing Helm charts work unchanged
- **Faster bootstraps**: Cached images served locally (~2x speedup)
- **Offline capability**: Cached images available during upstream outages
