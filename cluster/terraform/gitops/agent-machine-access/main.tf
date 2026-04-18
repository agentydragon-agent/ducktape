terraform {
  required_version = ">= 1.0"

  required_providers {
    authentik = {
      source  = "goauthentik/authentik"
      version = "~> 2025.10"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.35"
    }
  }

  backend "kubernetes" {
    secret_suffix = "agent-machine-access"
    namespace     = "flux-system"
  }
}

# Read the Authentik bootstrap token from the K8s Secret (populated by ESO from Vault).
data "kubernetes_secret" "authentik_bootstrap" {
  metadata {
    name      = "authentik-bootstrap"
    namespace = "authentik"
  }
}

provider "authentik" {
  url   = "http://authentik-server.authentik.svc.cluster.local"
  token = data.kubernetes_secret.authentik_bootstrap.data["AUTHENTIK_BOOTSTRAP_TOKEN"]
}

# --- Shared data sources ---

data "authentik_flow" "authentication" {
  slug = "default-authentication-flow"
}

data "authentik_flow" "implicit_consent" {
  slug = "default-provider-authorization-implicit-consent"
}

data "authentik_flow" "invalidation" {
  slug = "default-provider-invalidation-flow"
}

data "authentik_group" "admins" {
  name = "authentik Admins"
}

# Signing key + OIDC scope property mappings for the grocy-mcp user-login
# OAuth2 provider below. Mirrors
# <../authentik-mcp-poc/main.tf>'s data-source block.
data "authentik_certificate_key_pair" "self_signed" {
  name = "authentik Self-signed Certificate"
}

data "authentik_property_mapping_provider_scope" "openid" {
  managed = "goauthentik.io/providers/oauth2/scope-openid"
}

data "authentik_property_mapping_provider_scope" "email" {
  managed = "goauthentik.io/providers/oauth2/scope-email"
}

data "authentik_property_mapping_provider_scope" "profile" {
  managed = "goauthentik.io/providers/oauth2/scope-profile"
}

# --- Service Account ---
# Shared service account for Claude/OpenClaw sandbox agents.
# Used for Authentik API access (e.g., querying user info).

resource "authentik_user" "agent_sa" {
  username = "agent-service-account"
  name     = "Agent Service Account"
  type     = "service_account"
  path     = "goauthentik.io/service-accounts"
}

resource "authentik_token" "agent_sa_token" {
  identifier   = "agent-api-key"
  user         = authentik_user.agent_sa.id
  intent       = "api"
  expiring     = false
  retrieve_key = true
  description  = "Bearer token for Claude/OpenClaw sandbox agents"
}

# K8s secret in claude-sandbox with Reflector annotations for openclaw-sandbox.
resource "kubernetes_secret" "agent_bearer_token" {
  metadata {
    name      = "agent-bearer-token"
    namespace = "claude-sandbox"
    annotations = {
      "reflector.v1.k8s.emberstack.com/reflection-allowed"            = "true"
      "reflector.v1.k8s.emberstack.com/reflection-allowed-namespaces" = "openclaw-sandbox"
      "reflector.v1.k8s.emberstack.com/reflection-auto-enabled"       = "true"
      "reflector.v1.k8s.emberstack.com/reflection-auto-namespaces"    = "openclaw-sandbox"
    }
  }

  data = {
    token = authentik_token.agent_sa_token.key
  }
}

# --- Grocy SF household (proxy provider + MCP OAuth2) ---

resource "authentik_provider_proxy" "grocy_sf" {
  name                  = "grocy-sf"
  external_host         = "https://grocy-sf.allegedly.works"
  internal_host         = "http://grocy.grocy-sf.svc.cluster.local:80"
  mode                  = "proxy"
  authentication_flow   = data.authentik_flow.authentication.id
  authorization_flow    = data.authentik_flow.implicit_consent.id
  invalidation_flow     = data.authentik_flow.invalidation.id
  access_token_validity = "hours=24"

  jwt_federation_providers = [authentik_provider_oauth2.grocy_mcp_sf.id]
}

resource "authentik_application" "grocy_sf" {
  name              = "Grocy SF"
  slug              = "grocy-sf"
  protocol_provider = authentik_provider_proxy.grocy_sf.id
  meta_description  = "Groceries & household management (SF)"
  meta_icon         = "https://cdn.simpleicons.org/grocy"
  meta_launch_url   = "https://grocy-sf.allegedly.works"
  open_in_new_tab   = true
}

resource "authentik_policy_binding" "grocy_sf_admins" {
  target = authentik_application.grocy_sf.uuid
  group  = data.authentik_group.admins.id
  order  = 0
}

resource "authentik_provider_oauth2" "grocy_mcp_sf" {
  name               = "grocy-mcp-sf"
  client_id          = "grocy-mcp-sf"
  client_type        = "confidential"
  authorization_flow = data.authentik_flow.implicit_consent.id
  invalidation_flow  = data.authentik_flow.invalidation.id
  signing_key        = data.authentik_certificate_key_pair.self_signed.id

  issuer_mode                = "per_provider"
  include_claims_in_id_token = true

  property_mappings = [
    data.authentik_property_mapping_provider_scope.openid.id,
    data.authentik_property_mapping_provider_scope.email.id,
    data.authentik_property_mapping_provider_scope.profile.id,
  ]

  allowed_redirect_uris = [
    {
      matching_mode = "strict"
      url           = "https://grocy-mcp-sf.allegedly.works/auth/callback"
    },
  ]
}

resource "authentik_application" "grocy_mcp_sf" {
  name              = "Grocy MCP SF"
  slug              = "grocy-mcp-sf"
  protocol_provider = authentik_provider_oauth2.grocy_mcp_sf.id
  meta_description  = "Auth-aware MCP server for Grocy SF household"
  meta_launch_url   = "https://grocy-mcp-sf.allegedly.works"
}

resource "authentik_policy_binding" "grocy_mcp_sf_admins" {
  target = authentik_application.grocy_mcp_sf.uuid
  group  = data.authentik_group.admins.id
  order  = 0
}

resource "kubernetes_secret" "grocy_mcp_oidc_sf" {
  metadata {
    name      = "grocy-mcp-oidc-sf"
    namespace = "grocy-sf"
  }

  data = {
    client_id             = authentik_provider_oauth2.grocy_mcp_sf.client_id
    client_secret         = authentik_provider_oauth2.grocy_mcp_sf.client_secret
    grocy_proxy_client_id = authentik_provider_proxy.grocy_sf.client_id
  }
}

# --- Grocy Vallejo household (proxy provider + MCP OAuth2) ---

resource "authentik_provider_proxy" "grocy_vallejo" {
  name                  = "grocy-vallejo"
  external_host         = "https://grocy-vallejo.allegedly.works"
  internal_host         = "http://grocy.grocy-vallejo.svc.cluster.local:80"
  mode                  = "proxy"
  authentication_flow   = data.authentik_flow.authentication.id
  authorization_flow    = data.authentik_flow.implicit_consent.id
  invalidation_flow     = data.authentik_flow.invalidation.id
  access_token_validity = "hours=24"

  jwt_federation_providers = [authentik_provider_oauth2.grocy_mcp_vallejo.id]
}

resource "authentik_application" "grocy_vallejo" {
  name              = "Grocy Vallejo"
  slug              = "grocy-vallejo"
  protocol_provider = authentik_provider_proxy.grocy_vallejo.id
  meta_description  = "Groceries & household management (Vallejo)"
  meta_icon         = "https://cdn.simpleicons.org/grocy"
  meta_launch_url   = "https://grocy-vallejo.allegedly.works"
  open_in_new_tab   = true
}

resource "authentik_policy_binding" "grocy_vallejo_admins" {
  target = authentik_application.grocy_vallejo.uuid
  group  = data.authentik_group.admins.id
  order  = 0
}

resource "authentik_provider_oauth2" "grocy_mcp_vallejo" {
  name               = "grocy-mcp-vallejo"
  client_id          = "grocy-mcp-vallejo"
  client_type        = "confidential"
  authorization_flow = data.authentik_flow.implicit_consent.id
  invalidation_flow  = data.authentik_flow.invalidation.id
  signing_key        = data.authentik_certificate_key_pair.self_signed.id

  issuer_mode                = "per_provider"
  include_claims_in_id_token = true

  property_mappings = [
    data.authentik_property_mapping_provider_scope.openid.id,
    data.authentik_property_mapping_provider_scope.email.id,
    data.authentik_property_mapping_provider_scope.profile.id,
  ]

  allowed_redirect_uris = [
    {
      matching_mode = "strict"
      url           = "https://grocy-mcp-vallejo.allegedly.works/auth/callback"
    },
  ]
}

resource "authentik_application" "grocy_mcp_vallejo" {
  name              = "Grocy MCP Vallejo"
  slug              = "grocy-mcp-vallejo"
  protocol_provider = authentik_provider_oauth2.grocy_mcp_vallejo.id
  meta_description  = "Auth-aware MCP server for Grocy Vallejo household"
  meta_launch_url   = "https://grocy-mcp-vallejo.allegedly.works"
}

resource "authentik_policy_binding" "grocy_mcp_vallejo_admins" {
  target = authentik_application.grocy_mcp_vallejo.uuid
  group  = data.authentik_group.admins.id
  order  = 0
}

resource "kubernetes_secret" "grocy_mcp_oidc_vallejo" {
  metadata {
    name      = "grocy-mcp-oidc-vallejo"
    namespace = "grocy-vallejo"
  }

  data = {
    client_id             = authentik_provider_oauth2.grocy_mcp_vallejo.client_id
    client_secret         = authentik_provider_oauth2.grocy_mcp_vallejo.client_secret
    grocy_proxy_client_id = authentik_provider_proxy.grocy_vallejo.client_id
  }
}

# ============================================================================
# Shared: kubectl-sandbox-users group
# ============================================================================

data "authentik_user" "agentydragon" {
  username = "agentydragon"
}

resource "authentik_group" "kubectl_sandbox_users" {
  name  = "kubectl-sandbox-users"
  users = [data.authentik_user.agentydragon.id]
}

# ============================================================================
# kubectl-passthrough-mcp — Passthrough kubectl MCP (caller's own permissions)
# ============================================================================
# Forwards the caller's Authentik JWT directly to kube-apiserver. The caller
# gets their own OIDC permissions — not sandbox-scoped.

resource "authentik_provider_oauth2" "kubectl_passthrough_mcp" {
  name               = "kubectl-passthrough-mcp"
  client_id          = "kubectl-passthrough-mcp"
  client_type        = "confidential"
  authorization_flow = data.authentik_flow.implicit_consent.id
  invalidation_flow  = data.authentik_flow.invalidation.id
  signing_key        = data.authentik_certificate_key_pair.self_signed.id

  issuer_mode                = "per_provider"
  include_claims_in_id_token = true

  property_mappings = [
    data.authentik_property_mapping_provider_scope.openid.id,
    data.authentik_property_mapping_provider_scope.email.id,
    data.authentik_property_mapping_provider_scope.profile.id,
  ]

  allowed_redirect_uris = [
    {
      matching_mode = "strict"
      url           = "https://kubectl-passthrough-mcp.allegedly.works/oauth/callback"
    },
  ]
}

moved {
  from = authentik_provider_oauth2.kubectl_sandbox_mcp
  to   = authentik_provider_oauth2.kubectl_passthrough_mcp
}

resource "authentik_application" "kubectl_passthrough_mcp" {
  name              = "kubectl-passthrough-mcp"
  slug              = "kubectl-passthrough-mcp"
  protocol_provider = authentik_provider_oauth2.kubectl_passthrough_mcp.id
  meta_description  = "Passthrough kubectl MCP — forwards caller's JWT to kube-apiserver (caller's own permissions)"
  meta_launch_url   = "https://kubectl-passthrough-mcp.allegedly.works"
}

moved {
  from = authentik_application.kubectl_sandbox_mcp
  to   = authentik_application.kubectl_passthrough_mcp
}

resource "authentik_policy_binding" "kubectl_passthrough_mcp_users" {
  target = authentik_application.kubectl_passthrough_mcp.uuid
  group  = authentik_group.kubectl_sandbox_users.id
  order  = 0
}

moved {
  from = authentik_policy_binding.kubectl_sandbox_mcp_users
  to   = authentik_policy_binding.kubectl_passthrough_mcp_users
}

resource "kubernetes_secret" "kubectl_passthrough_mcp" {
  metadata {
    name      = "kubectl-passthrough-mcp"
    namespace = "kubectl-passthrough-mcp"
  }

  data = {
    "config.toml" = <<-EOT
      require_oauth = true
      # In-cluster URL for OIDC discovery (pods can't hairpin to external VPS IPs).
      # Client-facing auth endpoints (authorize, token) come from the OIDC config
      # itself, which Authentik returns with public URLs regardless of fetch origin.
      authorization_url = "http://authentik-server.authentik.svc.cluster.local/application/o/kubectl-passthrough-mcp/"
      oauth_audience = "kubectl-passthrough-mcp"
      sts_client_id     = "${authentik_provider_oauth2.kubectl_passthrough_mcp.client_id}"
      sts_client_secret = "${authentik_provider_oauth2.kubectl_passthrough_mcp.client_secret}"
      cluster_auth_mode = "passthrough"
      cluster_provider_strategy = "in-cluster"
      server_url = "https://kubectl-passthrough-mcp.allegedly.works"
      port = "8080"
    EOT
  }
}

moved {
  from = kubernetes_secret.kubectl_sandbox_mcp
  to   = kubernetes_secret.kubectl_passthrough_mcp
}

# ============================================================================
# kubectl-sandbox-mcp — Scoped kubectl MCP (token exchange → sandbox only)
# ============================================================================
# Authenticates callers via Authentik consent, then exchanges the caller's
# token for one scoped to kubectl-sandbox-users group. Even if the caller is
# a cluster admin, the exchanged token only carries sandbox-level permissions.

resource "authentik_provider_oauth2" "kubectl_sandbox_scoped" {
  name               = "kubectl-sandbox-mcp"
  client_id          = "kubectl-sandbox-mcp"
  client_type        = "confidential"
  authorization_flow = data.authentik_flow.implicit_consent.id
  invalidation_flow  = data.authentik_flow.invalidation.id
  signing_key        = data.authentik_certificate_key_pair.self_signed.id

  issuer_mode                = "per_provider"
  include_claims_in_id_token = true

  property_mappings = [
    data.authentik_property_mapping_provider_scope.openid.id,
    data.authentik_property_mapping_provider_scope.email.id,
    data.authentik_property_mapping_provider_scope.profile.id,
  ]

  allowed_redirect_uris = [
    {
      matching_mode = "strict"
      url           = "https://kubectl-sandbox-mcp.allegedly.works/oauth/callback"
    },
  ]
}

# Proxy provider used as the token exchange target. The exchanged token
# carries only the scoped claims from this provider (kubectl-sandbox-users
# group), regardless of the caller's actual groups/permissions.
resource "authentik_provider_proxy" "kubectl_sandbox_scoped" {
  name                  = "kubectl-sandbox-mcp-proxy"
  external_host         = "https://kubectl-sandbox-mcp.allegedly.works"
  internal_host         = "http://localhost"
  mode                  = "proxy"
  authentication_flow   = data.authentik_flow.authentication.id
  authorization_flow    = data.authentik_flow.implicit_consent.id
  invalidation_flow     = data.authentik_flow.invalidation.id
  access_token_validity = "hours=1"

  # Allow the OAuth2 provider's tokens to be exchanged for proxy-scoped ones.
  jwt_federation_providers = [authentik_provider_oauth2.kubectl_sandbox_scoped.id]
}

resource "authentik_application" "kubectl_sandbox_scoped" {
  name              = "kubectl-sandbox-mcp"
  slug              = "kubectl-sandbox-mcp"
  protocol_provider = authentik_provider_oauth2.kubectl_sandbox_scoped.id
  meta_description  = "Sandbox kubectl MCP — token exchange scopes to sandbox permissions"
  meta_launch_url   = "https://kubectl-sandbox-mcp.allegedly.works"
}

resource "authentik_policy_binding" "kubectl_sandbox_scoped_users" {
  target = authentik_application.kubectl_sandbox_scoped.uuid
  group  = authentik_group.kubectl_sandbox_users.id
  order  = 0
}

resource "kubernetes_secret" "kubectl_sandbox_scoped" {
  metadata {
    name      = "kubectl-sandbox-mcp"
    namespace = "kubectl-sandbox-mcp"
  }

  data = {
    "config.toml" = <<-EOT
      require_oauth = true
      # In-cluster URL for OIDC discovery (pods can't hairpin to external VPS IPs).
      authorization_url = "http://authentik-server.authentik.svc.cluster.local/application/o/kubectl-sandbox-mcp/"
      oauth_audience = "kubectl-sandbox-mcp"

      # Token exchange: swap caller's token for a sandbox-scoped one via the
      # proxy provider. The exchanged token carries only kubectl-sandbox-users
      # group, regardless of the caller's actual permissions.
      cluster_auth_mode = "passthrough"
      cluster_provider_strategy = "in-cluster"
      token_exchange_strategy = "rfc8693"
      sts_client_id     = "${authentik_provider_oauth2.kubectl_sandbox_scoped.client_id}"
      sts_client_secret = "${authentik_provider_oauth2.kubectl_sandbox_scoped.client_secret}"
      sts_audience      = "${authentik_provider_proxy.kubectl_sandbox_scoped.client_id}"

      server_url = "https://kubectl-sandbox-mcp.allegedly.works"
      port = "8080"
    EOT
  }
}
