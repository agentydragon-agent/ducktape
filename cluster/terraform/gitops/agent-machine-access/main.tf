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

# --- Grocy (proxy provider + machine auth via client_credentials) ---
# Replaces the grocy-sso.yaml blueprint. TF is the sole manager.
# Humans authenticate via OIDC (browser session through the proxy outpost).
# Agents exchange client_id + client_secret for a JWT via client_credentials,
# then use the JWT as Bearer token against grocy.allegedly.works.
# The proxy outpost only accepts JWTs from its own provider, so both flows
# must go through the same provider.

resource "authentik_provider_proxy" "grocy" {
  name               = "grocy"
  external_host      = "https://grocy.allegedly.works"
  internal_host      = "http://grocy.grocy.svc.cluster.local:80"
  mode               = "proxy"
  authentication_flow = data.authentik_flow.authentication.id
  authorization_flow  = data.authentik_flow.implicit_consent.id
  invalidation_flow   = data.authentik_flow.invalidation.id
  access_token_validity = "hours=24"
}

resource "authentik_application" "grocy" {
  name              = "Grocy"
  slug              = "grocy"
  protocol_provider = authentik_provider_proxy.grocy.id
  meta_description  = "Groceries & household management"
  meta_icon         = "https://cdn.simpleicons.org/grocy"
  meta_launch_url   = "https://grocy.allegedly.works"
  open_in_new_tab   = true
}

# Human access: admins group.
resource "authentik_policy_binding" "grocy_admins" {
  target = authentik_application.grocy.uuid
  group  = data.authentik_group.admins.id
  order  = 0
}

# Machine access: pre-create the service account that client_credentials
# auto-generates (ak-<provider-slug>-client_credentials) so we can bind it.
resource "authentik_user" "grocy_machine_sa" {
  username = "ak-grocy-client_credentials"
  name     = "Grocy Machine (client_credentials)"
  type     = "service_account"
  path     = "goauthentik.io/service-accounts"
}

resource "authentik_policy_binding" "grocy_machine_sa" {
  target = authentik_application.grocy.uuid
  user   = authentik_user.grocy_machine_sa.id
  order  = 10
}

# K8s secret with the proxy provider's OAuth2 credentials for agents.
resource "kubernetes_secret" "grocy_machine_credentials" {
  metadata {
    name      = "grocy-machine-credentials"
    namespace = "claude-sandbox"
    annotations = {
      "reflector.v1.k8s.emberstack.com/reflection-allowed"            = "true"
      "reflector.v1.k8s.emberstack.com/reflection-allowed-namespaces" = "openclaw-sandbox"
      "reflector.v1.k8s.emberstack.com/reflection-auto-enabled"       = "true"
      "reflector.v1.k8s.emberstack.com/reflection-auto-namespaces"    = "openclaw-sandbox"
    }
  }

  data = {
    client_id     = authentik_provider_proxy.grocy.client_id
    client_secret = authentik_provider_proxy.grocy.client_secret
  }
}
