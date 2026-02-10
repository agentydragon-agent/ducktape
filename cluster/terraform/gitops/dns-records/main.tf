terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    powerdns = {
      source  = "pan-net/powerdns"
      version = "~> 1.5"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.0"
    }
  }
}

# Read VPS IPs from ConfigMap created by infrastructure terraform
# Note: ConfigMap is in kube-system (always exists during infra layer)
data "kubernetes_config_map" "cluster_info" {
  metadata {
    name      = "cluster-info"
    namespace = "kube-system"
  }
}

locals {
  # Parse JSON structure: {"vps0": {"ip": "...", "name": "..."}, "vps1": {...}}
  vps_nodes = jsondecode(data.kubernetes_config_map.cluster_info.data["vps_nodes"])
  domain    = "allegedly.works"

  # Map VPS nodes to nameserver numbers: vps0 -> ns1, vps1 -> ns2, etc.
  ns_records = {
    for k, v in local.vps_nodes : k => {
      ns_name = "ns${tonumber(substr(k, 3, -1)) + 1}" # vps0 -> ns1, vps1 -> ns2
      ip      = v.ip
    }
  }
}

# AWS provider configured via environment variables from secret
provider "aws" {
  region = var.aws_region
  # AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY from environment
}

# PowerDNS provider
provider "powerdns" {
  server_url = var.powerdns_url
  api_key    = var.powerdns_api_key
}

# Route 53 glue records (at registrar level)
resource "aws_route53_record" "ns_glue" {
  for_each = local.ns_records
  #checkov:skip=CKV2_AWS_23:Glue records point to external Hetzner VPS servers, not AWS resources

  zone_id = var.route53_zone_id
  name    = "${each.value.ns_name}.${local.domain}"
  type    = "A"
  ttl     = 300
  records = [each.value.ip]
}

# PowerDNS NS A records (within the zone)
resource "powerdns_record" "ns" {
  for_each = local.ns_records

  zone    = "${local.domain}."
  name    = "${each.value.ns_name}.${local.domain}."
  type    = "A"
  ttl     = 3600
  records = [each.value.ip]
}
