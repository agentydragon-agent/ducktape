# Outputs for NixOS Dev Environment

output "pool_id" {
  description = "Resource pool ID"
  value       = proxmox_virtual_environment_pool.user_pool.pool_id
}

output "username" {
  description = "Proxmox username"
  value       = local.proxmox_username
}

output "user_api_token" {
  description = "User API token (sensitive)"
  value       = data.external.user_token.result.token
  sensitive   = true
}

# Dev Workstation outputs
output "dev_workstation" {
  description = "Dev workstation VM info"
  value = {
    name           = module.dev_workstation.vm_name
    id             = module.dev_workstation.vm_id
    ipv4_addresses = module.dev_workstation.ipv4_addresses
  }
}

output "instructions" {
  description = "Setup instructions and next steps"
  value       = <<-EOT

    ✅ Environment created successfully!

    Pool: ${proxmox_virtual_environment_pool.user_pool.pool_id}
    User: ${local.proxmox_username}

    VMs:
    - dev-workstation (ID: ${module.dev_workstation.vm_id})

    📋 Next steps:

    1. Wait for VMs to boot and cloud-init to complete (~2-3 minutes)

    2. Get VM IP addresses:
       terraform output dev_workstation

    3. SSH into a VM (passwordless):
       ssh ${var.username}@<vm-ip>

    4. Check home-manager status:
       ssh ${var.username}@<vm-ip> 'home-manager generations'

    5. Access Proxmox web UI as the user:
       URL: https://${var.proxmox_api_host}:8006
       User: ${local.proxmox_username}
       Password: (set with: ssh root@${var.proxmox_host} "pveum user password ${local.proxmox_username}")

    Configuration:
    - NixOS channel: ${var.nixos_channel}
    - Home-manager flake: ${var.home_manager_flake_url}#${var.home_manager_host}

    🔐 Environment variables baked into VMs:
    - Proxmox: PROXMOX_VE_ENDPOINT, PROXMOX_VE_USERNAME, PROXMOX_VE_API_TOKEN, PROXMOX_POOL_ID
    - LLM API keys: OPENAI_API_KEY, ANTHROPIC_API_KEY (if provided via ./apply.sh)
  EOT
}
