terraform {
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
    secret_suffix = "authentik-blueprint-vault"
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

# Generate Vault OAuth client secret
resource "random_password" "vault_client_secret" {
  length  = 32
  special = false

  lifecycle {
    ignore_changes = [length, special]
  }
}

# Store Vault OIDC credentials in Vault
resource "vault_kv_secret_v2" "vault_oidc" {
  mount = "kv"
  name  = "sso/vault"

  data_json = jsonencode({
    client_id     = "vault"
    client_secret = random_password.vault_client_secret.result
  })

  lifecycle {
    ignore_changes = [data_json]
  }
}

# Create Authentik application for Vault
resource "authentik_application" "vault" {
  name              = "Vault"
  slug              = "vault"
  protocol_provider = authentik_provider_oauth2.vault.id
  meta_description  = "HashiCorp Vault Secrets Management"
  meta_publisher    = "HashiCorp"
  open_in_new_tab   = true
}

# Create OAuth2/OIDC provider for Vault
resource "authentik_provider_oauth2" "vault" {
  name               = "vault-oidc"
  client_id          = "vault"
  client_secret      = random_password.vault_client_secret.result
  authorization_flow = data.authentik_flow.default_authorization_flow.id
  invalidation_flow  = data.authentik_flow.default_invalidation_flow.id

  allowed_redirect_uris = [
    {
      matching_mode = "strict"
      url           = "${var.vault_url}/ui/vault/auth/oidc/oidc/callback"
    },
    {
      matching_mode = "strict"
      url           = "${var.vault_url}/oidc/callback"
    }
  ]

  client_type                = "confidential"
  issuer_mode                = "per_provider"
  include_claims_in_id_token = true

  property_mappings = data.authentik_property_mapping_provider_scope.scopes.ids

  signing_key = data.authentik_certificate_key_pair.default.id
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

data "authentik_certificate_key_pair" "default" {
  name = "authentik Self-signed Certificate"
}
