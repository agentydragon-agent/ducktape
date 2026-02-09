# PowerDNS Helm Chart

A modern Helm chart for deploying PowerDNS authoritative DNS server with proper secret management.

## Features

- ✅ **Official PowerDNS Docker Image**: Uses `powerdns/pdns-auth-47`
- ✅ **External Secret Operator Integration**: Automatic API key management from Vault
- ✅ **Flexible Backend Support**: SQLite (default), MySQL, PostgreSQL
- ✅ **LoadBalancer Ready**: MetalLB integration for DNS VIP
- ✅ **Security Hardened**: Non-root container, proper security contexts
- ✅ **Health Checks**: Liveness and readiness probes
- ✅ **Persistent Storage**: Configurable PVC for data persistence

## Quick Start

```bash
# Install with default values (SQLite backend)
helm install powerdns ./powerdns-chart

# Install with MetalLB LoadBalancer
helm install powerdns ./powerdns-chart \
  --set service.dns.annotations."metallb\.universe\.tf/address-pool"=dns-pool \
  --set service.dns.annotations."metallb\.universe\.tf/loadBalancerIPs"=10.0.3.3

# Install with External Secret Operator
helm install powerdns ./powerdns-chart \
  --set externalSecret.enabled=true \
  --set externalSecret.secretStore.name=vault-backend \
  --set externalSecret.vaultPath="kv/data/powerdns"
```

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

## External Secrets Integration

To use Vault-managed API keys:

1. **Enable External Secret**:

```yaml
externalSecret:
  enabled: true
  secretStore:
    name: vault-backend
    kind: ClusterSecretStore
  vaultPath: "kv/data/powerdns"
  secretName: powerdns-api-key
```

1. **Create Vault Secret**:

```bash
vault kv put kv/powerdns apikey="$(openssl rand -base64 32)"
```

## Backend Configuration

### SQLite (Default)

```yaml
powerdns:
  backend: "gsqlite3"
  sqlite:
    database: "/var/lib/powerdns/pdns.sqlite3"
```

### MySQL

```yaml
powerdns:
  backend: "gmysql"
  config:
    gmysql-host: "mysql.default.svc.cluster.local"
    gmysql-user: "powerdns"
    gmysql-password: "password"
    gmysql-dbname: "powerdns"
```

## Integration Examples

### With external-dns

```yaml
# external-dns configuration
provider: powerdns
powerdns:
  server: "http://powerdns-api.dns-system:8081"
  api-key: "from-secret"
```

### With cert-manager webhook

```yaml
# cert-manager webhook configuration
groupName: acme.zacharyseguin.ca
solverName: pdns
config:
  host: "http://powerdns-api.dns-system:8081"
  apiKeySecretRef:
    name: powerdns-api-key
    key: PDNS_API_KEY
```

## Security

- Runs as non-root user (UID 953)
- API key stored in Kubernetes Secret
- Web server restricted to private networks by default
- Security contexts applied to pods and containers

## Troubleshooting

### Check pod status

```bash
kubectl get pods -l app.kubernetes.io/name=powerdns
kubectl logs -l app.kubernetes.io/name=powerdns
```

### Test DNS resolution

```bash
export DNS_IP=$(kubectl get svc powerdns-dns -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
dig @$DNS_IP test.example.com
```

### Check API access

```bash
kubectl port-forward svc/powerdns-api 8081:8081
curl -H "X-API-Key: $(kubectl get secret powerdns-api-key -o jsonpath='{.data.PDNS_API_KEY}' | base64 -d)" \
  http://localhost:8081/api/v1/servers
```
