terraform {
  required_version = ">= 1.0"

  required_providers {
    authentik = {
      source = "goauthentik/authentik"
    }
    vault = {
      source = "hashicorp/vault"
    }
    random = {
      source = "hashicorp/random"
    }
  }

  backend "kubernetes" {
    secret_suffix = "grafana-sso"
    namespace     = "flux-system"
  }
}

provider "authentik" {
  url   = var.authentik_url
  token = var.authentik_token
}

provider "vault" {
  address = var.vault_address
  token   = var.vault_token
}

# Generate Grafana OAuth client secret
resource "random_password" "grafana_client_secret" {
  length  = 32
  special = false

  lifecycle {
    ignore_changes = [length, special]
  }
}

# Store Grafana OIDC credentials in Vault
resource "vault_kv_secret_v2" "grafana_oidc" {
  mount = "kv"
  name  = "sso/grafana"

  data_json = jsonencode({
    client_id     = "grafana"
    client_secret = random_password.grafana_client_secret.result
  })

  lifecycle {
    ignore_changes = [data_json]
  }
}

# Create Authentik application for Grafana
resource "authentik_application" "grafana" {
  name              = "Grafana"
  slug              = "grafana"
  protocol_provider = authentik_provider_oauth2.grafana.id
  meta_description  = "Grafana Monitoring and Observability"
  meta_publisher    = "Grafana Labs"
  open_in_new_tab   = true
}

# Create OAuth2 provider for Grafana
resource "authentik_provider_oauth2" "grafana" {
  name               = "grafana-oauth2"
  client_id          = "grafana"
  client_secret      = random_password.grafana_client_secret.result
  authorization_flow = data.authentik_flow.default_authorization_flow.id
  invalidation_flow  = data.authentik_flow.default_invalidation_flow.id

  allowed_redirect_uris = [
    {
      matching_mode = "strict"
      url           = "${var.grafana_url}/login/generic_oauth"
    }
  ]

  client_type                = "confidential"
  issuer_mode                = "per_provider"
  include_claims_in_id_token = true

  property_mappings = data.authentik_property_mapping_provider_scope.scopes.ids
}

# Data sources for default flows and mappings
data "authentik_flow" "default_authorization_flow" {
  slug = "default-provider-authorization-implicit-consent"
}

data "authentik_flow" "default_invalidation_flow" {
  slug = "default-provider-invalidation-flow"
}

data "authentik_property_mapping_provider_scope" "scopes" {
  managed_list = [
    "goauthentik.io/providers/oauth2/scope-openid",
    "goauthentik.io/providers/oauth2/scope-email",
    "goauthentik.io/providers/oauth2/scope-profile",
  ]
}

# Store complete OIDC configuration in Vault for consumption by Grafana
# This eliminates duplication between Terraform (source of truth) and Kubernetes manifests
resource "vault_kv_secret_v2" "grafana_oidc_config" {
  mount = "kv"
  name  = "sso/oidc-providers/grafana"

  data_json = jsonencode({
    # Store configuration as individual fields (not YAML-encoded)
    # ExternalSecret will template these into the values
    enabled             = true
    name                = "Authentik"
    client_id           = authentik_provider_oauth2.grafana.client_id
    client_secret       = random_password.grafana_client_secret.result
    scopes              = "openid email profile"
    auth_url            = "https://auth.test-cluster.agentydragon.com/application/o/authorize/"
    token_url           = "http://authentik-server.authentik/application/o/token/"
    api_url             = "http://authentik-server.authentik/application/o/userinfo/"
    role_attribute_path = "contains(groups[*], 'Grafana Admins') && 'Admin' || 'Viewer'"
    allow_sign_up       = true
  })
}
