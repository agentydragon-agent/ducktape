terraform {
  required_version = ">= 1.0"

  required_providers {
    authentik = {
      source  = "goauthentik/authentik"
      version = "~> 2025.12.0"
    }
  }

  backend "kubernetes" {
    secret_suffix = "authentik-blueprint-loki"
    namespace     = "flux-system"
  }
}

provider "authentik" {
  url   = var.authentik_url
  token = var.authentik_token
}

data "authentik_flow" "default_invalidation" {
  slug = "default-provider-invalidation-flow"
}

data "authentik_flow" "default_authorization_flow" {
  slug = "default-provider-authorization-implicit-consent"
}

data "authentik_flow" "default_authentication" {
  slug = "default-authentication-flow"
}

data "authentik_group" "admins" {
  name = "authentik Admins"
}

# Loki Proxy Provider — outpost proxies traffic and handles auth
resource "authentik_provider_proxy" "loki" {
  name                  = "loki"
  external_host         = var.loki_url
  internal_host         = "http://loki-stack.loki.svc.cluster.local:3100"
  mode                  = "proxy"
  authentication_flow   = data.authentik_flow.default_authentication.id
  authorization_flow    = data.authentik_flow.default_authorization_flow.id
  invalidation_flow     = data.authentik_flow.default_invalidation.id
  access_token_validity = "hours=1"
}

resource "authentik_application" "loki" {
  name              = "Loki"
  slug              = "loki"
  protocol_provider = authentik_provider_proxy.loki.id
  meta_description  = "Grafana Loki Log Aggregation"
  meta_launch_url   = var.loki_url
  open_in_new_tab   = true
}

# Restrict access to admins
resource "authentik_policy_binding" "loki_access" {
  target = authentik_application.loki.uuid
  group  = data.authentik_group.admins.id
  order  = 0
}

data "authentik_service_connection_kubernetes" "local" {
  name = "Local Kubernetes Cluster"
}

# Dedicated outpost — deploys proxy pods in authentik namespace
resource "authentik_outpost" "loki" {
  name               = "loki-outpost"
  type               = "proxy"
  service_connection = data.authentik_service_connection_kubernetes.local.id

  protocol_providers = [
    authentik_provider_proxy.loki.id
  ]

  config = jsonencode({
    authentik_host         = var.authentik_url
    authentik_host_browser = "https://auth.allegedly.works"
  })
}
