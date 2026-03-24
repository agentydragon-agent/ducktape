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
    secret_suffix = "grafana-admin"
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

resource "random_password" "admin_password" {
  length  = 32
  special = false
  keepers = { rotation_version = var.rotation_version }

  lifecycle {
    ignore_changes = [length, special]
  }
}

resource "vault_kv_secret_v2" "grafana_admin" {
  mount = "kv"
  name  = "grafana/admin"

  data_json = jsonencode({
    admin_password = random_password.admin_password.result
  })
}
