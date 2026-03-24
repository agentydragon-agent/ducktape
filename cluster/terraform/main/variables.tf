# Cluster configuration (from infrastructure)
variable "cluster_name" {
  description = "Name of the Talos cluster"
  type        = string
  default     = "talos-cluster"
}

variable "cluster_domain" {
  description = "Cluster domain name"
  type        = string
  default     = "allegedly.works"
}

variable "talos_version" {
  description = "Talos version for the cluster"
  type        = string
  default     = "v1.12.3"
}

variable "kubernetes_version" {
  description = "Kubernetes version"
  type        = string
  default     = "1.35.1"
}

# Hetzner Cloud (from infrastructure)
variable "hcloud_token" {
  description = "Hetzner Cloud API token"
  type        = string
  sensitive   = true
}

variable "hetzner_location" {
  description = "Hetzner Cloud location"
  type        = string
  default     = "hil"
}

# Proxmox (shared by persistent-auth + infrastructure + VMs)
variable "proxmox_api_host" {
  description = "Proxmox API host — VLAN IP so CSI pods can reach it"
  type        = string
  default     = "10.2.0.2"
}

variable "proxmox_node_name" {
  description = "Proxmox node name for VM deployment"
  type        = string
  default     = "atlas"
}

# VM configuration (from nixos-dev-env)
variable "storage" {
  description = "Proxmox storage for VM disks"
  type        = string
  default     = "local-zfs"
}

variable "network_bridge" {
  description = "Proxmox network bridge"
  type        = string
  default     = "vmbr4"
}

variable "ssh_public_key" {
  description = "SSH public key (auto-detected if empty)"
  type        = string
  default     = ""
}

variable "rebuild_image" {
  description = "Rebuild NixOS bootstrap image (wyrm2)"
  type        = bool
  default     = false
}

variable "nixos_rebuild" {
  description = "Run nixos-rebuild on wyrm2 after apply"
  type        = bool
  default     = false
}
