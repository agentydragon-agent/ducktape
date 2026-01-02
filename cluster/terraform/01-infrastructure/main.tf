# LAYER 1: INFRASTRUCTURE
# Infrastructure deployment with ephemeral VM-specific auth
# Includes: PVE terraform auth, VMs, Talos cluster, CNI, storage, Vault
# References: 00-persistent-auth for CSI tokens and sealed secrets

# Proxmox provider using credentials from pve-auth module
provider "proxmox" {
  endpoint = "https://${var.proxmox_api_host}:443/"
  username = "terraform@pve"
  # Parse the token from the JSON config returned by pve-auth module
  api_token = jsondecode(module.pve_auth.terraform_token)["token"]
  insecure  = true # Dev environment with self-signed certs
}

# Kubernetes provider configured with kubeconfig from Talos
provider "kubernetes" {
  host                   = module.infrastructure.cluster_endpoint
  client_certificate     = base64decode(module.infrastructure.kubeconfig_data.client_certificate)
  client_key             = base64decode(module.infrastructure.kubeconfig_data.client_key)
  cluster_ca_certificate = base64decode(module.infrastructure.kubeconfig_data.cluster_ca_certificate)
}

# Helm provider configured with kubeconfig from Talos
provider "helm" {
  kubernetes = {
    host                   = module.infrastructure.cluster_endpoint
    client_certificate     = base64decode(module.infrastructure.kubeconfig_data.client_certificate)
    client_key             = base64decode(module.infrastructure.kubeconfig_data.client_key)
    cluster_ca_certificate = base64decode(module.infrastructure.kubeconfig_data.cluster_ca_certificate)
  }
}

# Write kubeconfig from Talos to file for provider consumption
resource "local_file" "kubeconfig" {
  content  = module.infrastructure.kubeconfig
  filename = "${path.module}/kubeconfig"

  depends_on = [module.infrastructure]
}

# Write talosconfig from Talos to file for CLI access
resource "local_file" "talosconfig" {
  content  = module.infrastructure.talos_config
  filename = "${path.module}/talosconfig.yml"

  depends_on = [module.infrastructure]
}

# Note: Flux provider removed from Layer 1 - Flux bootstrap moved to Layer 2

# PVE-AUTH MODULE: Creates Proxmox users and API tokens
module "pve_auth" {
  source = "../modules/pve-auth"

  proxmox_host     = var.proxmox_host
  proxmox_api_host = var.proxmox_api_host
}

# INFRASTRUCTURE MODULE: Creates Talos cluster and CNI (no Flux in Layer 1)
module "infrastructure" {
  source     = "../modules/infrastructure"
  depends_on = [module.pve_auth]

  proxmox_node_name = var.proxmox_node_name

  # Cluster configuration
  cluster_name       = var.cluster_name
  cluster_vip        = var.cluster_vip
  cluster_networks   = var.cluster_networks
  controller_count   = var.controller_count
  worker_count       = var.worker_count
  prefix             = var.prefix
  vm_id_ranges       = var.vm_id_ranges
  talos_version      = var.talos_version
  kubernetes_version = var.kubernetes_version

  # Headscale/Tailscale integration
  headscale_user         = var.headscale_user
  headscale_login_server = var.headscale_login_server

  # Disable Flux bootstrap in Layer 1 - moved to Layer 2 for proper dependency handling
  enable_flux_bootstrap = false
}

# CILIUM CNI: Install after Kubernetes API is ready
# Moved from infrastructure module to properly handle kubeconfig dependency chain

# SEALED SECRETS: Apply stable keypair after Kubernetes API is ready
# Moved from infrastructure module to properly handle kubeconfig dependency chain

# Reference persistent auth layer for CSI configuration
data "terraform_remote_state" "persistent_auth" {
  backend = "local"

  config = {
    path = "../00-persistent-auth/terraform.tfstate"
  }
}

# STORAGE: CSI sealed secrets generated in 00-persistent-auth layer
# No module needed here - persistent auth layer handles sealed secret generation
# CSI driver deployed by GitOps using sealed secrets from persistent layer
#
# NOTE: PVC cleanup handled by destroy provisioner on helm_release.cilium_bootstrap
# (see cilium.tf) - runs while cluster is still accessible during CNI teardown