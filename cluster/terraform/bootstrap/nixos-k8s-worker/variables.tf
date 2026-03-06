# NixOS K8s Worker Variables

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

# =============================================================================
# NIXOS/HOME-MANAGER FLAKE CONFIGURATION
# =============================================================================

variable "nixos_flake_url" {
  description = "Flake URL for NixOS system configuration"
  type        = string
  default     = "github:agentydragon/ducktape?dir=nix&ref=devel"
}

variable "home_manager_flake_url" {
  description = "Flake URL for home-manager configuration"
  type        = string
  default     = "github:agentydragon/ducktape?dir=nix&ref=devel"
}

variable "home_manager_host" {
  description = "Home-manager host config name from ducktape flake"
  type        = string
  default     = "nixos-vm"
}
