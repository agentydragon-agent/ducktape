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
    secret_suffix = "authentik-token"
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

# Authentik API/Bootstrap token (single token for both bootstrap and API access)
resource "random_password" "authentik_api_token" {
  length  = 64
  special = false

  lifecycle {
    ignore_changes = [length, special]
  }
}

resource "vault_kv_secret_v2" "authentik_api_token" {
  mount = "kv"
  name  = "sso/client-secrets"
  cas   = 0

  data_json = jsonencode({
    authentik_api_token = random_password.authentik_api_token.result
  })

  lifecycle {
    ignore_changes = [data_json]
  }
}
