terraform {
  required_providers {
    authentik = {
      source = "goauthentik/authentik"
    }
  }
}

# GITOPS MODULE: Shared SSO infrastructure only
# This module manages only shared Authentik resources:
# - Admin groups for services
# - Custom property mappings
# - Automation user with admin access
#
# Per-application OIDC providers are managed by individual blueprints:
# - terraform/authentik-blueprint/{app}/main.tf

# Create admin groups for each service in Authentik
resource "authentik_group" "harbor_admins" {
  name = "harbor-admins"
}

resource "authentik_group" "gitea_admins" {
  name = "gitea-admins"
}

resource "authentik_group" "matrix_admins" {
  name = "matrix-admins"
}

resource "authentik_group" "grafana_admins" {
  name = "grafana-admins"
}

# Create custom property mappings for OIDC
resource "authentik_property_mapping_provider_scope" "groups" {
  name        = "Groups Mapping"
  scope_name  = "groups"
  description = "Groups scope for SSO services"
  expression  = "return {'groups': [group.name for group in user.ak_groups.all()]}"
}

resource "authentik_property_mapping_provider_scope" "preferred_username" {
  name        = "Preferred Username Mapping"
  scope_name  = "openid"
  description = "Preferred username mapping for SSO services"
  expression  = "return {'preferred_username': request.user.username}"
}

# Create automation user with access to all admin groups
resource "authentik_user" "automation" {
  username = "automation"
  name     = "SSO Automation User"
  email    = "automation@test-cluster.agentydragon.com"

  # Add to all admin groups
  groups = [
    authentik_group.harbor_admins.id,
    authentik_group.gitea_admins.id,
    authentik_group.matrix_admins.id,
    authentik_group.grafana_admins.id,
  ]

  is_active = true
}

# Data sources for Authentik default flows and property mappings
data "authentik_flow" "default_authorization_flow" {
  slug = "default-provider-authorization-implicit-consent"
}

data "authentik_flow" "default_invalidation_flow" {
  slug = "default-provider-invalidation-flow"
}

# Default property mappings
data "authentik_property_mapping_provider_scope" "openid" {
  name = "authentik default OAuth Mapping: OpenID 'openid'"
}

data "authentik_property_mapping_provider_scope" "email" {
  name = "authentik default OAuth Mapping: OpenID 'email'"
}

data "authentik_property_mapping_provider_scope" "profile" {
  name = "authentik default OAuth Mapping: OpenID 'profile'"
}
