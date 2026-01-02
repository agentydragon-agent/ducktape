# INFRASTRUCTURE MODULE VARIABLES


variable "proxmox_node_name" {
  description = "Proxmox node name for VM deployment"
  type        = string
  default     = "atlas"
}

variable "cluster_name" {
  description = "Name of the Talos cluster"
  type        = string
}

variable "cluster_vip" {
  description = "Virtual IP for HA cluster access"
  type        = string
  default     = "10.2.3.1"
}

variable "cluster_networks" {
  description = "Network configuration for cluster nodes"
  type = object({
    gateway         = string
    controller_cidr = string
    worker_cidr     = string
  })
  default = {
    gateway         = "10.2.0.1"
    controller_cidr = "10.2.1.0/24"
    worker_cidr     = "10.2.2.0/24"
  }
}

variable "controller_count" {
  description = "Number of controller nodes"
  type        = number
  default     = 3
}

variable "worker_count" {
  description = "Number of worker nodes"
  type        = number
  default     = 3
}

variable "prefix" {
  description = "Prefix for VM names"
  type        = string
  default     = "talos"
}

variable "vm_id_ranges" {
  description = "VM ID ranges for different node types"
  type = object({
    controller_start = number
    worker_start     = number
  })
  default = {
    controller_start = 1500
    worker_start     = 2000
  }
}

variable "talos_version" {
  description = "Talos version for the cluster"
  type        = string
  default     = "v1.9.1"
}

variable "kubernetes_version" {
  description = "Kubernetes version"
  type        = string
  default     = "1.32.1"
}

variable "headscale_user" {
  description = "Headscale user for pre-auth key generation"
  type        = string
}

variable "headscale_login_server" {
  description = "Headscale login server URL"
  type        = string
  default     = "https://agentydragon.com:8080"
}

variable "enable_flux_bootstrap" {
  description = "Whether to bootstrap Flux during infrastructure deployment"
  type        = bool
  default     = false
}

