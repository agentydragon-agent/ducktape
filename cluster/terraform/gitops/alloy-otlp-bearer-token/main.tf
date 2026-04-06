terraform {
  required_version = ">= 1.0"

  required_providers {
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.35"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.7.0"
    }
  }

  backend "kubernetes" {
    secret_suffix = "alloy-otlp-bearer-token"
    namespace     = "flux-system"
  }
}

resource "random_password" "bearer_token" {
  length  = 48
  special = false

  lifecycle {
    ignore_changes = [length, special]
  }
}

# K8s secret in claude-sandbox for Claude hooks to send as Bearer token.
resource "kubernetes_secret" "alloy_otlp_bearer_token_claude" {
  metadata {
    name      = "alloy-otlp-bearer-token"
    namespace = "claude-sandbox"
  }

  data = {
    token = random_password.bearer_token.result
  }
}

# K8s secret in authentik namespace for Authentik worker envFrom.
# The blueprint uses !Env ALLOY_OTLP_BEARER_TOKEN to register the token
# as an Authentik service account API key.
resource "kubernetes_secret" "alloy_otlp_bearer_token_authentik" {
  metadata {
    name      = "alloy-otlp-bearer-token"
    namespace = "authentik"
  }

  data = {
    ALLOY_OTLP_BEARER_TOKEN = random_password.bearer_token.result
  }
}
