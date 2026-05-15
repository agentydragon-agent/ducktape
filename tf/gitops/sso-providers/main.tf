import {
  to = authentik_application.gitea
  id = "gitea"
}

import {
  to = authentik_application.grafana
  id = "grafana"
}

import {
  to = authentik_application.harbor
  id = "harbor"
}

import {
  to = authentik_application.headlamp
  id = "headlamp"
}

import {
  to = authentik_application.inventree
  id = "inventree"
}

import {
  to = authentik_application.kagent
  id = "kagent"
}

import {
  to = authentik_application.matrix
  id = "matrix"
}

import {
  to = authentik_application.openclaw_agent
  id = "openclaw-agent"
}

import {
  to = authentik_brand.allegedly_works
  id = "436580f9-b7c7-4ed6-a692-4377862248d6"
}

import {
  to = authentik_group.authentik_admins
  id = "a13f0970-ab4b-477f-959d-99db796f1db8"
}

import {
  to = authentik_group.grafana_admins
  id = "72bd66e7-eafd-4fab-b4af-a49f19c88c61"
}

import {
  to = authentik_group.study_casino
  id = "8e7462ca-d4e2-4f81-8c54-217bcd6bb645"
}

import {
  to = authentik_policy_binding.gitea_admins
  id = "00b668d9-5f24-407a-b798-8bb9ed0908ba"
}

import {
  to = authentik_policy_binding.grafana_admins
  id = "191ad1de-a9c5-4a89-97b9-928964a834d9"
}

import {
  to = authentik_policy_binding.harbor_admins
  id = "c16a7255-1a2c-4f04-8330-69646c920026"
}

import {
  to = authentik_policy_binding.headlamp_admins
  id = "658591c1-f8a8-4acb-bd77-c00f5e49e18e"
}

import {
  to = authentik_policy_binding.inventree_admins
  id = "8b615618-eca6-4d27-acde-587d1f6ae82d"
}

import {
  to = authentik_policy_binding.kagent_admins
  id = "dc7ec96d-fe82-4a1d-aa45-46fe1b9e5c2d"
}

import {
  to = authentik_policy_binding.matrix_admins
  id = "1b0effe0-d7e2-4306-811f-7af6e7d39b79"
}

import {
  to = authentik_policy_binding.openclaw_agent_sa
  id = "3d7b3f14-2f66-46c0-ba7a-dd3f35f4b927"
}

import {
  to = authentik_policy_binding.study_casino_admins
  id = "c706a3a6-64f8-493a-af29-4f212ff242ff"
}

import {
  to = authentik_policy_binding.study_casino_users
  id = "433e79f8-6796-480c-b545-333137e9db53"
}

import {
  to = authentik_provider_oauth2.gitea
  id = "70"
}

import {
  to = authentik_provider_oauth2.grafana
  id = "60"
}

import {
  to = authentik_provider_oauth2.harbor
  id = "67"
}

import {
  to = authentik_provider_oauth2.headlamp
  id = "59"
}

import {
  to = authentik_provider_oauth2.inventree
  id = "69"
}

import {
  to = authentik_provider_oauth2.kagent
  id = "120"
}

import {
  to = authentik_provider_oauth2.matrix
  id = "68"
}

import {
  to = authentik_provider_oauth2.openclaw_agent
  id = "58"
}

import {
  to = authentik_provider_oauth2.study_casino
  id = "114"
}

import {
  to = authentik_source_oauth.google
  id = "google"
}

import {
  to = authentik_token.claude_api
  id = "claude-diagnostics-api-token"
}

import {
  to = authentik_user.agentydragon
  id = "19"
}

import {
  to = authentik_user.auragon
  id = "20"
}

import {
  to = authentik_user.claude_service_account
  id = "57"
}

import {
  to = authentik_user.openclaw_agent_sa
  id = "18"
}

import {
  to = kubernetes_secret.airlock_secrets
  id = "authentik/airlock-secrets"
}

import {
  to = kubernetes_secret.claude_authentik_token
  id = "authentik/claude-authentik-api-token"
}

import {
  to = kubernetes_secret.gitea_oauth
  id = "authentik/gitea-oauth-client-secret"
}

import {
  to = kubernetes_secret.grafana_oidc
  id = "authentik/grafana-oidc-config"
}

import {
  to = kubernetes_secret.harbor_oidc
  id = "authentik/harbor-oauth-client-secret"
}

import {
  to = kubernetes_secret.headlamp_oidc
  id = "authentik/headlamp-oidc-secret"
}

import {
  to = kubernetes_secret.inventree_sso_providers
  id = "authentik/inventree-sso-providers"
}

import {
  to = kubernetes_secret.kagent_oauth2_proxy
  id = "authentik/kagent-oauth2-proxy"
}

import {
  to = kubernetes_secret.matrix_oidc
  id = "authentik/matrix-oidc-config"
}

import {
  to = kubernetes_secret.study_casino_oidc
  id = "study-casino/study-casino-oidc"
}


# SSO OAuth2 providers managed by Terraform.
#
# Replaces blueprint+Vault+ESO chain for Grafana, Headlamp, and
# OpenClaw-Agent. TF creates the Authentik provider (which owns the
# client_secret), then writes K8s secrets into the authentik namespace.
# Reflector mirrors them to consumer namespaces.

terraform {
  required_version = ">= 1.0"

  required_providers {
    authentik = {
      source  = "goauthentik/authentik"
      version = "~> 2026.2"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.35"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  backend "kubernetes" {
    secret_suffix = "sso-providers"
    namespace     = "flux-system"
  }
}

data "kubernetes_secret" "authentik_bootstrap" {
  metadata {
    name      = "authentik-bootstrap"
    namespace = "authentik"
  }
}

data "kubernetes_secret" "authentik_user_password" {
  metadata {
    name      = "authentik-user-password"
    namespace = "authentik"
  }
}

data "kubernetes_secret" "auragon_google_email" {
  metadata {
    name      = "authentik-auragon-google-email"
    namespace = "authentik"
  }
}

provider "authentik" {
  url   = var.authentik_url_override != "" ? var.authentik_url_override : "http://authentik-server.authentik.svc.cluster.local"
  token = data.kubernetes_secret.authentik_bootstrap.data["AUTHENTIK_BOOTSTRAP_TOKEN"]
}

# --- Shared data sources ---

data "authentik_flow" "implicit_consent" {
  slug = "default-provider-authorization-implicit-consent"
}

data "authentik_flow" "invalidation" {
  slug = "default-provider-invalidation-flow"
}

data "authentik_group" "admins" {
  name = "authentik Admins"
}

data "authentik_user" "akadmin" {
  username = "akadmin"
}

resource "authentik_user" "agentydragon" {
  username = "agentydragon"
  name     = "Rai"
  email    = "agentydragon@gmail.com"
  password = data.kubernetes_secret.authentik_user_password.data["USER_PASSWORD"]
}

# Google OAuth-only user. Email is SOPS-encrypted — sourced from
# authentik-auragon-google-email secret so it stays out of plaintext git.
# Matches via user_matching_mode = "email_link" on authentik_source_oauth.google.
resource "authentik_user" "auragon" {
  username = "auragon"
  name     = "auragon"
  email    = data.kubernetes_secret.auragon_google_email.data["AURAGON_GOOGLE_EMAIL"]
}

resource "authentik_group" "authentik_admins" {
  name         = "authentik Admins"
  is_superuser = true
  users        = [data.authentik_user.akadmin.pk, tonumber(authentik_user.agentydragon.id)]
}

resource "authentik_group" "grafana_admins" {
  name  = "Grafana Admins"
  users = [tonumber(authentik_user.agentydragon.id)]
}

resource "authentik_group" "study_casino" {
  name = "study-casino"
  users = [
    tonumber(authentik_user.agentydragon.id),
    tonumber(authentik_user.auragon.id),
  ]
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

# Custom airlock scope mappings (defined in airlock-scope-mappings.yaml blueprint)
data "authentik_property_mapping_provider_scope" "propose" {
  scope_name = "propose"
}

data "authentik_property_mapping_provider_scope" "read" {
  scope_name = "read"
}
