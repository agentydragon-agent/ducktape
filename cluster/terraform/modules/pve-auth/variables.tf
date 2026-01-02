# PVE-AUTH MODULE VARIABLES

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