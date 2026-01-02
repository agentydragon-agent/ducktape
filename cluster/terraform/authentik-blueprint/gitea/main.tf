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
    secret_suffix = "authentik-blueprint-gitea"
    namespace     = "flux-system"
  }
}

provider "authentik" {
  url   = var.authentik_url
  token = var.authentik_token
}

provider "vault" {
  address         = var.vault_address
  token           = var.vault_token
  skip_tls_verify = true # Self-signed internal CA
}

# Generate Gitea OAuth client secret
resource "random_password" "gitea_client_secret" {
  length  = 32
  special = false

  lifecycle {
    ignore_changes = [length, special]
  }
}

# Store Gitea OIDC credentials in Vault
resource "vault_kv_secret_v2" "gitea_oidc" {
  mount = "kv"
  name  = "sso/gitea"

  data_json = jsonencode({
    client_id     = "gitea"
    client_secret = random_password.gitea_client_secret.result
  })

  lifecycle {
    ignore_changes = [data_json]
  }
}

# Create Authentik application for Gitea
resource "authentik_application" "gitea" {
  name              = "Gitea"
  slug              = "gitea"
  protocol_provider = authentik_provider_oauth2.gitea.id
  meta_description  = "Gitea Git Repository Management"
  meta_publisher    = "Gitea"
  open_in_new_tab   = true
}

# Create OAuth2 provider for Gitea
resource "authentik_provider_oauth2" "gitea" {
  name               = "gitea-oauth2"
  client_id          = "gitea"
  client_secret      = random_password.gitea_client_secret.result
  authorization_flow = data.authentik_flow.default_authorization_flow.id
  invalidation_flow  = data.authentik_flow.default_invalidation_flow.id

  allowed_redirect_uris = [
    {
      matching_mode = "strict"
      url           = "${var.gitea_url}/user/oauth2/authentik/callback"
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