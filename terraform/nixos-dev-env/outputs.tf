# Outputs for NixOS Dev Environment

output "pool_id" {
  description = "Resource pool ID"
  value       = proxmox_virtual_environment_pool.user_pool.pool_id
}

output "username" {
  description = "Proxmox username"
  value       = local.proxmox_username
}

output "vm_name" {
  description = "VM name"
  value       = proxmox_virtual_environment_vm.nixos_vm.name
}

output "vm_id" {
  description = "VM ID"
  value       = proxmox_virtual_environment_vm.nixos_vm.vm_id
}

output "vm_ipv4_addresses" {
  description = "VM IPv4 addresses (requires QEMU agent)"
  value       = proxmox_virtual_environment_vm.nixos_vm.ipv4_addresses
}

output "user_api_token" {
  description = "User API token (sensitive)"
  value       = data.external.user_token.result.token
  sensitive   = true
}

output "instructions" {
  description = "Setup instructions and next steps"
  value       = <<-EOT

    ✅ Environment created successfully!

    Pool: ${proxmox_virtual_environment_pool.user_pool.pool_id}
    User: ${local.proxmox_username}
    VM:   ${proxmox_virtual_environment_vm.nixos_vm.name} (ID: ${proxmox_virtual_environment_vm.nixos_vm.vm_id})

    📋 Next steps:

    1. Wait for VM to boot and cloud-init to complete (~2-3 minutes)

    2. Get VM IP address:
       terraform output vm_ipv4_addresses

    3. SSH into the VM (passwordless):
       ssh ${var.username}@<vm-ip>

    4. Check home-manager status:
       ssh ${var.username}@<vm-ip> 'home-manager generations'

    5. Access Proxmox web UI as the user:
       URL: https://${var.proxmox_api_host}:8006
       User: ${local.proxmox_username}
       Password: (set with: ssh root@${var.proxmox_host} "pveum user password ${local.proxmox_username}")

    6. View user's API token:
       terraform output -raw user_api_token

    ${var.enable_gui ? "7. Access GNOME desktop via Proxmox console (auto-login enabled)" : ""}

    Configuration:
    - NixOS channel: ${var.nixos_channel}
    - Ducktape repo: ${var.ducktape_repo}
    - GUI: ${var.enable_gui ? "enabled (GNOME with auto-login)" : "disabled (headless)"}

    🔐 Environment variables baked into VM:
    - Proxmox: PROXMOX_VE_ENDPOINT, PROXMOX_VE_USERNAME, PROXMOX_VE_API_TOKEN, PROXMOX_POOL_ID
    - LLM API keys: OPENAI_API_KEY, ANTHROPIC_API_KEY (if provided via ./apply.sh)
    - VM can manage itself and create sibling VMs in its pool
  EOT
}
