# PVE-AUTH MODULE OUTPUTS

output "terraform_token" {
  description = "Terraform API token for Proxmox provider (ephemeral)"
  value       = data.external.pve_tokens["terraform"].result.config_json
  sensitive   = true
}

# CSI config moved to 00-persistent-auth layer