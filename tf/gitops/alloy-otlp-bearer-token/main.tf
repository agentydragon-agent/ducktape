terraform {
  required_version = ">= 1.0"

  required_providers {
    authentik = {
      source  = "goauthentik/authentik"
      version = "~> 2025.10"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.35"
    }
  }

  backend "kubernetes" {
    secret_suffix = "alloy-otlp-bearer-token"
    namespace     = "flux-system"
  }
}

# Read the Authentik bootstrap token from the K8s Secret (populated by ESO from Vault).
data "kubernetes_secret" "authentik_bootstrap" {
  metadata {
    name      = "authentik-bootstrap"
    namespace = "authentik"
  }
}

provider "authentik" {
  url   = "http://authentik-server.authentik.svc.cluster.local"
  token = data.kubernetes_secret.authentik_bootstrap.data["AUTHENTIK_BOOTSTRAP_TOKEN"]
}

data "authentik_flow" "authentication" {
  slug = "default-authentication-flow"
}

data "authentik_flow" "implicit_consent" {
  slug = "default-provider-authorization-implicit-consent"
}

data "authentik_flow" "invalidation" {
  slug = "default-provider-invalidation-flow"
}

data "authentik_certificate_key_pair" "self_signed" {
  name = "authentik Self-signed Certificate"
}

data "authentik_property_mapping_provider_scope" "openid" {
  managed = "goauthentik.io/providers/oauth2/scope-openid"
}

data "authentik_property_mapping_provider_scope" "email" {
  managed = "goauthentik.io/providers/oauth2/scope-email"
}

data "authentik_property_mapping_provider_scope" "profile" {
  managed = "goauthentik.io/providers/oauth2/scope-profile"
}

# External OTLP/HTTP ingestion endpoint used by Claude Code hooks to send traces
# to Grafana Alloy, with Authentik proxy outpost validating Bearer JWTs minted
# by a dedicated client_credentials OAuth2 provider. Keeping this separate from
# kubectl-sandbox-client-credentials ensures leaked tracing credentials do not
# grant Kubernetes access.
#
# The proxy provider predates this module and already exists in Authentik, so
# tofu-controller must adopt it into state before it can update
# jwt_federation_providers declaratively.

import {
  to = authentik_provider_proxy.alloy_otlp
  id = "19"
}

import {
  to = authentik_application.alloy_otlp
  id = "alloy-otlp"
}

resource "authentik_provider_proxy" "alloy_otlp" {
  name                  = "alloy-otlp"
  external_host         = "https://alloy-otlp.allegedly.works"
  internal_host         = "http://alloy.monitoring.svc.cluster.local:4318"
  mode                  = "proxy"
  authentication_flow   = data.authentik_flow.authentication.id
  authorization_flow    = data.authentik_flow.implicit_consent.id
  invalidation_flow     = data.authentik_flow.invalidation.id
  access_token_validity = "hours=24"

  jwt_federation_providers = [authentik_provider_oauth2.alloy_otlp_client_credentials.id]
}

resource "authentik_application" "alloy_otlp" {
  name              = "Alloy OTLP"
  slug              = "alloy-otlp"
  protocol_provider = authentik_provider_proxy.alloy_otlp.id
  meta_description  = "Grafana Alloy OTLP ingestion endpoint for external clients (Claude hooks, etc.)"
  open_in_new_tab   = false
}

# Dedicated client_credentials provider for Alloy tracing JWTs.
resource "authentik_provider_oauth2" "alloy_otlp_client_credentials" {
  name        = "alloy-otlp-client-credentials"
  client_id   = "alloy-otlp-client-credentials"
  client_type = "confidential"

  authorization_flow = data.authentik_flow.implicit_consent.id
  invalidation_flow  = data.authentik_flow.invalidation.id
  signing_key        = data.authentik_certificate_key_pair.self_signed.id

  issuer_mode                = "per_provider"
  include_claims_in_id_token = true
  access_token_validity      = "hours=1080"

  property_mappings = [
    data.authentik_property_mapping_provider_scope.openid.id,
    data.authentik_property_mapping_provider_scope.email.id,
    data.authentik_property_mapping_provider_scope.profile.id,
  ]
}

resource "authentik_application" "alloy_otlp_client_credentials" {
  name              = "alloy-otlp-client-credentials"
  slug              = "alloy-otlp-client-credentials"
  protocol_provider = authentik_provider_oauth2.alloy_otlp_client_credentials.id
  meta_description  = "Machine-to-machine OTLP tracing access for Claude hooks"
}

resource "authentik_user" "alloy_otlp_client_credentials" {
  username = "alloy-otlp-client-credentials"
  name     = "Alloy OTLP client_credentials service account"
  type     = "service_account"
  path     = "goauthentik.io/service-accounts"
}

resource "authentik_policy_binding" "alloy_otlp_client_credentials" {
  target = authentik_application.alloy_otlp_client_credentials.uuid
  user   = authentik_user.alloy_otlp_client_credentials.id
  order  = 0
}

# Pre-create the service-account user shape that Authentik otherwise
# auto-materializes for client_credentials grants. The kubectl-sandbox provider
# proved that issued tokens authenticate as this username, but reading it as a
# data source makes first-plan bootstrap fail before the OAuth2 provider exists.
resource "authentik_user" "alloy_otlp_cc_auto" {
  username = "ak-alloy-otlp-client-credentials-client_credentials"
  name     = "Autogenerated user from application alloy-otlp-client-credentials (client credentials)"
  type     = "service_account"
  path     = "goauthentik.io/apps/alloy-otlp-client-credentials"
}

resource "authentik_policy_binding" "alloy_otlp_cc_auto_user" {
  target = authentik_application.alloy_otlp_client_credentials.uuid
  user   = authentik_user.alloy_otlp_cc_auto.id
  order  = 1
}

# The outpost authenticates bearer JWTs from alloy-otlp-client-credentials
# against the proxy application. Bind both the stable service account identity
# and Authentik's auto-created client_credentials user to keep the mapping
# explicit.
resource "authentik_policy_binding" "alloy_otlp_proxy_user" {
  target = authentik_application.alloy_otlp.uuid
  user   = authentik_user.alloy_otlp_client_credentials.id
  order  = 0
}

resource "authentik_policy_binding" "alloy_otlp_proxy_auto_user" {
  target = authentik_application.alloy_otlp.uuid
  user   = authentik_user.alloy_otlp_cc_auto.id
  order  = 1
}

# In-cluster client credentials for the Alloy JWT rotator CronJob. The job
# mints short-lived-ish OIDC access tokens, commits them SOPS-encrypted to git,
# and session startup exports DUCKTAPE_OTEL_BEARER_TOKEN from that file.
resource "kubernetes_secret" "alloy_otlp_client_credentials" {
  metadata {
    name      = "alloy-otlp-client-credentials"
    namespace = "agents-infra"
    annotations = {
      description = "client_id + client_secret for alloy-otlp-client-credentials OIDC provider (mounted by alloy-otlp-jwt-rotation CronJob)"
    }
  }

  data = {
    client_id     = authentik_provider_oauth2.alloy_otlp_client_credentials.client_id
    client_secret = authentik_provider_oauth2.alloy_otlp_client_credentials.client_secret
  }
}
