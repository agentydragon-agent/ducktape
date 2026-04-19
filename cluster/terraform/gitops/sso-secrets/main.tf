terraform {
  required_version = ">= 1.0"

  required_providers {
    vault = {
      source  = "hashicorp/vault"
      version = "~> 5.7.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.7.0"
    }
  }

  backend "kubernetes" {
    secret_suffix = "sso-secrets"
    namespace     = "flux-system"
  }
}

provider "vault" {
  address = var.vault_address
  auth_login_jwt {
    mount = "kubernetes"
    role  = "tf-runner"
    jwt   = fileexists("/var/run/secrets/kubernetes.io/serviceaccount/token") ? file("/var/run/secrets/kubernetes.io/serviceaccount/token") : "not-in-cluster"
  }
}

# --- Client Secret Generation ---
# Each OAuth2 app gets an immutable random secret. Bump rotation_version to rotate.

resource "random_password" "gitea_client_secret" {
  length  = 32
  special = false
  keepers = { rotation_version = var.rotation_version }

  lifecycle {
    ignore_changes = [length, special]
  }
}


resource "random_password" "inventree_client_secret" {
  length  = 32
  special = false
  keepers = { rotation_version = var.rotation_version }

  lifecycle {
    ignore_changes = [length, special]
  }
}

# --- Vault Storage: Basic Credentials ---

resource "vault_kv_secret_v2" "gitea_oidc" {
  mount = "kv"
  name  = "sso/gitea"

  data_json = jsonencode({
    client_id     = "gitea"
    client_secret = random_password.gitea_client_secret.result
  })
}


resource "vault_kv_secret_v2" "inventree_oidc" {
  mount = "kv"
  name  = "sso/inventree"

  data_json = jsonencode({
    client_id     = "inventree"
    client_secret = random_password.inventree_client_secret.result
  })
}
