# Route 53 DNS for allegedly.works — zone records and domain delegation.
#
# All DNS is served by AWS Route 53. No in-cluster DNS authority.
# Update public_gateway_ips when adding/removing public Gateway nodes.

terraform {
  required_version = ">= 1.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

locals {
  domain = "allegedly.works"

  # Public Gateway node IPs. Update when public Gateway-capable nodes change.
  public_gateway_ips = [
    "5.78.142.158",   # talos-vps-cp-0
    "5.78.144.197",   # talos-vps-cp-1
    "147.135.39.162", # talos-kimsufi-worker-0
  ]
}

provider "aws" {
  region = var.aws_region
}

# Read hosted zone to get its NS records for domain delegation
data "aws_route53_zone" "zone" {
  zone_id = var.route53_zone_id
}

import {
  to = aws_route53_record.wildcard
  id = "Z02901943N8ZFQFOD9P5I_*.allegedly.works_A"
}

import {
  to = aws_route53_record.apex
  id = "Z02901943N8ZFQFOD9P5I_allegedly.works_A"
}

# Wildcard A record — all subdomains resolve to VPS nodes
resource "aws_route53_record" "wildcard" {
  #checkov:skip=CKV2_AWS_23:A records point to external public gateway nodes, not AWS resources
  zone_id         = var.route53_zone_id
  name            = "*.${local.domain}"
  type            = "A"
  ttl             = 300
  records         = local.public_gateway_ips
  allow_overwrite = true
}

# Apex A record
resource "aws_route53_record" "apex" {
  #checkov:skip=CKV2_AWS_23:A records point to external public gateway nodes, not AWS resources
  zone_id         = var.route53_zone_id
  name            = local.domain
  type            = "A"
  ttl             = 300
  records         = local.public_gateway_ips
  allow_overwrite = true
}

# Domain registration — delegate to Route 53 nameservers
import {
  to = aws_route53domains_registered_domain.allegedly_works
  id = "allegedly.works"
}

resource "aws_route53domains_registered_domain" "allegedly_works" {
  domain_name = local.domain

  dynamic "name_server" {
    for_each = toset(data.aws_route53_zone.zone.name_servers)
    content {
      name = name_server.value
    }
  }

  lifecycle {
    ignore_changes = [
      transfer_lock, auto_renew,
      admin_contact, billing_contact, registrant_contact, tech_contact,
      admin_privacy, billing_privacy, registrant_privacy, tech_privacy,
    ]
  }
}
