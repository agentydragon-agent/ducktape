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
    secret_suffix = "ollama-api-key"
    namespace     = "flux-system"
  }
}

provider "vault" {
  address = var.vault_address
  token   = var.vault_token
}

resource "random_password" "api_key" {
  length  = 48
  special = false

  lifecycle {
    ignore_changes = [length, special]
  }
}

resource "vault_kv_secret_v2" "ollama_api_key" {
  mount = "kv"
  name  = "ollama/api-key"

  data_json = jsonencode({
    api_key = random_password.api_key.result
  })

  lifecycle {
    ignore_changes = [data_json]
  }
}
