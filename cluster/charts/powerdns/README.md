# PowerDNS Helm Chart

Deploys PowerDNS authoritative DNS server (`powerdns/pdns-auth-47`).

Supports SQLite (default) or MySQL backend, ESO integration for API key from Vault,
non-root container with security contexts, and configurable PVC.

## Configuration

| Parameter                 | Description               | Default                 |
| ------------------------- | ------------------------- | ----------------------- |
| `image.repository`        | PowerDNS Docker image     | `powerdns/pdns-auth-47` |
| `image.tag`               | Image tag                 | `4.7.3`                 |
| `replicaCount`            | Number of replicas        | `1`                     |
| `powerdns.api.enabled`    | Enable PowerDNS API       | `true`                  |
| `powerdns.backend`        | Database backend          | `gsqlite3`              |
| `service.dns.type`        | DNS service type          | `LoadBalancer`          |
| `service.dns.annotations` | DNS service annotations   | `{}`                    |
| `persistence.enabled`     | Enable persistent storage | `true`                  |
| `persistence.size`        | Storage size              | `1Gi`                   |
| `externalSecret.enabled`  | Enable ESO integration    | `false`                 |
| `resources.limits.memory` | Memory limit              | `512Mi`                 |
| `resources.requests.cpu`  | CPU request               | `100m`                  |

## ESO Integration

```yaml
externalSecret:
  enabled: true
  secretStore:
    name: vault-backend
    kind: ClusterSecretStore
  vaultPath: "kv/data/powerdns"
  secretName: powerdns-api-key
```

## Troubleshooting

```bash
kubectl get pods -l app.kubernetes.io/name=powerdns
kubectl logs -l app.kubernetes.io/name=powerdns

# Test API access
kubectl port-forward svc/powerdns-api 8081:8081
curl -H "X-API-Key: $(kubectl get secret powerdns-api-key -o jsonpath='{.data.PDNS_API_KEY}' | base64 -d)" \
  http://localhost:8081/api/v1/servers
```
