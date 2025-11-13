# Harbor + Authentik OIDC Configuration Module
# This module configures the OIDC integration between Harbor and Authentik
# with proper dependency ordering to avoid timing issues

terraform {
  required_providers {
    authentik = {
      source  = "goauthentik/authentik"
      version = "~> 2025.10.0"
    }
    harbor = {
      source  = "goharbor/harbor"
      version = "~> 3.10.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6.0"
    }
  }
}

# Client secret is now provided externally via variable

# Configure Authentik OAuth2 Provider first
resource "authentik_provider_oauth2" "harbor" {
  name          = "harbor-terraform-oidc"
  client_id     = "harbor-terraform"
  client_secret = var.harbor_client_secret

  authorization_flow = data.authentik_flow.default_authorization_flow.id
  invalidation_flow  = data.authentik_flow.default_invalidation_flow.id

  allowed_redirect_uris = [
    {
      matching_mode = "strict"
      url           = "${var.harbor_external_url}/c/oidc/callback"
    },
    {
      matching_mode = "strict"
      url           = "${var.harbor_external_url}/c/oidc/login"
    }
  ]

  client_type = "confidential"
  issuer_mode = "per_provider"

  include_claims_in_id_token = true

  property_mappings = [
    data.authentik_property_mapping_provider_scope.openid.id,
    data.authentik_property_mapping_provider_scope.email.id,
    data.authentik_property_mapping_provider_scope.profile.id,
    authentik_property_mapping_provider_scope.groups.id,
    authentik_property_mapping_provider_scope.preferred_username.id,
  ]
}

# Create custom property mappings for Harbor
resource "authentik_property_mapping_provider_scope" "groups" {
  name        = "Harbor Groups Mapping"
  scope_name  = "groups"
  description = "Groups scope for Harbor"
  expression  = "return {'groups': [group.name for group in user.ak_groups.all()]}"
}

resource "authentik_property_mapping_provider_scope" "preferred_username" {
  name        = "Harbor preferred_username Mapping"
  scope_name  = "openid"
  description = "Preferred username mapping for Harbor"
  expression  = "return {'preferred_username': request.user.username}"
}

# Create Harbor admin group
resource "authentik_group" "harbor_admins" {
  name         = var.harbor_admin_group
  is_superuser = false
}

# Create Authentik Application
resource "authentik_application" "harbor" {
  name              = "Harbor Registry (Terraform)"
  slug              = "harbor-terraform"
  protocol_provider = authentik_provider_oauth2.harbor.id

  meta_launch_url  = var.harbor_external_url
  meta_description = "Private container registry with vulnerability scanning."

  # Policy engine mode
  policy_engine_mode = "any"
}

# Configure Harbor OIDC settings (depends on Authentik being ready)
resource "harbor_config_auth" "oidc" {
  auth_mode = "oidc_auth"

  oidc_name          = "Authentik"
  oidc_endpoint      = "${var.authentik_external_url}/application/o/harbor-terraform/"
  oidc_client_id     = authentik_provider_oauth2.harbor.client_id
  oidc_client_secret = authentik_provider_oauth2.harbor.client_secret
  oidc_groups_claim  = "groups"
  oidc_admin_group   = var.harbor_admin_group
  oidc_scope         = "openid,profile,email,groups"
  oidc_user_claim    = "preferred_username"
  oidc_verify_cert   = true
  oidc_auto_onboard  = true

  # Explicit dependency ensures Authentik is configured first
  depends_on = [
    authentik_provider_oauth2.harbor,
    authentik_application.harbor
  ]
}

# Data sources for existing Authentik flows
data "authentik_flow" "default_authorization_flow" {
  slug = "default-provider-authorization-implicit-consent"
}

data "authentik_flow" "default_invalidation_flow" {
  slug = "default-provider-invalidation-flow"
}

# Data sources for existing property mappings
data "authentik_property_mapping_provider_scope" "openid" {
  managed = "goauthentik.io/providers/oauth2/scope-openid"
}

data "authentik_property_mapping_provider_scope" "email" {
  managed = "goauthentik.io/providers/oauth2/scope-email"
}

data "authentik_property_mapping_provider_scope" "profile" {
  managed = "goauthentik.io/providers/oauth2/scope-profile"
}