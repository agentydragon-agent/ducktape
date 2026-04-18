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
    namespace = "grocy-mcp-sf"
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
    namespace = "grocy-mcp-vallejo"
  }

  data = {
    client_id             = authentik_provider_oauth2.grocy_mcp_vallejo.client_id
    client_secret         = authentik_provider_oauth2.grocy_mcp_vallejo.client_secret
    grocy_proxy_client_id = authentik_provider_proxy.grocy_vallejo.client_id
  }
}

# ============================================================================
# kubectl-sandbox-mcp — Sandbox kubectl MCP server with OIDC auth
# ============================================================================
# Users in kubectl-sandbox-users group can authenticate to the MCP server
# and get kube-apiserver access scoped to claude-sandbox SA permissions.

data "authentik_user" "agentydragon" {
  username = "agentydragon"
}

resource "authentik_group" "kubectl_sandbox_users" {
  name  = "kubectl-sandbox-users"
  users = [data.authentik_user.agentydragon.id]
}

resource "authentik_provider_oauth2" "kubectl_sandbox_mcp" {
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
      # /oauth/callback is the hardcoded callback path in containers/kubernetes-mcp-server.
      url = "https://kubectl-sandbox-mcp.allegedly.works/oauth/callback"
    },
  ]
}

resource "authentik_application" "kubectl_sandbox_mcp" {
  name              = "kubectl-sandbox-mcp"
  slug              = "kubectl-sandbox-mcp"
  protocol_provider = authentik_provider_oauth2.kubectl_sandbox_mcp.id
  meta_description  = "Sandbox kubectl MCP — cluster access scoped to claude-sandbox SA permissions"
  meta_launch_url   = "https://kubectl-sandbox-mcp.allegedly.works"
}

resource "authentik_policy_binding" "kubectl_sandbox_mcp_users" {
  target = authentik_application.kubectl_sandbox_mcp.uuid
  group  = authentik_group.kubectl_sandbox_users.id
  order  = 0
}

# K8s secret with complete config.toml for containers/kubernetes-mcp-server.
# Includes sts_client_id/sts_client_secret used for the authorization-code
# exchange with Authentik (confidential client leg). Namespace created by
# kubectl-sandbox-mcp-namespace Flux Kustomization; agent-machine-access-tf
# dependsOn that kustomization so TF runs after the namespace exists.
resource "kubernetes_secret" "kubectl_sandbox_mcp" {
  metadata {
    name      = "kubectl-sandbox-mcp"
    namespace = "kubectl-sandbox-mcp"
  }

  data = {
    "config.toml" = <<-EOT
      # OAuth is required — clients must authenticate via Authentik before calling tools.
      require_oauth = true

      # Authentik issuer URL for the kubectl-sandbox-mcp OAuth2 provider.
      authorization_url = "https://auth.allegedly.works/application/o/kubectl-sandbox-mcp/"

      # Audience must match what Authentik issues (client_id) and what kube-apiserver
      # accepts (AuthenticationConfiguration audiences entry for kubectl-sandbox-mcp).
      oauth_audience = "kubectl-sandbox-mcp"

      # Confidential client credentials for the authorization-code exchange with Authentik.
      sts_client_id     = "${authentik_provider_oauth2.kubectl_sandbox_mcp.client_id}"
      sts_client_secret = "${authentik_provider_oauth2.kubectl_sandbox_mcp.client_secret}"

      # passthrough: forward the caller's JWT directly to kube-apiserver. No token
      # exchange needed because kube-apiserver is configured to accept this audience.
      cluster_auth_mode = "passthrough"

      # Use in-cluster service account discovery for the kube-apiserver endpoint.
      cluster_provider_strategy = "in-cluster"

      # Public base URL of this MCP server (for well-known OAuth metadata).
      server_url = "https://kubectl-sandbox-mcp.allegedly.works"

      # HTTP port
      port = "8080"
    EOT
  }
}
