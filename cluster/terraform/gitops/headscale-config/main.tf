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

# Robot user for the ActivityWatch tailscale sidecar
resource "headscale_user" "activitywatch" {
  name = "activitywatch"
}

resource "headscale_pre_auth_key" "activitywatch" {
  user           = headscale_user.activitywatch.id
  reusable       = true
  acl_tags       = ["tag:service"]
  time_to_expire = "8760h"
}

resource "vault_kv_secret_v2" "activitywatch_authkey" {
  mount = "kv"
  name  = "activitywatch/tailscale-authkey"

  data_json = jsonencode({
    authkey = headscale_pre_auth_key.activitywatch.key
  })
}
