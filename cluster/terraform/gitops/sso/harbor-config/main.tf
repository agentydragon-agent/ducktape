terraform {
  required_version = ">= 1.0"

  required_providers {
    harbor = {
      source  = "goharbor/harbor"
      version = "~> 3.11"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.38.0"
    }
    vault = {
      source  = "hashicorp/vault"
      version = "~> 5.7.0"
    }
  }

  backend "kubernetes" {
    secret_suffix = "harbor-oidc-config"
    namespace     = "flux-system"
  }
}

provider "vault" {
  address         = var.vault_address
  token           = var.vault_token
  skip_tls_verify = true
}

# Harbor admin password from ESO-synced K8s secret
data "kubernetes_secret" "harbor_admin_password" {
  metadata {
    name      = "harbor-admin-initial"
    namespace = "harbor"
  }
}

provider "harbor" {
  url      = var.harbor_url
  username = "admin"
  password = data.kubernetes_secret.harbor_admin_password.data["HARBOR_ADMIN_PASSWORD"]
}

# Read OIDC credentials stored by harbor SSO provider module
data "vault_kv_secret_v2" "harbor_oidc" {
  mount = "kv"
  name  = "sso/harbor"
}

# Configure Harbor OIDC authentication with Authentik
resource "harbor_config_auth" "oidc" {
  auth_mode = "oidc_auth"

  oidc_name          = "Authentik"
  oidc_endpoint      = "${var.authentik_url}/application/o/harbor/"
  oidc_client_id     = jsondecode(data.vault_kv_secret_v2.harbor_oidc.data_json)["client_id"]
  oidc_client_secret = jsondecode(data.vault_kv_secret_v2.harbor_oidc.data_json)["client_secret"]
  oidc_scope         = "openid,email,profile"
  oidc_verify_cert   = true

  oidc_auto_onboard = true
  oidc_user_claim   = "preferred_username"
  oidc_groups_claim = "groups"
  oidc_admin_group  = "harbor-admins"
}
