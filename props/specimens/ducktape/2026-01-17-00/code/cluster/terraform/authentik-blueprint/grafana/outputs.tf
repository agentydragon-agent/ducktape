output "application_slug" {
  description = "Authentik application slug"
  value       = authentik_application.grafana.slug
}

output "client_id" {
  description = "OAuth2 client ID"
  value       = authentik_provider_oauth2.grafana.client_id
}

output "client_secret" {
  description = "OAuth2 client secret"
  value       = authentik_provider_oauth2.grafana.client_secret
  sensitive   = true
}

output "auth_url" {
  description = "OAuth2 authorization URL"
  value       = "${var.authentik_url}/application/o/authorize/"
}

output "token_url" {
  description = "OAuth2 token URL"
  value       = "${var.authentik_url}/application/o/token/"
}

output "api_url" {
  description = "OAuth2 userinfo URL"
  value       = "${var.authentik_url}/application/o/userinfo/"
}
