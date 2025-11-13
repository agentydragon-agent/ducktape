# Application Configuration (Harbor + Authentik OIDC)
# This runs after the k3s cluster and applications are deployed via Helm

terraform {
  required_providers {
    authentik = {
      source  = "goauthentik/authentik"
      version = "~> 2025.10.0"
    }
    harbor = {
      source  = "goharbor/harbor"
      version = "~> 3.10.0"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.33.0"
    }
    vault = {
      source  = "hashicorp/vault"
      version = "~> 4.5.0"
    }
  }
}

# Generate secure Harbor admin password 
resource "random_password" "harbor_admin_password" {
  length  = 32
  special = true

  lifecycle {
    ignore_changes = [length, special]
  }
}

# Generate secure client secret (single source of truth)
resource "random_password" "harbor_client_secret" {
  length  = 32
  special = false # Harbor/Authentik might have issues with special chars

  lifecycle {
    ignore_changes = [length, special]
  }
}

# Store all Harbor secrets in Vault (as the authoritative source)
resource "vault_kv_secret_v2" "harbor_secrets" {
  mount = "kv"
  name  = "harbor"

  # Use cas = 0 to only create if it doesn't exist (prevents overwrites)
  cas = 0

  data_json = jsonencode({
    admin-password = random_password.harbor_admin_password.result
    client-secret  = random_password.harbor_client_secret.result
    managed-by     = "terraform"
    created-at     = timestamp()
    description    = "Harbor secrets managed by Terraform for OIDC integration"
  })

  lifecycle {
    # Don't recreate if the secret already exists in Vault
    ignore_changes = [cas, data_json]
  }
}

# Read the secrets back from Vault (for provider configuration)
data "vault_kv_secret_v2" "harbor_secrets" {
  mount      = vault_kv_secret_v2.harbor_secrets.mount
  name       = vault_kv_secret_v2.harbor_secrets.name
  depends_on = [vault_kv_secret_v2.harbor_secrets]
}

# Extract tokens from Kubernetes secrets (since we have cluster root access)
data "kubernetes_secret" "vault_root_token" {
  metadata {
    name      = "vault-root-token"
    namespace = "vault"
  }
}

data "kubernetes_secret" "authentik_bootstrap_token" {
  metadata {
    name      = "authentik-secrets"
    namespace = "authentik"
  }
}

# Provider configurations
provider "vault" {
  address = var.vault_address
  token   = data.kubernetes_secret.vault_root_token.data["root-token"]
}

provider "authentik" {
  url   = var.authentik_url
  token = data.kubernetes_secret.authentik_bootstrap_token.data["bootstrap-token"]
}

provider "harbor" {
  url      = var.harbor_url
  username = var.harbor_username
  password = data.vault_kv_secret_v2.harbor_secrets.data["admin-password"]
}

provider "kubernetes" {
  config_path = var.kubeconfig_path
}

# Harbor + Authentik OIDC Configuration
module "harbor_authentik_oidc" {
  source = "../k3s/modules/harbor-authentik-oidc"

  harbor_external_url    = var.harbor_external_url
  authentik_external_url = var.authentik_external_url
  harbor_admin_group     = var.harbor_admin_group
  harbor_client_secret   = random_password.harbor_client_secret.result
}

# Optional: Store the generated secret in Kubernetes for reference
# (This is mainly for debugging - the actual config is done via Terraform)
resource "kubernetes_secret" "harbor_oidc_terraform" {
  metadata {
    name      = "harbor-oidc-terraform"
    namespace = "harbor"
    labels = {
      "managed-by" = "terraform"
      "purpose"    = "oidc-config"
    }
  }

  data = {
    "client-secret"         = module.harbor_authentik_oidc.harbor_client_secret
    "authentik-provider-id" = module.harbor_authentik_oidc.authentik_provider_id
    "configured-at"         = timestamp()
  }

  type = "Opaque"
}