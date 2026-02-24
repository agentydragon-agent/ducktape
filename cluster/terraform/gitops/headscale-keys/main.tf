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
    secret_suffix = "headscale-keys"
    namespace     = "flux-system"
  }
}

provider "vault" {
  address = var.vault_address
  token   = var.vault_token
}

resource "random_id" "wireguard_key" {
  byte_length = 32
}

resource "random_id" "noise_key" {
  byte_length = 32
}

resource "random_id" "derp_key" {
  byte_length = 32
}

resource "vault_kv_secret_v2" "headscale_keys" {
  mount = "kv"
  name  = "headscale/keys"
  cas   = 0

  data_json = jsonencode({
    wireguard_key = random_id.wireguard_key.hex
    noise_key     = "privkey:${random_id.noise_key.hex}"
    derp_key      = "privkey:${random_id.derp_key.hex}"
  })

  lifecycle {
    ignore_changes = [data_json]
  }
}
