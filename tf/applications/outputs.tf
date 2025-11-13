# Outputs for Application Configuration

output "oidc_configuration_summary" {
  description = "Summary of the OIDC configuration"
  value       = module.harbor_authentik_oidc.configuration_summary
}

output "authentik_provider_id" {
  description = "ID of the Authentik OAuth2 provider"
  value       = module.harbor_authentik_oidc.authentik_provider_id
}

output "authentik_application_slug" {
  description = "Slug of the Authentik application"
  value       = module.harbor_authentik_oidc.authentik_application_slug
}

output "harbor_auth_mode" {
  description = "Harbor authentication mode"
  value       = module.harbor_authentik_oidc.harbor_auth_mode
}

output "vault_integration" {
  description = "Vault integration details"
  sensitive   = true
  value = {
    vault_address = var.vault_address
    secret_path   = "${vault_kv_secret_v2.harbor_secrets.mount}/${vault_kv_secret_v2.harbor_secrets.name}"
    managed_by    = "terraform"
    created_at    = vault_kv_secret_v2.harbor_secrets.data_json
  }
}

# Sensitive outputs for debugging (use with terraform output -raw)
output "harbor_client_secret" {
  description = "Generated Harbor client secret (for debugging)"
  value       = random_password.harbor_client_secret.result
  sensitive   = true
}

output "harbor_admin_password" {
  description = "Generated Harbor admin password (for debugging)"
  value       = random_password.harbor_admin_password.result
  sensitive   = true
}

output "vault_secret_path" {
  description = "Full path to Harbor secrets in Vault"
  value       = "${vault_kv_secret_v2.harbor_secrets.mount}/${vault_kv_secret_v2.harbor_secrets.name}"
}