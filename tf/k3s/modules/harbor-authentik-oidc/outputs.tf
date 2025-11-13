# Outputs for Harbor + Authentik OIDC Configuration

output "harbor_client_secret" {
  description = "Client secret for Harbor OIDC (provided externally)"
  value       = var.harbor_client_secret
  sensitive   = true
}

output "authentik_provider_id" {
  description = "ID of the created Authentik OAuth2 provider"
  value       = authentik_provider_oauth2.harbor.id
}

output "authentik_application_slug" {
  description = "Slug of the created Authentik application"
  value       = authentik_application.harbor.slug
}

output "harbor_auth_mode" {
  description = "Harbor authentication mode"
  value       = harbor_config_auth.oidc.auth_mode
}

output "configuration_summary" {
  description = "Summary of OIDC configuration"
  value = {
    authentik_provider_endpoint = "${var.authentik_external_url}/application/o/harbor/"
    harbor_callback_url         = "${var.harbor_external_url}/c/oidc/callback"
    client_id                   = authentik_provider_oauth2.harbor.client_id
    admin_group                 = var.harbor_admin_group
    configured_at               = timestamp()
  }
}