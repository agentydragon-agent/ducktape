# Gitea with Authentik OAuth2 Integration

This directory contains the complete setup for Gitea with automated Authentik OAuth2 integration using Reflector for secret sharing.

## Deployment Steps

### 1. Generate OAuth2 Credentials (First Time Only)

Generate a sealed secret with OAuth2 credentials:

```bash
# Generate secure OAuth2 credentials
OAUTH_CLIENT_ID="gitea-oauth2-client"
OAUTH_SECRET=$(openssl rand -hex 32)

# Create secret with Reflector annotations for cross-namespace sharing
kubectl create secret generic gitea-oauth-shared \
  --namespace=gitea \
  --from-literal=client_id="${OAUTH_CLIENT_ID}" \
  --from-literal=client_secret="${OAUTH_SECRET}" \
  --from-literal=GITEA_CLIENT_SECRET="${OAUTH_SECRET}" \
  --dry-run=client -o yaml | \
yq '.metadata.annotations["reflector.v1.k8s.emberstack.com/reflection-allowed"] = "true" |
    .metadata.annotations["reflector.v1.k8s.emberstack.com/reflection-allowed-namespaces"] = "authentik"' | \
kubeseal --format yaml > gitea-oauth-sealed.yaml

echo "Save these values:"
echo "  Client ID: ${OAUTH_CLIENT_ID}"
echo "  Client Secret: ${OAUTH_SECRET}"
```

### 2. Deploy Components

```bash
# Install Reflector for secret sharing (if not already installed)
kubectl apply -f reflector.yaml
kubectl wait --for=condition=available --timeout=60s deployment/reflector -n kube-system

# Create namespace
kubectl apply -f namespace.yaml

# Deploy sealed secret
kubectl apply -f gitea-oauth-sealed.yaml

# Wait for secret to be unsealed and reflected
until kubectl get secret gitea-oauth-shared -n authentik >/dev/null 2>&1; do
  echo "Waiting for secret to be reflected to authentik namespace..."
  sleep 2
done

# Update Authentik to include Gitea blueprint
# The blueprint is already integrated in k8s/helm/authentik/
cd ../helm/authentik
helm dependency update
helm upgrade authentik . -n authentik --reuse-values
cd -

# Add Gitea Helm repository
helm repo add gitea-charts https://dl.gitea.io/charts/
helm repo update

# Install Gitea
helm upgrade --install gitea gitea-charts/gitea \
  --namespace gitea \
  --values values.yaml \
  --wait \
  --timeout 10m

# Configure OAuth2 in Gitea
kubectl apply -f gitea-oauth-setup-job.yaml

# Get admin password (if needed for emergency access)
echo "Admin password: $(kubectl get secret -n gitea gitea-admin-secret -o jsonpath='{.data.password}' | base64 -d)"
```

## Architecture

### Components

1. **Gitea** - Private Git repository server at `https://git.k3s.agentydragon.com`
2. **Authentik Integration** - OAuth2/OpenID Connect for SSO
3. **SealedSecrets** - Secure credential storage in git

### Automated Setup

The deployment automatically:
1. Creates OAuth2 provider in Authentik via blueprints
2. Configures Gitea with OAuth2 authentication
3. Sets up groups: `gitea-users` and `gitea-admins`
4. Shares credentials securely between services

### Files

- `namespace.yaml` - Gitea namespace definition
- `values.yaml` - Helm values for Gitea deployment
- `gitea-oauth-setup-job.yaml` - Post-install OAuth2 configuration job
- `reflector.yaml` - Kubernetes Reflector for cross-namespace secret sharing
- `gitea-oauth-sealed.yaml` - Sealed secret with OAuth2 credentials (generated)
- **Authentik blueprint**: Integrated in `../helm/authentik/templates/gitea-provider-blueprint.yaml`

## Access

After deployment:
- **URL**: https://git.k3s.agentydragon.com
- **Admin**: agentydragon (password shown after deploy)
- **SSO**: Click "Sign in with Authentik"

## Using Private Repos in Home-Manager

Once deployed, create a private repository for binaries:

1. Create repo in Gitea UI: `private-binaries`

2. Add as git submodule:
   ```bash
   cd ~/code/ducktape
   git submodule add https://git.k3s.agentydragon.com/agentydragon/private-binaries.git private
   ```

3. Reference in home-manager:
   ```nix
   home.file."bin/google-drive" = {
     source = ./private/google-drive/drive;
     executable = true;
   };
   ```

## Troubleshooting

### Check OAuth2 Setup
```bash
kubectl logs -n gitea job/gitea-oauth-setup
```

### Get Admin Password
```bash
kubectl get secret -n gitea gitea-admin-secret \
  -o jsonpath='{.data.password}' | base64 -d
```

### Verify Sealed Secrets
```bash
kubectl get secrets -n gitea gitea-oauth-shared
kubectl get secrets -n authentik gitea-oauth-shared
```

### Check Authentik Blueprint
```bash
kubectl logs -n authentik deployment/authentik-worker | grep -i gitea
```