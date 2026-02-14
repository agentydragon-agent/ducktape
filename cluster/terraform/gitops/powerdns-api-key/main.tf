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
    secret_suffix = "powerdns-api-key"
    namespace     = "flux-system"
  }
}

provider "vault" {
  address = var.vault_address
  token   = var.vault_token
}

resource "random_password" "powerdns_api_key" {
  length  = 32
  special = false

  lifecycle {
    ignore_changes = [length, special]
  }
}

resource "vault_kv_secret_v2" "powerdns_api_key" {
  mount = "kv"
  name  = "powerdns/api-key"
  cas   = 0

  data_json = jsonencode({
    api_key = random_password.powerdns_api_key.result
  })

  lifecycle {
    ignore_changes = [data_json]
  }
}
