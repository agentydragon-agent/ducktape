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

### 1b. Generate Ember Gitea password (rotate as needed)

```bash
EMBER_PASSWORD=$(openssl rand -base64 24)

kubectl create secret generic gitea-ember-credentials \
  --namespace=gitea \
  --from-literal=ember-password="${EMBER_PASSWORD}" \
  --dry-run=client -o yaml | kubeseal --format yaml > gitea-ember-sealed.yaml

echo "Ember Gitea password saved to sealed secret"
```

### 2. Deploy Components

```bash
# Install Reflector for secret sharing (if not already installed)
kubectl apply -f reflector.yaml
kubectl wait --for=condition=available --timeout=60s deployment/reflector -n kube-system

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

# Apply jobs and sealed secrets (OAuth setup + Ember PAT)
kubectl apply -k .

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
5. Boots an `ember-bot` service account with a personal access token published to the `ember` namespace

### Files

- `namespace.yaml` - Gitea namespace definition
- `ember-rbac.yaml` - ServiceAccount + Role/Binding for writing Ember secrets
- `values.yaml` - Helm values for Gitea deployment
- `gitea-oauth-setup-job.yaml` - Post-install OAuth2 configuration job
- `gitea-ember-token-job.yaml` - Bootstrap job that drives the Gitea `admin user` CLI to mint Ember's PAT
- `reflector.yaml` - Kubernetes Reflector for cross-namespace secret sharing
- `gitea-oauth-sealed.yaml` - Sealed secret with OAuth2 credentials (generated)
- `gitea-ember-sealed.yaml` - Sealed secret containing the Ember Gitea password
- `kustomization.yaml` - Bundles manifests and mounts the Python bootstrap script
- `scripts/ember_pat.py` - Python helper that orchestrates the CLI token generation and secret sync
- **Authentik blueprint**: Integrated in `../helm/authentik/templates/gitea-provider-blueprint.yaml`

## Access

After deployment:
- Ember's PAT lives in secret `gitea-ember-token` in the `ember` namespace with fields `username`, `token`, and `token_name`.
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
kubectl get secrets -n gitea gitea-ember-credentials
kubectl get secrets -n ember gitea-ember-token
```

### Check Authentik Blueprint
```bash
kubectl logs -n authentik deployment/authentik-worker | grep -i gitea
```