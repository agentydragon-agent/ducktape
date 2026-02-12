variable "proxmox_api_host" {
  description = "Proxmox API host - use VLAN IP (10.2.0.2) so CSI pods can reach it without Tailscale DNS"
  type        = string
  default     = "10.2.0.2"
}

variable "proxmox_ssh_host" {
  description = "Proxmox SSH hostname (Tailscale name, NOT the FQDN which routes to VPS)"
  type        = string
  default     = "atlas"
}
