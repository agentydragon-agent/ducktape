# K8s Worker (Proxmox) Variables

# =============================================================================
# PROXMOX CONFIGURATION
# =============================================================================

variable "proxmox_host" {
  description = "Proxmox host for SSH access"
  type        = string
  default     = "atlas"
}

variable "proxmox_api_host" {
  description = "Proxmox API host:port"
  type        = string
  default     = "10.0.182.102:8006"
}

variable "proxmox_node_name" {
  description = "Proxmox node name for VM deployment"
  type        = string
  default     = "atlas"
}

variable "storage" {
  description = "Storage location for VM disks"
  type        = string
  default     = "local-zfs"
}

variable "network_bridge" {
  description = "Network bridge for VMs"
  type        = string
  default     = "vmbr0"
}

# =============================================================================
# VM CONFIGURATION
# =============================================================================

variable "username" {
  description = "Username for VM user account"
  type        = string
  default     = "user"
}

variable "ssh_public_key" {
  description = "SSH public key (auto-detected from ~/.ssh if not specified)"
  type        = string
  default     = ""
}
