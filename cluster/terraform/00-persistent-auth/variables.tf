variable "proxmox_api_host" {
  description = "Proxmox host (Tailscale MagicDNS name for direct access)"
  type        = string
  default     = "atlas.vps"
}

variable "proxmox_ssh_host" {
  description = "Proxmox SSH hostname (Tailscale name, NOT the FQDN which routes to VPS)"
  type        = string
  default     = "atlas"
}

variable "talos_version" {
  description = "Talos Linux version for machine secrets generation"
  type        = string
  default     = "v1.9.5"
}
