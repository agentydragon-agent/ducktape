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
    secret_suffix = "atuin-secrets"
    namespace     = "flux-system"
  }
}

provider "vault" {
  address = var.vault_address
  token   = var.vault_token
}

resource "random_password" "postgres_password" {
  length  = 32
  special = false

  lifecycle {
    ignore_changes = [length, special]
  }
}

resource "vault_kv_secret_v2" "atuin_secrets" {
  mount = "kv"
  name  = "atuin/secrets"
  cas   = 0

  data_json = jsonencode({
    postgres_password = random_password.postgres_password.result
  })

  lifecycle {
    ignore_changes = [data_json]
  }
}
