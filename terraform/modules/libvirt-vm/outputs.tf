# Libvirt VM Module Outputs

output "vm_name" {
  description = "The VM name"
  value       = libvirt_domain.vm.name
}

output "ip_addresses" {
  description = "The IP addresses of the VM (from DHCP lease)"
  value       = data.libvirt_domain_interface_addresses.vm.interfaces[*].addrs[*].addr
}
