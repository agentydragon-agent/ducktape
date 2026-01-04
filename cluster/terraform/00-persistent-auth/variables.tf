variable "proxmox_api_host" {
  description = "Proxmox host FQDN (used for HTTPS API and SSH access)"
  type        = string
  default     = "atlas.agentydragon.com"
}

variable "talos_version" {
  description = "Talos Linux version for machine secrets generation"
  type        = string
  default     = "v1.9.5"
}