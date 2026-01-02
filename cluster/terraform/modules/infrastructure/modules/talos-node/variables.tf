# Node configuration
variable "node_name" {
  description = "Name of the node (e.g., c0, w0)"
  type        = string
}

variable "node_type" {
  description = "Talos machine type: controlplane or worker"
  type        = string
  validation {
    condition     = contains(["controlplane", "worker"], var.node_type)
    error_message = "node_type must be either 'controlplane' or 'worker'."
  }
}

variable "vm_id" {
  description = "Proxmox VM ID"
  type        = number
}

variable "ip_address" {
  description = "Static IP address for this node"
  type        = string
}

variable "memory_dedicated_mb" {
  description = "Dedicated (minimum guaranteed) memory in MB"
  type        = number
}

# Shared configuration for proxmox/tailscale/etc
variable "shared_config" {
  description = "Shared configuration for all nodes (non-talos)"
  type = object({
    gateway           = string
    proxmox_node_name = string
    prefix            = string
    cluster_vip       = string
    global_config = object({
      headscale_login_server = string
      headscale_user         = string
      headscale_server       = string
      proxmox_server         = string
    })
    tailscale_base_args  = string
    tailscale_route_args = string
  })
  sensitive = true
}

# Talos machine configuration base (for merging)
variable "talos_config_base" {
  description = "Base talos machine configuration (splattable)"
  type = object({
    cluster_name       = string
    cluster_endpoint   = string
    machine_secrets    = any
    talos_version      = string
    kubernetes_version = string
    examples           = bool
    docs               = bool
  })
  sensitive = true
}
