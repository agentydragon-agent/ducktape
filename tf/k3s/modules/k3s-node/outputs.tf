output "vm_id" {
  value = proxmox_virtual_environment_vm.node.vm_id
}

output "name" {
  value = proxmox_virtual_environment_vm.node.name
}

output "ip_address" {
  value = var.ip_address
}

output "mac_address" {
  value = try(proxmox_virtual_environment_vm.node.network_device[0].mac_address, "unknown")
}