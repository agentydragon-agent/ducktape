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
    secret_suffix = "authentik-blueprint-matrix"
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

# Generate Matrix OAuth client secret
resource "random_password" "matrix_client_secret" {
  length  = 32
  special = false

  lifecycle {
    ignore_changes = [length, special]
  }
}

# Store Matrix OIDC credentials in Vault
resource "vault_kv_secret_v2" "matrix_oidc" {
  mount = "kv"
  name  = "sso/matrix"

  data_json = jsonencode({
    client_id     = "matrix"
    client_secret = random_password.matrix_client_secret.result
  })

  lifecycle {
    ignore_changes = [data_json]
  }
}

# Create Authentik application for Matrix
resource "authentik_application" "matrix" {
  name              = "Matrix"
  slug              = "matrix"
  protocol_provider = authentik_provider_oauth2.matrix.id
  meta_description  = "Matrix Synapse Homeserver"
  meta_publisher    = "Matrix.org"
  open_in_new_tab   = true
}

# Create OAuth2 provider for Matrix
resource "authentik_provider_oauth2" "matrix" {
  name               = "matrix-oauth2"
  client_id          = "matrix"
  client_secret      = random_password.matrix_client_secret.result
  authorization_flow = data.authentik_flow.default_authorization_flow.id
  invalidation_flow  = data.authentik_flow.default_invalidation_flow.id

  allowed_redirect_uris = [
    {
      matching_mode = "strict"
      url           = "${var.matrix_url}/_synapse/client/oidc/callback"
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

# Store complete OIDC configuration in Vault for consumption by Matrix Synapse
# Stored as structured JSON (not YAML string) for proper injection via ExternalSecret
resource "vault_kv_secret_v2" "matrix_oidc_config" {
  mount = "kv"
  name  = "sso/oidc-providers/matrix"

  data_json = jsonencode({
    # Store as structured list for ExternalSecret to template into Helm values
    oidc_providers = [
      {
        idp_id        = "authentik"
        idp_name      = "Authentik SSO"
        discover      = true
        issuer        = "http://authentik-server.authentik/application/o/${authentik_application.matrix.slug}/"
        client_id     = authentik_provider_oauth2.matrix.client_id
        client_secret = random_password.matrix_client_secret.result
        scopes = [
          "openid",
          "profile",
          "email"
        ]
        user_mapping_provider = {
          config = {
            localpart_template    = "{{ user.preferred_username }}"
            display_name_template = "{{ user.name }}"
            email_template        = "{{ user.email }}"
          }
        }
        allow_existing_users = true
        enable_registration  = true
      }
    ]
  })
}