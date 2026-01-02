# Gitea Admin Token Automation Research

## Problem Statement

To configure Gitea SSO with Authentik via Terraform, we need an admin API token for Terraform to authenticate with
Gitea. This document explores declarative options for automating admin token generation in a GitOps environment.

## Research Options

### Option 1: Kubernetes Job with curl API Call (SELECTED)

**Description**: Deploy a Kubernetes Job that uses curl to call Gitea's API to create an admin token using BasicAuth
with the admin password.

**Pros**:

- Fully declarative via Kubernetes manifests
- Works with existing admin password from ESO
- No additional dependencies or operators required
- Job idempotency via `restartPolicy: OnFailure`
- Token stored in Kubernetes secret for Terraform consumption
- Well-documented Gitea API endpoint (`POST /api/v1/users/:username/tokens`)

**Cons**:

- Requires admin password (which we already have from ESO)
- Token is created once and stored - no automatic rotation
- Need to handle job re-runs if token already exists (API returns 500 if token name exists)

**Implementation Details**:

<!-- markdownlint-disable MD040 -->

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: gitea-admin-token-generator
  namespace: gitea
spec:
  template:
    spec:
      restartPolicy: OnFailure
      containers:
      - name: token-generator
        image: curlimages/curl:latest
        command: ["/bin/sh", "-c"]
        args:
        - |
          # Generate token via Gitea API
          RESPONSE=$(curl -s -w "\n%{http_code}" -X POST \
            -H "Content-Type: application/json" \
            -d '{"name":"terraform-admin-token","scopes":["write:admin","write:repository","write:user"]}' \
            -u "admin:${GITEA_ADMIN_PASSWORD}" \
            "http://gitea-http:3000/api/v1/users/admin/tokens")

          HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
          BODY=$(echo "$RESPONSE" | head -n-1)

          # Check if successful (201) or already exists (500)
          if [ "$HTTP_CODE" = "201" ] || [ "$HTTP_CODE" = "500" ]; then
            if [ "$HTTP_CODE" = "201" ]; then
              TOKEN=$(echo "$BODY" | grep -o '"sha1":"[^"]*"' | cut -d'"' -f4)
              echo "Token created: $TOKEN"
              # Store in Kubernetes secret
              kubectl create secret generic gitea-admin-token \
                --from-literal=token="$TOKEN" \
                --dry-run=client -o yaml | kubectl apply -f -
            else
              echo "Token already exists, skipping"
            fi
          else
            echo "Failed to create token. HTTP $HTTP_CODE: $BODY"
            exit 1
          fi
        env:
        - name: GITEA_ADMIN_PASSWORD
          valueFrom:
            secretKeyRef:
              name: gitea-admin-password
              key: password
```

<!-- markdownlint-enable MD040 -->

**API Reference**:

- Endpoint: `POST /api/v1/users/{username}/tokens`
- Auth: BasicAuth (username:password)
- Response: `{"id":1, "name":"token_name", "sha1":"actual_token_value", "token_last_eight":"..."}`
- Scopes: Format `[read|write]:<block>` (e.g., `write:admin`, `read:repository`)

### Option 2: Gitea CLI in Init Container

**Description**: Use Gitea's built-in CLI command `gitea admin user generate-access-token` within an init container or Job.

**Pros**:

- Native Gitea command (official supported method)
- No need for external curl/jq dependencies
- Direct access to Gitea internals

**Cons**:

- Requires mounting Gitea's configuration files and data directory
- Needs Gitea container image (heavier than curl)
- More complex volume mounts and permissions
- Requires file system access to Gitea's app.ini and database
- Scope specification issues: tokens without scopes are "effectively useless" (returns 403 errors)

**Implementation Complexity**: HIGH (volume mounts, file permissions, database access)

**Example Command**:

```bash
gitea admin user generate-access-token \
  --username admin \
  --token-name terraform-admin \
  --scopes write:admin,write:repository \
  --raw
```

**Rejected Reason**: Requires complex volume mounts and file system access, making it less portable and harder to
maintain than API approach.

### Option 3: Gitea Operator

**Description**: Use a Kubernetes operator like `hyperspike/gitea-operator` to manage Gitea resources
declaratively.

**Pros**:

- Fully declarative CRD-based management
- Can manage users, repositories, organizations, etc.
- GitOps-friendly

**Cons**:

- Additional operator to deploy and maintain
- Relatively unmaintained (hyperspike/gitea-operator last commit 2021)
- Adds complexity layer on top of Helm chart
- No clear token generation CRD in available operators

**Availability**: Limited operators available, none actively maintained or focused on token management.

**Rejected Reason**: Adds significant complexity without clear benefit for token generation use case.

### Option 4: Helm Chart with Init Container Hook

**Description**: Extend Gitea Helm chart with custom init container or post-install hook.

**Pros**:

- Integrated with Helm release lifecycle
- Can use Helm hooks for timing control

**Cons**:

- Requires forking/customizing official Gitea Helm chart
- Maintenance burden for chart updates
- Flux GitOps makes chart customization complex
- Hook ordering complexity

**Rejected Reason**: Requires maintaining custom chart fork, breaks turnkey deployment principle.

### Option 5: External Secrets Operator with Vault Script

**Description**: Use ESO with Vault's dynamic secrets engine and custom script to generate token.

**Pros**:

- Centralized secret management
- Potential for automatic rotation

**Cons**:

- Requires Vault custom plugin/script development
- Complex integration (Vault needs to call Gitea API)
- Circular dependency: Vault needs Gitea token to generate Gitea token
- Over-engineered for this use case

**Rejected Reason**: Unnecessary complexity, circular dependency issues.

### Option 6: Terraform Provider with Manual Bootstrap Token

**Description**: Manually create initial token via Gitea UI/CLI, store in Vault, use Terraform to manage subsequent resources.

**Pros**:

- Simple initial setup
- Clear separation of bootstrap vs runtime
- Standard practice for many providers

**Cons**:

- **VIOLATES PRIMARY DIRECTIVE**: Not fully turnkey - requires manual intervention
- Token rotation requires manual steps
- Doesn't survive `terraform destroy && bootstrap.sh` cycle

**Rejected Reason**: Fails turnkey bootstrap requirement - manual token creation breaks declarative
workflow.

## Selected Solution: Option 1 (Kubernetes Job with curl)

### Rationale

Option 1 best aligns with project requirements:

1. **Fully Declarative**: Kubernetes Job manifest committed to git
2. **Turnkey Bootstrap**: No manual intervention required
3. **Minimal Dependencies**: Uses standard curl container
4. **Well-Documented API**: Gitea API is stable and well-documented
5. **Simple Integration**: Token stored in K8s secret for Terraform consumption
6. **No Custom Charts**: Works with official Gitea Helm chart

### Architecture

```text
┌─────────────────────────────────────────────────────────────┐
│ Bootstrap Flow                                              │
├─────────────────────────────────────────────────────────────┤
│ 1. ESO generates admin password → gitea-admin-password     │
│ 2. Gitea HelmRelease starts with existingSecret            │
│ 3. Gitea pod initializes with admin user                   │
│ 4. Job reads admin password from gitea-admin-password      │
│ 5. Job calls Gitea API: POST /api/v1/users/admin/tokens    │
│    Auth: BasicAuth admin:${password}                       │
│ 6. Job stores token in gitea-admin-token secret            │
│ 7. Terraform reads token from gitea-admin-token            │
│ 8. Terraform configures Gitea OAuth with Authentik         │
└─────────────────────────────────────────────────────────────┘
```

### Implementation Files

1. **Job Manifest**: `k8s/applications/gitea/admin-token-job.yaml`
   - Kubernetes Job with curl container
   - Reads admin password from ESO-generated secret
   - Creates token via Gitea API
   - Stores result in `gitea-admin-token` secret

2. **Terraform Integration**: Update `terraform/03-configuration/gitea-sso/`
   - Create new terraform directory for Gitea SSO configuration
   - Reads token from Kubernetes secret via varsFrom
   - Configures Gitea OAuth provider to point to Authentik

3. **Flux Kustomization**: `k8s/applications/gitea/kustomization.yaml`
   - Include admin-token-job.yaml in resources
   - Proper dependency ordering (after HelmRelease)

### Token Scopes

Terraform requires these scopes for full Gitea configuration:

- `write:admin` - Manage admin settings, authentication sources
- `write:repository` - Configure repository settings
- `write:user` - Manage user settings
- `write:organization` - Configure organizations (if needed)

Full scope specification in API call:

<!-- markdownlint-disable MD040 -->

```json
{
  "name": "terraform-admin-token",
  "scopes": [
    "write:admin",
    "write:repository",
    "write:user",
    "write:organization"
  ]
}
```

<!-- markdownlint-enable MD040 -->

### Idempotency Handling

The Job handles re-runs gracefully:

1. **First run**: Token doesn't exist → API returns 201 Created → Store token
2. **Subsequent runs**: Token exists → API returns 500 (duplicate name) → Skip creation
3. **Failure handling**: HTTP error codes cause job failure → Kubernetes restarts job

Alternative: Use token UUID/timestamp suffix for uniqueness, always create new token.

### Token Rotation Strategy

**Current**: Token created once during bootstrap, no automatic rotation.

**Future Enhancement** (Phase 2 - see SECRET_SYNCHRONIZATION_ANALYSIS.md):

- CronJob pattern: Periodically create new token, update secret, delete old token
- Overlapping validity: Keep both old and new tokens valid during rotation window
- Integration with Stakater Reloader for automatic Terraform pod restarts

## Alternatives Considered but Rejected

### Terraform Gitea Provider Token Resource

The Gitea Terraform provider has a `gitea_token` resource, but it requires
an existing admin token to create tokens - circular dependency.

### API Token from Database

Directly inserting token into Gitea's PostgreSQL database bypasses API validation and is non-portable across Gitea versions.

### Pre-generated Token in SealedSecret

Violates security best practice of generating secrets at runtime with entropy from the environment.

## References

- Gitea API Documentation: <https://docs.gitea.com/development/api-usage>
- Gitea CLI Documentation: <https://docs.gitea.com/administration/command-line>
- Terraform Gitea Provider: <https://registry.terraform.io/providers/go-gitea/gitea/latest/docs>
- GitHub Issue - CLI token generation: <https://github.com/go-gitea/gitea/issues/17721>
- GitHub Issue - API token auth: <https://github.com/go-gitea/gitea/issues/21186>

## Implementation Status

- [x] Research completed
- [x] Documentation written
- [x] Job manifest created (admin-token-job.yaml, oauth-config-job.yaml)
- [x] Kubernetes Jobs deployed and tested
- [x] Admin token generated successfully
- [x] OAuth configuration created in Gitea
- [x] End-to-end SSO flow working

**Status**: COMPLETE - Users can now login to Gitea using Authentik SSO
