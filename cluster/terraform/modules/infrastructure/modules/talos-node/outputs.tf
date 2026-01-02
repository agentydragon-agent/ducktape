output "vm_id" {
  description = "Proxmox VM ID"
  value       = proxmox_virtual_environment_vm.vm.id
}

output "ip_address" {
  description = "Node IP address"
  value       = var.ip_address
}

output "node_name" {
  description = "Node name"
  value       = var.node_name
}

output "schematic_id" {
  description = "Image Factory schematic ID"
  value       = talos_image_factory_schematic.schematic.id
}


