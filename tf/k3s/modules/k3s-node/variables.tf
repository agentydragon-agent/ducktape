variable "node_name" {
  description = "Name of the k3s node"
  type        = string
}

variable "vm_id" {
  description = "Proxmox VM ID"
  type        = number
}

variable "ip_address" {
  description = "IP address with CIDR (e.g., 10.0.200.202/16)"
  type        = string
}

variable "k3s_type" {
  description = "k3s installation type"
  type        = string
  validation {
    condition     = contains(["bootstrap_server", "join_server", "agent"], var.k3s_type)
    error_message = "k3s_type must be 'bootstrap_server', 'join_server', or 'agent'"
  }
}

variable "proxmox_node" {
  description = "Proxmox node name"
  type        = string
  default     = "atlas"
}

variable "vm_config" {
  description = "VM configuration"
  type = object({
    cpu_cores      = number
    cpu_sockets    = number
    cpu_units      = number
    memory         = number
    disk_size      = number
    disk_storage   = string
    network_bridge = string
    gateway        = string
    dns_servers    = list(string)
    template_id    = number
  })
}


variable "cloud_init_content" {
  description = "Cloud-init user data content (optional)"
  type        = string
  default     = null
}