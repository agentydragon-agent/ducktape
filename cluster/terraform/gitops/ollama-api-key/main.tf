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
  auth_login_jwt {
    mount = "kubernetes"
    role  = "tf-runner"
    jwt   = fileexists("/var/run/secrets/kubernetes.io/serviceaccount/token") ? file("/var/run/secrets/kubernetes.io/serviceaccount/token") : "not-in-cluster"
  }
}

resource "random_password" "api_key" {
  length  = 48
  special = false
  keepers = { rotation_version = var.rotation_version }

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
}
