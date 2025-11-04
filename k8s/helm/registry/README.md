# Harbor Container Registry

Harbor container registry with Authentik OIDC integration for secure, authenticated access.

## Features

- **Harbor v2.12.0** - Enterprise-grade container registry
- **Authentik OIDC Integration** - Single Sign-On authentication
- **Vulnerability Scanning** - Built-in Trivy scanner
- **Web UI** - Full-featured registry management interface
- **Project-based Access Control** - Fine-grained permissions
- **Metrics & Monitoring** - Built-in Prometheus metrics

## Deployment

Harbor is deployed via Helmfile, not directly through Helm:

```bash
cd k8s/helmfile
helmfile apply --selector name=harbor
```

## Access

### Web UI Access
- **URL**: https://registry.k3s.agentydragon.com
- **Authentication**: Click "LOGIN VIA OIDC" → authenticate via Authentik
- **Admin Access**: Username `admin`, Password `HarborAdmin123!` (disable after OIDC setup)

### Docker CLI Access

Docker CLI requires traditional username/password authentication:

#### Option 1: Admin Credentials (Temporary)
```bash
docker login registry.k3s.agentydragon.com
# Username: admin
# Password: HarborAdmin123!
```

#### Option 2: CLI Secret (Recommended)
1. Log in to Harbor web UI via OIDC
2. Go to **User Profile** → **User Settings** → **CLI secret**
3. Generate a CLI secret
4. Use your Authentik username + generated secret:
```bash
docker login registry.k3s.agentydragon.com
# Username: <your-authentik-username>
# Password: <generated-cli-secret>
```

#### Option 3: Robot Accounts (Best for Automation)
1. Create a project in Harbor web UI
2. Go to **Projects** → **Your Project** → **Robot Accounts**
3. Create robot account with appropriate permissions
4. Use robot credentials:
```bash
docker login registry.k3s.agentydragon.com
# Username: robot$<robot-name>
# Password: <robot-token>
```

## Usage Examples

```bash
# Tag and push an image
docker tag my-app:latest registry.k3s.agentydragon.com/my-project/my-app:v1.0
docker push registry.k3s.agentydragon.com/my-project/my-app:v1.0

# Pull an image
docker pull registry.k3s.agentydragon.com/my-project/my-app:v1.0
```

## Configuration

Harbor configuration is managed through:
- **Helmfile**: `/k8s/helmfile/helmfile.yaml`
- **Values**: `/k8s/helmfile/values/harbor.yaml`
- **Authentik Blueprint**: `/k8s/helm/authentik/blueprints/harbor.yaml`

## Storage

Currently using `local-path` storage class for all Harbor components:
- **Registry**: 50GB
- **Database**: 1GB (PostgreSQL)
- **Redis**: 1GB
- **Trivy**: 5GB (vulnerability database)
- **JobService**: 1GB (logs)

## Security Features

- **TLS Encryption** - All traffic encrypted via cert-manager certificates
- **OIDC Authentication** - Integrated with Authentik SSO
- **Vulnerability Scanning** - Automatic scanning with Trivy
- **Access Control** - Project-based permissions and RBAC
- **Audit Logging** - Complete audit trail of registry actions

## Troubleshooting

### Web UI Not Accessible (VPS nginx proxy issue)
**Known Issue**: The VPS nginx proxy configuration needs to be updated to point to the correct Traefik NodePort.

Current nginx config points to `http://k3s-master:80`, but Traefik runs on NodePorts:
- HTTP: 30413
- HTTPS: 32253

**Workaround - Direct cluster access:**
```bash
# Use port-forwarding to bypass nginx proxy
kubectl port-forward -n harbor svc/harbor-portal 8080:80
# Access: http://localhost:8080
```

**Fix**: Update `/ansible/nginx-sites/k3s.agentydragon.com.j2` line 37:
```nginx
# Change from:
proxy_pass http://k3s-master;
# Change to:
proxy_pass http://k3s-master:30413;  # or use LoadBalancer IP
```

### Check Harbor Status
```bash
kubectl get pods -n harbor
kubectl get pvc -n harbor
kubectl logs -n harbor harbor-core-<pod-id>
```

### Docker Login Issues
- **External access**: Requires VPS nginx configuration update (see above)
- **Internal cluster access**: Use port-forwarding or direct cluster access
- Ensure you're using the correct authentication method (CLI secret vs admin vs robot)
- Verify Harbor is accessible internally: `kubectl exec -n harbor harbor-core-<pod> -- curl -s http://127.0.0.1:8080/api/v2.0/ping`

## Migration Notes

- **Replaced Docker Registry** - Harbor provides superior functionality with native OIDC support
- **Legacy Registry Data** - Not automatically migrated; re-push images as needed
- **Authentication** - No more complex docker_auth setup; Harbor handles OIDC natively
- **Declarative Management** - Fully managed through Helmfile for consistency