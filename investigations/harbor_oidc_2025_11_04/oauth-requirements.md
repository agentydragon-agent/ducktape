# Harbor OIDC OAuth2 Requirements

## Critical Components for Successful OAuth2 Flow

### 1. Client Credentials (MUST MATCH EXACTLY)
- **Client ID**: `harbor`
- **Client Secret**: Must be identical across all systems
  - **Source of Truth**: Vault at `kv/data/harbor/oidc` 
  - **K8s Secret**: `harbor-oidc-secret` in `harbor` namespace (synced via External Secrets Operator)
  - **Authentik Provider**: OAuth2 provider with client_id=`harbor` 
  - **Harbor Database**: Stored encrypted in `properties` table with key `oidc_client_secret`

### 2. Redirect URIs (MUST BE REGISTERED)
- Primary callback: `https://registry.k3s.agentydragon.com/c/oidc/callback`
- Login endpoint: `https://registry.k3s.agentydragon.com/c/oidc/login`
- Must be registered in Authentik OAuth2 provider with `matching_mode: strict`

### 3. OIDC Configuration in Harbor
Required settings in Harbor's configuration:
- `auth_mode`: `oidc_auth`
- `oidc_name`: `Authentik`
- `oidc_endpoint`: `https://auth.k3s.agentydragon.com/application/o/harbor/`
- `oidc_client_id`: `harbor`
- `oidc_client_secret`: (encrypted in DB)
- `oidc_groups_claim`: `groups`
- `oidc_admin_group`: `harbor-admins`
- `oidc_scope`: `openid,profile,email,groups`
- `oidc_user_claim`: `preferred_username`
- `oidc_verify_cert`: `true`
- `oidc_auto_onboard`: `true`

### 4. Authentik Configuration
- **OAuth2 Provider**: Named `harbor-oidc` with:
  - Grant type: `authorization-code`
  - Client type: `confidential`
  - Issuer mode: `per_provider`
  - Sub mode: `hashed_user_id`
  - Include claims in ID token: `true`
- **Application**: Slug `harbor` linked to provider
- **Scope Mappings**: Must include custom `preferred_username` claim
- **Group**: `harbor-admins` for admin access

### 5. Network Connectivity
- Harbor must reach Authentik at `https://auth.k3s.agentydragon.com`
- Browser must reach both Harbor and Authentik
- TLS certificates must be valid or verification disabled

### 6. Token Exchange Requirements
- Harbor sends authorization code to Authentik's token endpoint
- Must include proper client authentication (client_id + client_secret)
- Authentik validates client credentials before issuing tokens

## Current Testing Gaps

### ❌ Not Explicitly Checked by Our Protocol:
1. **Secret Decryption in Harbor**: We check the encrypted value exists but don't verify it decrypts to the correct value
2. **TLS Certificate Validation**: Not testing if Harbor can actually validate Authentik's certificate
3. **Network Connectivity Between Services**: Not explicitly testing if Harbor pod can reach Authentik
4. **Token Signature Verification**: Not checking if Harbor can validate JWT signatures from Authentik
5. **Scope Permissions**: Not verifying all requested scopes are actually granted
6. **Group Claims Processing**: Not testing if groups are properly passed through

### ✅ Currently Checked:
1. User creation in Authentik
2. OAuth2 authorization flow (browser perspective)
3. Authorization code generation
4. Redirect URI matching
5. Basic token exchange attempt
6. Harbor API configuration values
7. Database secret presence (but not decryption)

## Synchronization Process

### Declarative Configuration Flow:
1. **Vault** stores the actual secret values
2. **External Secrets Operator** syncs from Vault to K8s Secret
3. **Harbor Setup Helm Chart** runs a job that:
   - Sets admin password in database
   - Configures OIDC via Harbor API
   - Harbor encrypts and stores the secret
4. **Authentik Blueprint** configures OAuth2 provider using environment variable from K8s Secret

### Manual Intervention Required When:
- Secrets change in Vault (must re-run Harbor setup: `helm upgrade harbor-setup k8s/helm/harbor-setup/`)
- Blueprint changes (Authentik auto-reloads blueprints)
- Network/DNS changes affecting service discovery

## Common Failure Points

1. **Client Secret Mismatch**: Most common issue - Harbor's encrypted secret doesn't match Authentik's
2. **Redirect URI Mismatch**: Exact string matching required, including trailing slashes
3. **Expired/Invalid Authorization Code**: Codes are single-use and time-limited
4. **Network Issues**: Services can't reach each other (DNS, firewall, ingress)
5. **Certificate Issues**: Self-signed or invalid certificates when `oidc_verify_cert: true`
6. **Missing Scopes/Claims**: Required claims not included in token response

## Fix Procedure

When OAuth fails with "invalid_client":
1. Check K8s secret: `kubectl get secret harbor-oidc-secret -n harbor -o jsonpath='{.data.OIDC_CLIENT_SECRET}' | base64 -d`
2. Check Authentik: `kubectl exec -n authentik deployment/authentik-server -- ak shell -c "from authentik.providers.oauth2.models import OAuth2Provider; p = OAuth2Provider.objects.filter(client_id='harbor').first(); print(p.client_secret)"`
3. If mismatch, re-run Harbor setup: `helm upgrade harbor-setup k8s/helm/harbor-setup/`
4. Verify Harbor received update: Check `properties` table for new encrypted value
5. Test OAuth flow again