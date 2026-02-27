terraform {
  required_version = ">= 1.0"

  required_providers {
    headscale = {
      source  = "awlsring/headscale"
      version = "~> 0.5.0"
    }
    vault = {
      source  = "hashicorp/vault"
      version = "~> 5.7.0"
    }
  }

  backend "kubernetes" {
    secret_suffix = "headscale-config"
    namespace     = "flux-system"
  }
}

provider "headscale" {
  endpoint = var.headscale_url
  api_key  = var.headscale_api_key
}

provider "vault" {
  address = var.vault_address
  token   = var.vault_token
}

# Robot user for the Tailscale subnet router
resource "headscale_user" "subnet_router" {
  name = "subnet-router"
}

# Pre-auth key for the subnet router to register with headscale
# ACL policy is managed via ConfigMap (policy.mode: file), not Terraform.
resource "headscale_pre_auth_key" "router" {
  user           = headscale_user.subnet_router.id
  reusable       = true
  acl_tags       = ["tag:router"]
  time_to_expire = "8760h"
}

# Store pre-auth key in Vault for ESO consumption
resource "vault_kv_secret_v2" "router_authkey" {
  mount = "kv"
  name  = "tailscale-router/authkey"
  cas   = 0

  data_json = jsonencode({
    authkey = headscale_pre_auth_key.router.key
  })

  lifecycle {
    ignore_changes = [data_json]
  }
}
