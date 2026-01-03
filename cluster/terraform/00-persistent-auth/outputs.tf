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