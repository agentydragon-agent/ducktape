terraform {
  required_providers {
    vault = {
      source = "hashicorp/vault"
    }
    random = {
      source = "hashicorp/random"
    }
  }

  backend "kubernetes" {
    secret_suffix = "sso-secrets"
    namespace     = "flux-system"
  }
}

provider "vault" {
  address = var.vault_address
  token   = var.vault_token
}

# Generate Authentik API/Bootstrap token (single token for both bootstrap and API access)
# All per-application OIDC client secrets are now managed by individual blueprints
# in terraform/authentik-blueprint/{app}/main.tf
resource "random_password" "authentik_api_token" {
  length  = 64
  special = false

  lifecycle {
    ignore_changes = [length, special]
  }
}

# Store Authentik API token in Vault
# Per-application OIDC credentials are now stored at kv/sso/{app} by their respective blueprints
resource "vault_kv_secret_v2" "sso_shared_secrets" {
  mount = "kv"
  name  = "sso/client-secrets"

  data_json = jsonencode({
    authentik_api_token = random_password.authentik_api_token.result
  })

  lifecycle {
    ignore_changes = [data_json]
  }
}

# Harbor Admin Password
# Store in Vault as single source of truth
# Both ExternalSecret and Terraform read from this Vault path
resource "random_password" "harbor_admin" {
  length  = 32
  special = false

  lifecycle {
    ignore_changes = [length, special]
  }
}

resource "vault_kv_secret_v2" "harbor_admin_password" {
  mount = "kv"
  name  = "harbor/admin"

  data_json = jsonencode({
    password = random_password.harbor_admin.result
  })

  lifecycle {
    ignore_changes = [data_json]
  }
}