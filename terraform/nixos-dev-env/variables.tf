# Variables for unified Proxmox user + NixOS VM environment

# Proxmox Configuration
variable "proxmox_host" {
  description = "Proxmox host for SSH access"
  type        = string
  default     = "atlas"
}

variable "proxmox_api_host" {
  description = "Proxmox API host FQDN"
  type        = string
  default     = "atlas.agentydragon.com"
}

variable "proxmox_node_name" {
  description = "Proxmox node name for VM deployment"
  type        = string
  default     = "atlas"
}

# User Configuration
variable "username" {
  description = "Username for VM user account"
  type        = string
  default     = "user"
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]*$", var.username))
    error_message = "Username must start with a letter and contain only lowercase letters, numbers, and hyphens."
  }
}

variable "proxmox_username" {
  description = "Username for Proxmox pool user (without @pve, defaults to username)"
  type        = string
  default     = ""
  validation {
    condition     = var.proxmox_username == "" || can(regex("^[a-z][a-z0-9-]*$", var.proxmox_username))
    error_message = "Proxmox username must start with a letter and contain only lowercase letters, numbers, and hyphens."
  }
}

variable "pool_name" {
  description = "Resource pool name (defaults to pool-{proxmox_username})"
  type        = string
  default     = ""
}

variable "user_comment" {
  description = "Comment for Proxmox user"
  type        = string
  default     = "Managed by Terraform"
}

# VM Configuration
variable "vm_name" {
  description = "Name of the NixOS VM (defaults to {username}-nixos)"
  type        = string
  default     = ""
}

variable "vm_id" {
  description = "VM ID in Proxmox (leave 0 for auto-assignment)"
  type        = number
  default     = 0
}

variable "vcpus" {
  description = "Number of vCPUs"
  type        = number
  default     = 4
}

variable "memory_mb" {
  description = "Memory in MB"
  type        = number
  default     = 8192
}

variable "disk_size_gb" {
  description = "Disk size in GB"
  type        = number
  default     = 50
}

variable "network_bridge" {
  description = "Network bridge for VM"
  type        = string
  default     = "vmbr0"
}

variable "storage" {
  description = "Storage location for VM disk"
  type        = string
  default     = "local-zfs"
}

# NixOS Configuration
variable "nixos_channel" {
  description = "NixOS channel (unstable, 24.11, 24.05, etc.)"
  type        = string
  default     = "unstable"
}

variable "ssh_public_key" {
  description = "SSH public key (will use ~/.ssh/id_rsa.pub if not specified)"
  type        = string
  default     = ""
}

variable "ducktape_repo" {
  description = "Ducktape home-manager repository"
  type        = string
  default     = "github:agentydragon/ducktape/main"
}

variable "enable_gui" {
  description = "Enable GNOME desktop with auto-login"
  type        = bool
  default     = true
}

variable "auto_start" {
  description = "Start VM after creation"
  type        = bool
  default     = true
}

variable "custom_env_vars" {
  description = "Custom environment variables to inject into VM"
  type        = map(string)
  default     = {}
  sensitive   = true
}

variable "openai_api_key" {
  description = "OpenAI API key to inject into VM (reads from TF_VAR_openai_api_key or OPENAI_API_KEY env var)"
  type        = string
  default     = ""
  sensitive   = true
}

variable "anthropic_api_key" {
  description = "Anthropic API key to inject into VM (reads from TF_VAR_anthropic_api_key or ANTHROPIC_API_KEY env var)"
  type        = string
  default     = ""
  sensitive   = true
}
