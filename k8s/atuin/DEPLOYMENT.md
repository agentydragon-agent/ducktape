# Atuin Server Deployment Configuration

## Access Information

**Atuin Server URL**: `http://10.0.200.200:30888`

Alternative URLs (any k3s node):
- `http://10.0.200.201:30888` (k3s-worker)
- `http://<node-tailscale-hostname>:30888`

## Security Configuration

⚠️ **IMPORTANT**: This deployment has **OPEN REGISTRATION ENABLED**
- Anyone with access to your Tailscale network can create an account
- To disable open registration, edit `atuin-configmap.yaml` and set `open_registration = false`

## Client Configuration

### Register a new account:
```bash
atuin register -u <username> -p <password> -e <email> \
  --server http://10.0.200.200:30888
```

### Login to existing account:
```bash
atuin login -u <username> -p <password> \
  --server http://10.0.200.200:30888
```

### Configure Atuin client permanently:
Add to `~/.config/atuin/config.toml`:
```toml
sync_address = "http://10.0.200.200:30888"
```

### Start syncing:
```bash
atuin sync
```

## Network Architecture

- **External Access**: Via NodePort 30888 on any k3s node (through Tailscale)
- **Internal Services**:
  - ClusterIP: `atuin-server:8888` (for pod-to-pod communication)
  - PostgreSQL: `postgres:5432` (internal only)
- **Security**: Only accessible through Tailscale network, not exposed to public internet

## Database

- PostgreSQL 14 with 1GB persistent storage
- Data stored at: `/var/lib/k3s/storage/` on k3s nodes
- Database name: `atuin`
- Database user: `atuin`

## Maintenance

### Check service status:
```bash
kubectl get all -l app=atuin
kubectl logs deployment/atuin-server
```

### Disable open registration:
1. Edit ConfigMap: `kubectl edit configmap atuin-config`
2. Change `open_registration = false`
3. Restart: `kubectl rollout restart deployment/atuin-server`

### Update deployment:
```bash
cd ~/code/ducktape/k8s/atuin
kubectl apply -f .
```