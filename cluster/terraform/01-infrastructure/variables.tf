# LAYER 1 VARIABLES - Hybrid Infrastructure
# 2x Hetzner VPS + 1x Proxmox home node

# ============================================================================
# CLUSTER CONFIGURATION
# ============================================================================

variable "cluster_name" {
  description = "Name of the Talos cluster"
  type        = string
  default     = "talos-cluster"
}

variable "cluster_domain" {
  description = "Cluster domain name"
  type        = string
  default     = "test-cluster.agentydragon.com"
}

variable "talos_version" {
  description = "Talos version for the cluster"
  type        = string
  default     = "v1.11.0"
}

variable "kubernetes_version" {
  description = "Kubernetes version"
  type        = string
  default     = "1.32.0"
}

# ============================================================================
# HETZNER CLOUD CONFIGURATION
# ============================================================================

variable "hcloud_token" {
  description = "Hetzner Cloud API token (from HCLOUD_TOKEN env var)"
  type        = string
  sensitive   = true
}

variable "hetzner_location" {
  description = "Hetzner Cloud location (hil = Hillsboro, OR)"
  type        = string
  default     = "hil"
}

# ============================================================================
# PROXMOX CONFIGURATION (Phase 2 - home node)
# ============================================================================

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

# Home node network configuration
variable "home_node_ip" {
  description = "Static IP address for home Proxmox node"
  type        = string
  default     = "10.2.1.1"
}

variable "home_node_gateway" {
  description = "Gateway for home Proxmox node"
  type        = string
  default     = "10.2.0.1"
}
