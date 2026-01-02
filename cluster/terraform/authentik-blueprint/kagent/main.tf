terraform {
  required_version = ">= 1.0"

  required_providers {
    authentik = {
      source = "goauthentik/authentik"
    }
    http = {
      source = "hashicorp/http"
    }
    null = {
      source = "hashicorp/null"
    }
  }

  backend "kubernetes" {
    secret_suffix = "authentik-blueprint-kagent"
    namespace     = "flux-system"
  }
}

provider "authentik" {
  url   = var.authentik_url
  token = var.authentik_token
}

# Data source for invalidation flow (required in provider ~> 2025.10.0)
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

# Kagent Proxy Provider for Forward Auth
resource "authentik_provider_proxy" "kagent" {
  name                = "kagent"
  external_host       = var.kagent_url
  mode                = "forward_single"
  authentication_flow = data.authentik_flow.default_authentication.id
  authorization_flow  = data.authentik_flow.default_authorization_flow.id
  invalidation_flow   = data.authentik_flow.default_invalidation.id

  # Forward auth doesn't need internal host
  access_token_validity = "hours=1"
}

# Kagent Application
resource "authentik_application" "kagent" {
  name              = "Kagent"
  slug              = "kagent"
  protocol_provider = authentik_provider_proxy.kagent.id
  meta_description  = "Kubernetes Agent Platform - AI agents with K8s integration"
  meta_launch_url   = var.kagent_url
  open_in_new_tab   = true
}

# Policy Binding - Allow admins group
resource "authentik_policy_binding" "kagent_access" {
  target = authentik_application.kagent.uuid
  group  = data.authentik_group.admins.id
  order  = 0
}

# Query the existing Kubernetes service connection (created by Authentik chart)
data "authentik_service_connection_kubernetes" "local" {
  name = "Local Kubernetes Cluster"
}

# Create dedicated outpost for Kagent (fully declarative, no import needed)
resource "authentik_outpost" "kagent" {
  name               = "kagent-outpost"
  type               = "proxy"
  service_connection = data.authentik_service_connection_kubernetes.local.id

  # Assign Kagent provider
  protocol_providers = [
    authentik_provider_proxy.kagent.id
  ]

  # Configure authentik_host for OAuth redirects (fixes http://0.0.0.0:9000 issue)
  config = jsonencode({
    authentik_host         = var.authentik_url
    authentik_host_browser = ""
  })
}
