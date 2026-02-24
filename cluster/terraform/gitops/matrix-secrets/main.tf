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
    secret_suffix = "matrix-secrets"
    namespace     = "flux-system"
  }
}

provider "vault" {
  address = var.vault_address
  token   = var.vault_token
}

resource "random_password" "signing_key" {
  length  = 43
  special = false

  lifecycle {
    ignore_changes = [length, special]
  }
}

resource "random_password" "registration_secret" {
  length  = 32
  special = false

  lifecycle {
    ignore_changes = [length, special]
  }
}

resource "random_password" "macaroon_secret" {
  length  = 32
  special = false

  lifecycle {
    ignore_changes = [length, special]
  }
}

resource "random_password" "redis_password" {
  length  = 32
  special = false

  lifecycle {
    ignore_changes = [length, special]
  }
}

resource "random_password" "openclaw_bot_password" {
  length  = 32
  special = false

  lifecycle {
    ignore_changes = [length, special]
  }
}

resource "vault_kv_secret_v2" "matrix_secrets" {
  mount = "kv"
  name  = "matrix/secrets"
  cas   = 0

  data_json = jsonencode({
    signing_key           = random_password.signing_key.result
    registration_secret   = random_password.registration_secret.result
    macaroon_secret       = random_password.macaroon_secret.result
    redis_password        = random_password.redis_password.result
    openclaw_bot_password = random_password.openclaw_bot_password.result
  })

  lifecycle {
    ignore_changes = [data_json]
  }
}
