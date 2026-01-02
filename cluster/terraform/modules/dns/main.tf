terraform {
  required_providers {
    powerdns = {
      source = "pan-net/powerdns"
    }
    vault = {
      source = "hashicorp/vault"
    }
    random = {
      source = "hashicorp/random"
    }
  }
}

# DNS MODULE: PowerDNS management and zone configuration
# Manages PowerDNS API keys and cluster zone records

# Generate secure PowerDNS API key
resource "random_password" "powerdns_api_key" {
  length  = 32
  special = false

  lifecycle {
    ignore_changes = [length, special]
  }
}

# Store API key in Vault
resource "vault_generic_secret" "powerdns_api_key" {
  path = "kv/powerdns/api"

  data_json = jsonencode({
    api_key = random_password.powerdns_api_key.result
  })

  lifecycle {
    ignore_changes = [data_json]
  }
}

# Create the main zone for the cluster
resource "powerdns_zone" "cluster_zone" {
  name        = var.cluster_domain
  kind        = "Master"
  nameservers = ["ns1.${var.cluster_domain}"]

  depends_on = [vault_generic_secret.powerdns_api_key]
}

# Add DNS records for cluster services
resource "powerdns_record" "cluster_api" {
  zone    = powerdns_zone.cluster_zone.name
  name    = "api.${var.cluster_domain}"
  type    = "A"
  ttl     = 300
  records = [var.cluster_vip]
}

resource "powerdns_record" "ingress" {
  zone    = powerdns_zone.cluster_zone.name
  name    = "*.${var.cluster_domain}"
  type    = "A"
  ttl     = 300
  records = [var.ingress_pool]
}