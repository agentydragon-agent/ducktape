# K8s Infrastructure

## Components

### Registry
Container registry for in-cluster Docker images. Accessible at:
- `registry.k3s.local` (via Traefik ingress with TLS)

### cert-manager & TLS Certificates

The cluster uses cert-manager for automatic TLS certificate management with a self-signed homelab CA.

#### Setup
1. **cert-manager v1.13.0** is installed in the `cert-manager` namespace
2. **Homelab CA** - A 10-year self-signed CA certificate for issuing all cluster certificates
3. **ClusterIssuers**:
   - `selfsigned-cluster-issuer` - Bootstrap issuer for creating the CA
   - `homelab-ca-issuer` - Issues certificates signed by the homelab CA

#### Using TLS for Services

To enable HTTPS for any ingress, add these annotations:
```yaml
metadata:
  annotations:
    cert-manager.io/cluster-issuer: "homelab-ca-issuer"
spec:
  tls:
  - hosts:
    - your-service.k3s.local
    secretName: your-service-tls
```

#### Trust the CA on Docker Hosts

To enable Docker to push/pull via HTTPS:
```bash
# Extract the CA certificate
kubectl get secret homelab-ca-secret -n cert-manager -o jsonpath='{.data.ca\.crt}' | base64 -d > homelab-ca.crt

# Install on each Docker host
sudo cp homelab-ca.crt /usr/local/share/ca-certificates/
sudo update-ca-certificates
sudo systemctl restart docker
```

#### Docker Registry Usage

After CA trust is configured:
```bash
# Build and tag
docker build -t registry.k3s.local/myapp:latest .

# Push via HTTPS
docker push registry.k3s.local/myapp:latest

# Use in k8s deployments
image: registry.k3s.local/myapp:latest
```

### Observability
- OpenAI probe for API monitoring
- TimescaleDB for metrics storage
- (Previously: Loki, Grafana, Promtail - archived)

### Infrastructure
- MetalLB for LoadBalancer services
- Traefik as ingress controller (LoadBalancer IP: 10.0.200.100)

All high-level workloads have first-party Helm charts (`k8s/helm/`) and are orchestrated together via Helmfile (`k8s/helmfile/helmfile.yaml`). Use `helmfile apply` from that directory to roll the full stack once secrets and container images are in place.

## DNS Configuration

All `*.k3s.local` domains resolve to the Traefik LoadBalancer at 10.0.200.100 (configured via dnsmasq on the host).
