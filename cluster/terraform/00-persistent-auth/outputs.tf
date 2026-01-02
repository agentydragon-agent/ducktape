output "csi_config" {
  description = "Proxmox CSI configuration JSON for use by infrastructure layer"
  value       = jsondecode(data.external.pve_persistent_tokens["csi"].result.config_json)
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