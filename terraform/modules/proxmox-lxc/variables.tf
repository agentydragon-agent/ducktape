variable "ct_name" {
  description = "Name of the LXC container"
  type        = string
}

variable "ct_id" {
  description = "Container ID in Proxmox (null for auto-assignment)"
  type        = number
  default     = null
}

variable "privileged" {
  description = "Whether to run as a privileged container (required for k8s workers)"
  type        = bool
  default     = false
}

variable "vcpus" {
  description = "Number of CPU cores"
  type        = number
  default     = 4
}

variable "memory_mb" {
  description = "Memory in MB"
  type        = number
  default     = 4096
}

variable "swap_mb" {
  description = "Swap in MB"
  type        = number
  default     = 0
}

variable "disk_size_gb" {
  description = "Root filesystem size in GB"
  type        = number
  default     = 20
}

variable "template_file_id" {
  description = "Proxmox template file ID (e.g., 'local:vztmpl/lxc-k8s-test.tar.xz')"
  type        = string
}

variable "proxmox_node_name" {
  description = "Proxmox node name"
  type        = string
}

variable "storage" {
  description = "Storage for container rootfs"
  type        = string
}

variable "network_bridge" {
  description = "Network bridge"
  type        = string
}

variable "pool_id" {
  description = "Proxmox pool ID (empty = no pool)"
  type        = string
  default     = ""
}

variable "ssh_public_key" {
  description = "SSH public key for container access"
  type        = string
}

variable "root_password" {
  description = "Root password for console access"
  type        = string
  default     = ""
  sensitive   = true
}

variable "mount_points" {
  description = "Additional mount points for the container"
  type = list(object({
    volume    = string
    path      = string
    size      = optional(string)
    read_only = optional(bool)
  }))
  default = []
}

variable "startup_order" {
  description = "Container startup order"
  type        = number
  default     = 3
}
