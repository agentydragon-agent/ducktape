output "csi_config" {
  description = "Proxmox CSI configuration JSON for use by infrastructure layer"
  value       = jsondecode(data.external.pve_persistent_tokens["csi"].result.config_json)
  sensitive   = true
}

output "terraform_pve_token" {
  description = "Proxmox terraform API token for infrastructure layer"
  value       = jsondecode(data.external.pve_persistent_tokens["terraform"].result.config_json)
  sensitive   = true
}

output "sealed_secrets_keypair" {
  description = "Sealed secrets keypair (terraform-generated)"
  value = {
    private_key = tls_private_key.sealed_secrets.private_key_pem
    certificate = tls_self_signed_cert.sealed_secrets.cert_pem
  }
  sensitive = true
}

output "persistent_auth_ready" {
  description = "Indicates that persistent auth layer is ready"
  value = {
    timestamp = timestamp()
    csi_ready = length(data.external.pve_persistent_tokens) > 0
  }
}

# Talos machine secrets for hybrid cluster
output "talos_machine_secrets" {
  description = "Talos machine secrets (shared across all cluster nodes)"
  value       = talos_machine_secrets.cluster.machine_secrets
  sensitive   = true
}

output "talos_client_configuration" {
  description = "Talos client configuration for talosctl access"
  value       = talos_machine_secrets.cluster.client_configuration
  sensitive   = true
}

# Attic JWT token output
output "attic_jwt_token_base64" {
  description = "Attic JWT token (base64-encoded) for HTTP API authentication"
  value       = local.attic_jwt_token_base64
  sensitive   = true
}

# Sealed secrets outputs
output "sealed_secrets_private_key_pem" {
  description = "Sealed secrets RSA private key (PEM format)"
  value       = tls_private_key.sealed_secrets.private_key_pem
  sensitive   = true
}

output "sealed_secrets_cert_pem" {
  description = "Sealed secrets self-signed certificate (PEM format)"
  value       = tls_self_signed_cert.sealed_secrets.cert_pem
  sensitive   = false
}

# Flux deploy key outputs
output "flux_deploy_public_key" {
  description = "Flux deploy key public key (OpenSSH format) - add to GitHub"
  value       = tls_private_key.flux_deploy.public_key_openssh
}

output "flux_deploy_private_key" {
  description = "Flux deploy key private key (OpenSSH format)"
  value       = tls_private_key.flux_deploy.private_key_openssh
  sensitive   = true
}

# Nix cache outputs
output "nix_cache_public_key" {
  description = "Nix cache signing public key for trusted-public-keys"
  value       = local.nix_cache_keys.public_key
}

output "nix_cache_private_key" {
  description = "Nix cache signing private key"
  value       = local.nix_cache_keys.private_key
  sensitive   = true
}
