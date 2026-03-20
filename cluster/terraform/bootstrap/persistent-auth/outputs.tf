output "csi_config" {
  description = "Proxmox CSI configuration for use by infrastructure layer"
  value       = local.pve_token_configs["csi"]
  sensitive   = true
}

output "terraform_pve_token" {
  description = "Proxmox terraform API token for infrastructure layer"
  value       = local.pve_token_configs["terraform"]
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
    csi_ready = length(proxmox_virtual_environment_user_token.persistent) > 0
  }
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

# Nebula mesh PKI
output "nebula_ca_cert" {
  description = "Nebula CA public certificate (safe to share)"
  value       = data.local_file.nebula_ca_crt.content
}

output "nebula_node_certs" {
  description = "Per-node Nebula certificates and keys"
  value = {
    for name, _ in local.nebula_nodes : name => {
      cert = data.local_file.nebula_node_crt[name].content
      key  = data.local_sensitive_file.nebula_node_key[name].content
    }
  }
  sensitive = true
}
