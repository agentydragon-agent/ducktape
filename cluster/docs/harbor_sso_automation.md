# Harbor SSO Automation Options

## Research Summary

This document evaluates different approaches for configuring Harbor container registry with Authentik OIDC
authentication in a declarative, GitOps-friendly manner.

## Options Evaluated

### 1. Harbor Terraform Provider (SELECTED)

**Source**: [goharbor/harbor](https://registry.terraform.io/providers/goharbor/harbor/latest/docs)
**Version**: 3.11.2

**Description**: Official Terraform provider from Harbor project that manages Harbor resources via the Harbor API.

**Key Resources**:

- `harbor_config_auth` - Configure authentication methods including OIDC
- `harbor_project` - Manage Harbor projects
- `harbor_robot_account` - Manage robot accounts
- `harbor_user` - Manage users
- `harbor_retention_policy` - Configure image retention policies

**OIDC Configuration Example**:

```hcl
resource "harbor_config_auth" "oidc" {
  auth_mode            = "oidc_auth"
  oidc_name            = "authentik"
  oidc_endpoint        = "https://auth.test-cluster.agentydragon.com/application/o/harbor/"
  oidc_client_id       = "harbor"
  oidc_client_secret   = var.client_secret
  oidc_scope           = "openid,email,profile"
  oidc_verify_cert     = true
  oidc_auto_onboard    = true
  oidc_user_claim      = "preferred_username"
  oidc_groups_claim    = "groups"
  oidc_admin_group     = "harbor-admins"
}
```

**Pros**:

- Official provider maintained by Harbor project
- Declarative configuration as code
- Integrates with existing Terraform/GitOps workflow
- Supports OIDC configuration via `harbor_config_auth` resource
- Can manage other Harbor resources (projects, users, retention policies)
- Well-documented with examples
- Active development (latest release 3.11.2)

**Cons**:

- Requires Harbor admin credentials (bootstrap problem)
- No native Kubernetes CRD integration
- Requires tofu-controller for GitOps deployment

**Integration Pattern**:

1. Deploy Harbor via Helm (already done)
2. Generate OAuth client secret via ESO Password generator (already done)
3. Configure Authentik OAuth provider via Terraform (already done)
4. Configure Harbor OIDC settings via Terraform provider (to be implemented)

**Selected Reason**: Best fit for declarative configuration with existing Terraform-based SSO workflow.
Aligns with how Gitea, Matrix, Vault SSO are configured.

---

### 2. Harbor Helm Chart Built-in OIDC Config

**Source**: [goharbor/harbor-helm](https://github.com/goharbor/harbor-helm)

**Description**: Harbor Helm chart does not support OIDC configuration directly via values.yaml.
Authentication settings must be configured post-deployment via API or UI.

**Helm Values Investigation**:
The Harbor Helm chart only exposes basic authentication settings:

- `harborAdminPassword` - Admin password
- `existingSecretAdminPassword` - Reference to existing secret for admin password

**OIDC Configuration**: Not supported in Helm chart values. Must be done post-deployment.

**Pros**:

- None for OIDC configuration (feature doesn't exist)

**Cons**:

- No declarative OIDC configuration support in Helm chart
- Requires post-deployment API calls or UI configuration
- Not GitOps-friendly for authentication settings

**Conclusion**: Not viable for declarative OIDC setup.

---

### 3. Harbormaster

**Investigation**: Searched for "harbormaster Harbor registry automation tool"

**Findings**:

- **harbormaster.io** exists but is a **general workflow automation platform**, NOT Harbor-specific
- "Harbormaster" terminology comes from nautical/shipping industry (harbor master = port authority)
- No Harbor-specific tool called "harbormaster" exists
- The search result was a false positive due to similar naming

**Conclusion**: No Harbor-specific tool called "harbormaster" exists. The term was likely a misunderstanding
or confusion with the general workflow automation platform.

---

### 4. Harbor CLI

**Source**: [goharbor/harbor-cli](https://github.com/goharbor/harbor-cli)

**Description**: Official command-line interface for Harbor registry operations. Provides a user-friendly
alternative to the WebUI for scripting and automation.

**Capabilities**:

- Project management (create, list, delete)
- Repository operations
- User management
- Registry operations
- Artifact management

**OIDC Configuration**: Unknown - documentation doesn't clearly indicate OIDC configuration support.

**Pros**:

- Official Harbor project tool
- Good for scripting and CI/CD pipelines
- Better UX than raw API calls

**Cons**:

- Imperative rather than declarative
- Not GitOps-native (requires custom Job/CronJob wrapper)
- Unknown OIDC configuration support
- Less mature than Terraform provider

**Conclusion**: Useful for operational tasks but not ideal for declarative GitOps configuration.

---

### 5. Harbor API Direct Automation

**Source**: [Harbor API Documentation](https://goharbor.io/docs/latest/build-customize-contribute/configure-swagger/)

**Description**: Harbor provides a comprehensive REST API that can be used directly for automation.

**OIDC Configuration Endpoint**: `PUT /api/v2.0/configurations`

**Example API Call**:

```bash
curl -X PUT "https://harbor.example.com/api/v2.0/configurations" \
  -H "Authorization: Basic $(echo -n 'admin:password' | base64)" \
  -H "Content-Type: application/json" \
  -d '{
    "auth_mode": "oidc_auth",
    "oidc_name": "authentik",
    "oidc_endpoint": "https://auth.example.com/application/o/harbor/",
    "oidc_client_id": "harbor",
    "oidc_client_secret": "secret",
    "oidc_scope": "openid,email,profile",
    "oidc_verify_cert": true,
    "oidc_auto_onboard": true
  }'
```

**Pros**:

- Complete control over Harbor configuration
- No additional dependencies
- Can be wrapped in Kubernetes Job for declarative deployment

**Cons**:

- Imperative rather than declarative
- Requires custom wrapper code
- No drift detection
- More maintenance than Terraform provider
- Less readable than Terraform HCL

**Conclusion**: Viable but more work than Terraform provider. Better to use higher-level abstraction.

---

### 6. Harbor Operator (Does Not Exist)

**Investigation**: Searched for Harbor Kubernetes operators.

**Findings**:

- No official Harbor Operator exists from the Harbor project
- Some community attempts but none are mature or widely adopted
- Harbor focuses on Helm chart + API/CLI for Kubernetes deployments

**Conclusion**: Not available. Harbor project does not provide a Kubernetes operator.

---

## Implementation Architecture

### Selected Approach: Harbor Terraform Provider

**Components**:

1. **Authentik OAuth Provider** (already configured)
   - Location: `terraform/authentik-blueprint/harbor/`
   - Creates OAuth2 application in Authentik
   - Generates client_id: `harbor`
   - Uses ESO-generated client_secret

2. **Harbor OIDC Configuration** (to be implemented)
   - Location: `terraform/03-configuration/harbor-sso.tf`
   - Uses `harbor_config_auth` resource
   - Configures Harbor to use Authentik OIDC
   - Sets up auto-onboarding and group mapping

3. **Secret Management**
   - OAuth client secret: Generated via ESO Password generator
   - Harbor admin password: Generated via ESO Password generator
   - Both reflected to flux-system namespace for tofu-controller access

### Deployment Flow

```text
┌─────────────────────────────────────────────────────────────┐
│ 1. ESO Password Generator                                   │
│    Generates OAuth client secret (32 chars)                 │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│ 2. Kubernetes Secret (harbor-oauth-client-secret)          │
│    Reflected to flux-system namespace                       │
└────────────────────┬────────────────────────────────────────┘
                     │
        ┌────────────┴────────────┐
        │                         │
        ▼                         ▼
┌──────────────────┐    ┌────────────────────────────┐
│ 3a. Authentik    │    │ 3b. Harbor OIDC Config     │
│     Provider TF  │    │     (03-configuration)     │
│     (tofu)       │    │     (terraform apply)      │
│                  │    │                            │
│ - Creates OAuth2 │    │ - Calls Harbor API         │
│   app in         │    │ - Configures OIDC          │
│   Authentik      │    │ - Sets auth_mode           │
│ - Uses client    │    │ - Enables auto-onboard     │
│   secret         │    │                            │
└──────────────────┘    └────────────────────────────┘
```

### Configuration Parameters

| Parameter | Value | Source |
| --------- | ----- | ------ |
| `auth_mode` | `"oidc_auth"` | Hardcoded |
| `oidc_name` | `"authentik"` | Hardcoded |
| `oidc_endpoint` | `"https://auth.test-cluster.agentydragon.com/application/o/harbor/"` | Variable |
| `oidc_client_id` | `"harbor"` | Hardcoded (matches Authentik app slug) |
| `oidc_client_secret` | Generated | ESO Password generator |
| `oidc_scope` | `"openid,email,profile"` | Hardcoded |
| `oidc_verify_cert` | `true` | Hardcoded |
| `oidc_auto_onboard` | `true` | Hardcoded (create users on first login) |
| `oidc_user_claim` | `"preferred_username"` | Hardcoded |
| `oidc_groups_claim` | `"groups"` | Hardcoded |
| `oidc_admin_group` | `"harbor-admins"` | Hardcoded |

## Alternative Approaches Considered and Rejected

### 1. Flux Post-Install Job

**Idea**: Use Flux Kustomization postBuild hook to run a Job that calls Harbor API.

**Rejected Because**:

- Imperative rather than declarative
- No drift detection
- Harder to maintain than Terraform
- Duplicate effort (Terraform provider already exists)

### 2. Custom Kubernetes Operator

**Idea**: Write a custom operator that manages Harbor configuration via CRDs.

**Rejected Because**:

- Significant development effort
- Maintenance burden
- Reinvents the wheel (Terraform provider exists)
- Not needed for single-cluster use case

### 3. Manual UI Configuration

**Idea**: Configure OIDC via Harbor web UI.

**Rejected Because**:

- Not declarative
- Not version controlled
- Not GitOps-friendly
- Violates PRIMARY DIRECTIVE (turnkey bootstrap)
- Configuration drift over time

## Testing Plan

1. **Deploy Configuration**: Apply Terraform in `03-configuration` layer
2. **Verify Harbor OIDC Settings**:
   - Login to Harbor as admin
   - Check Configuration > Authentication
   - Verify OIDC settings are configured correctly
3. **Test SSO Login**:
   - Logout from Harbor
   - Click "Login via OIDC Provider"
   - Should redirect to Authentik
   - Login with Authentik credentials
   - Should redirect back to Harbor with authenticated session
4. **Verify Auto-Onboarding**:
   - Check that user was automatically created in Harbor
   - Verify username matches Authentik preferred_username
5. **Verify Group Mapping** (future):
   - Create `harbor-admins` group in Authentik
   - Add user to group
   - Verify user has admin privileges in Harbor

## References

- [Harbor Terraform Provider Docs](https://registry.terraform.io/providers/goharbor/harbor/latest/docs)
- [Harbor OIDC Configuration Docs](https://goharbor.io/docs/latest/administration/configure-authentication/oidc-auth/)
- [Authentik OAuth2 Provider Docs](https://goauthentik.io/docs/providers/oauth2/)
- [Harbor API Documentation](https://goharbor.io/docs/latest/build-customize-contribute/configure-swagger/)

## Implementation Update (2025-12-10)

**Bug Fix**: Terraform configuration was initially using a data source to read Harbor OIDC
credentials from Vault, causing a circular dependency. Fixed by referencing the resource directly.

**File**: `terraform/authentik-blueprint/harbor/harbor-config.tf` (lines 37-38)

**Before** (incorrect - data source):

```hcl
data "vault_kv_secret_v2" "harbor_oidc" {
  mount = "kv"
  name  = "sso/harbor"
}
```

**After** (correct - resource reference):

```hcl
oidc_client_id     = jsondecode(
  vault_kv_secret_v2.harbor_oidc.data_json
)["client_id"]
oidc_client_secret = jsondecode(
  vault_kv_secret_v2.harbor_oidc.data_json
)["client_secret"]
```

This ensures proper Terraform resource ordering without circular dependencies.
