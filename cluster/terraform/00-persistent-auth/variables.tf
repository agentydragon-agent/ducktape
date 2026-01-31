variable "proxmox_api_host" {
  description = "Proxmox host FQDN (used for HTTPS API access via nginx reverse proxy)"
  type        = string
  default     = "atlas.agentydragon.com"
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
