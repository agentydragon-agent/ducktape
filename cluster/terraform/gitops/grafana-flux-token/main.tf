terraform {
  required_version = ">= 1.0"

  required_providers {
    vault = {
      source  = "hashicorp/vault"
      version = "~> 5.7.0"
    }
    grafana = {
      source  = "grafana/grafana"
      version = "~> 3.22.0"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.35"
    }
  }

  backend "kubernetes" {
    secret_suffix = "grafana-flux-token"
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

data "vault_kv_secret_v2" "grafana_admin" {
  mount = "kv"
  name  = "grafana/admin"
}

provider "grafana" {
  url  = var.grafana_url
  auth = "admin:${data.vault_kv_secret_v2.grafana_admin.data["admin_password"]}"
}

resource "grafana_service_account" "flux" {
  name = "flux-notifications"
  role = "Editor"
}

resource "grafana_service_account_token" "flux" {
  name               = "flux-token"
  service_account_id = grafana_service_account.flux.id
}

resource "kubernetes_secret" "grafana_flux_token" {
  metadata {
    name      = "grafana-flux-token"
    namespace = "flux-system"
  }

  data = {
    token = grafana_service_account_token.flux.key
  }
}
