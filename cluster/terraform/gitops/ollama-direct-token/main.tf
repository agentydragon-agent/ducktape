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
    secret_suffix = "ollama-direct-token"
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

resource "random_password" "direct_token" {
  length  = 48
  special = false
  keepers = { rotation_version = var.rotation_version }

  lifecycle {
    ignore_changes = [length, special]
  }
}

resource "vault_kv_secret_v2" "ollama_direct_token" {
  mount = "kv"
  name  = "ollama/direct-api-token"

  data_json = jsonencode({
    token = random_password.direct_token.result
  })
}
