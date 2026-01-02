# GITOPS MODULE OUTPUTS
# Only outputs for shared infrastructure resources

output "admin_groups" {
  description = "Created admin groups for services"
  value = {
    harbor_admins  = authentik_group.harbor_admins.id
    gitea_admins   = authentik_group.gitea_admins.id
    matrix_admins  = authentik_group.matrix_admins.id
    grafana_admins = authentik_group.grafana_admins.id
  }
}

output "property_mappings" {
  description = "Custom property mapping IDs for use by OIDC providers"
  value = {
    groups             = authentik_property_mapping_provider_scope.groups.id
    preferred_username = authentik_property_mapping_provider_scope.preferred_username.id
  }
}

output "default_flows" {
  description = "Default Authentik flow IDs"
  value = {
    authorization = data.authentik_flow.default_authorization_flow.id
    invalidation  = data.authentik_flow.default_invalidation_flow.id
  }
}

output "default_scopes" {
  description = "Default OIDC scope mapping IDs"
  value = {
    openid  = data.authentik_property_mapping_provider_scope.openid.id
    email   = data.authentik_property_mapping_provider_scope.email.id
    profile = data.authentik_property_mapping_provider_scope.profile.id
  }
}
