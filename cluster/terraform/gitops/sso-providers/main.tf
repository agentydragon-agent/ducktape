# SSO OAuth2 providers managed by Terraform.
#
# Replaces blueprint+Vault+ESO chain for Grafana, Headlamp, and
# OpenClaw-Agent. TF creates the Authentik provider (which owns the
# client_secret), then writes K8s secrets into the authentik namespace.
# Reflector mirrors them to consumer namespaces.

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
    secret_suffix = "sso-providers"
    namespace     = "flux-system"
  }
}

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

data "authentik_flow" "implicit_consent" {
  slug = "default-provider-authorization-implicit-consent"
}

data "authentik_flow" "invalidation" {
  slug = "default-provider-invalidation-flow"
}

data "authentik_group" "admins" {
  name = "authentik Admins"
}

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

# Custom airlock scope mappings (defined in airlock-scope-mappings.yaml blueprint)
data "authentik_property_mapping_provider_scope" "propose" {
  scope_name = "propose"
}

data "authentik_property_mapping_provider_scope" "read" {
  scope_name = "read"
}

# ============================================================================
# Grafana — OIDC login for the monitoring dashboard
# ============================================================================

resource "authentik_provider_oauth2" "grafana" {
  name               = "grafana-oauth2"
  client_id          = "grafana"
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
      url           = "https://grafana.allegedly.works/login/generic_oauth"
    },
  ]
}

resource "authentik_application" "grafana" {
  name              = "Grafana"
  slug              = "grafana"
  protocol_provider = authentik_provider_oauth2.grafana.id
  meta_icon         = "https://cdn.simpleicons.org/grafana"
  open_in_new_tab   = true
}

resource "authentik_policy_binding" "grafana_admins" {
  target = authentik_application.grafana.uuid
  group  = data.authentik_group.admins.id
  order  = 0
}

resource "kubernetes_secret" "grafana_oidc" {
  metadata {
    name      = "grafana-oidc-config"
    namespace = "authentik"
    annotations = {
      "reflector.v1.k8s.emberstack.com/reflection-allowed"            = "true"
      "reflector.v1.k8s.emberstack.com/reflection-allowed-namespaces" = "monitoring"
      "reflector.v1.k8s.emberstack.com/reflection-auto-enabled"       = "true"
      "reflector.v1.k8s.emberstack.com/reflection-auto-namespaces"    = "monitoring"
    }
  }

  data = {
    GF_AUTH_GENERIC_OAUTH_CLIENT_ID     = authentik_provider_oauth2.grafana.client_id
    GF_AUTH_GENERIC_OAUTH_CLIENT_SECRET = authentik_provider_oauth2.grafana.client_secret
  }
}

# ============================================================================
# Headlamp — OIDC login for the Kubernetes dashboard
# ============================================================================

resource "authentik_provider_oauth2" "headlamp" {
  name               = "headlamp"
  client_id          = "headlamp"
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
      url           = "https://headlamp.allegedly.works/oidc-callback"
    },
  ]
}

resource "authentik_application" "headlamp" {
  name              = "Headlamp"
  slug              = "headlamp"
  protocol_provider = authentik_provider_oauth2.headlamp.id
  meta_description  = "Kubernetes cluster UI"
  meta_launch_url   = "https://headlamp.allegedly.works"
  meta_icon         = "https://raw.githubusercontent.com/kubernetes-sigs/headlamp/main/frontend/public/android-chrome-512x512.png"
  open_in_new_tab   = true
}

resource "authentik_policy_binding" "headlamp_admins" {
  target = authentik_application.headlamp.uuid
  group  = data.authentik_group.admins.id
  order  = 0
}

resource "kubernetes_secret" "headlamp_oidc" {
  metadata {
    name      = "headlamp-oidc-secret"
    namespace = "authentik"
    annotations = {
      "reflector.v1.k8s.emberstack.com/reflection-allowed"            = "true"
      "reflector.v1.k8s.emberstack.com/reflection-allowed-namespaces" = "headlamp"
      "reflector.v1.k8s.emberstack.com/reflection-auto-enabled"       = "true"
      "reflector.v1.k8s.emberstack.com/reflection-auto-namespaces"    = "headlamp"
    }
  }

  data = {
    OIDC_CLIENT_ID     = authentik_provider_oauth2.headlamp.client_id
    OIDC_CLIENT_SECRET = authentik_provider_oauth2.headlamp.client_secret
    OIDC_ISSUER_URL    = "https://auth.allegedly.works/application/o/headlamp/"
    OIDC_SCOPES        = "openid profile email"
  }
}

# ============================================================================
# OpenClaw Agent — M2M auth via client_credentials grant
# ============================================================================

resource "authentik_provider_oauth2" "openclaw_agent" {
  name               = "openclaw-agent"
  client_id          = "openclaw-agent"
  client_type        = "confidential"
  authorization_flow = data.authentik_flow.implicit_consent.id
  invalidation_flow  = data.authentik_flow.invalidation.id
  signing_key        = data.authentik_certificate_key_pair.self_signed.id

  issuer_mode                = "per_provider"
  include_claims_in_id_token = true
  access_token_validity      = "hours=1"

  property_mappings = [
    data.authentik_property_mapping_provider_scope.openid.id,
    data.authentik_property_mapping_provider_scope.propose.id,
    data.authentik_property_mapping_provider_scope.read.id,
  ]

  allowed_redirect_uris = []
}

resource "authentik_application" "openclaw_agent" {
  name              = "OpenClaw Agent"
  slug              = "openclaw-agent"
  protocol_provider = authentik_provider_oauth2.openclaw_agent.id
  meta_description  = "Machine-to-machine auth for openclaw agents"
}

resource "authentik_user" "openclaw_agent_sa" {
  username  = "openclaw-agent-sa"
  name      = "OpenClaw Agent (Service Account)"
  type      = "service_account"
  is_active = true
  path      = "service-accounts"
}

resource "authentik_policy_binding" "openclaw_agent_sa" {
  target = authentik_application.openclaw_agent.uuid
  user   = authentik_user.openclaw_agent_sa.id
  order  = 0
}

resource "kubernetes_secret" "airlock_secrets" {
  metadata {
    name      = "airlock-secrets"
    namespace = "authentik"
    annotations = {
      description                                                     = "OAuth2 client creds for openclaw-agent — reflected to airlock and openclaw-gateway"
      "reflector.v1.k8s.emberstack.com/reflection-allowed"            = "true"
      "reflector.v1.k8s.emberstack.com/reflection-allowed-namespaces" = "airlock,openclaw-gateway"
      "reflector.v1.k8s.emberstack.com/reflection-auto-enabled"       = "true"
      "reflector.v1.k8s.emberstack.com/reflection-auto-namespaces"    = "airlock,openclaw-gateway"
    }
  }

  data = {
    "client-id"     = authentik_provider_oauth2.openclaw_agent.client_id
    "client-secret" = authentik_provider_oauth2.openclaw_agent.client_secret
  }
}
