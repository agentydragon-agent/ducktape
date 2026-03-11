output "ct_id" {
  description = "The container ID"
  value       = proxmox_virtual_environment_container.ct.vm_id
}

output "ct_name" {
  description = "The container name"
  value       = var.ct_name
}
