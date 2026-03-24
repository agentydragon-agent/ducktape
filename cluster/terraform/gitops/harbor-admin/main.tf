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
    secret_suffix = "harbor-admin"
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

resource "random_password" "harbor_admin" {
  length  = 32
  special = false

  lifecycle {
    ignore_changes = [length, special]
  }
}

resource "vault_kv_secret_v2" "harbor_admin_password" {
  mount = "kv"
  name  = "harbor/admin"
  cas   = 0

  data_json = jsonencode({
    password = random_password.harbor_admin.result
  })

  lifecycle {
    ignore_changes = [data_json]
  }
}
