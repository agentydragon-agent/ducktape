# Variables for NixOS Dev Environment
# Shared infrastructure + defaults for VM modules

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
  default     = "atlas:8006"
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
# SSH CONFIGURATION
# =============================================================================

variable "ssh_public_key" {
  description = "SSH public key (auto-detected from ~/.ssh if not specified)"
  type        = string
  default     = ""
}

# =============================================================================
# IMAGE BUILD & PROVISIONING
# =============================================================================

variable "rebuild_image" {
  description = "Rebuild and re-upload the bootstrap NixOS image. Only needed for initial VM creation or bootstrap config changes."
  type        = bool
  default     = false
}

variable "nixos_rebuild" {
  description = "Run nixos-rebuild switch on wyrm2 after VM is ready. Deploys the full wyrm2 config from GitHub."
  type        = bool
  default     = false
}
