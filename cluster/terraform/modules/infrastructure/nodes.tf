# Define all nodes in a single place
locals {
  # Global configuration shared by all nodes
  global_config = {
    headscale_login_server = var.headscale_login_server
    headscale_user         = var.headscale_user
    headscale_server       = local.ssh_targets.headscale
    proxmox_server         = local.ssh_targets.proxmox
  }

  # Define node types and their configuration in a single data structure
  # Memory: All nodes can use up to 12GB (vm_defaults.memory_mb), but have different
  # guaranteed minimums via balloon target (memory_dedicated_mb)
  node_types = {
    controlplane = {
      count               = var.controller_count
      vm_start            = var.vm_id_ranges.controller_start
      cidr                = var.cluster_networks.controller_cidr
      memory_dedicated_mb = 3072 # 3GB balloon target (guaranteed minimum)
    }
    worker = {
      count               = var.worker_count
      vm_start            = var.vm_id_ranges.worker_start
      cidr                = var.cluster_networks.worker_cidr
      memory_dedicated_mb = 6144 # 6GB balloon target (guaranteed minimum)
    }
  }

  # Generate all nodes dynamically from node_types configuration
  nodes = merge([
    for node_type, config in local.node_types : {
      for i in range(config.count) : "${node_type}${i}" => {
        type                = node_type
        vm_id               = config.vm_start + i
        ip_address          = cidrhost(config.cidr, i + 1)
        memory_dedicated_mb = config.memory_dedicated_mb
      }
    }
  ]...)

  # Group nodes by type dynamically as lists
  nodes_by_type = {
    for node_type in keys(local.node_types) : node_type => [
      for k, v in local.nodes : merge(v, { name = k }) if v.type == node_type
    ]
  }

  # Validation: ensure generated nodes don't have overlapping VM IDs or IP addresses
  validate_vm_ids = (
    length([for node in local.nodes : node.vm_id]) == length(toset([for node in local.nodes : node.vm_id])) ?
    true : tobool("VM ID collision detected")
  )
  validate_ip_addresses = (
    length([for node in local.nodes : node.ip_address]) == length(toset([for node in local.nodes : node.ip_address])) ?
    true : tobool("IP address collision detected")
  )

  # DRY endpoints - auto-computed from configuration
  cluster_vip_endpoint = "https://${var.cluster_vip}:6443"

  # Shared node configuration (DRY)
  shared_node_config = {
    # Proxmox-specific config
    gateway           = var.cluster_networks.gateway
    proxmox_node_name = var.proxmox_node_name
    prefix            = var.prefix

    # Additional config
    cluster_vip   = var.cluster_vip
    global_config = local.global_config

    # Tailscale config (DRY)
    tailscale_base_args  = "--login-server=${local.global_config.headscale_login_server} --accept-routes"
    tailscale_route_args = "--advertise-routes=10.2.3.0/27 --advertise-tags=tag:cluster-router"
  }

  # Talos machine configuration base (splattable object)
  talos_machine_config_base = {
    cluster_name       = var.cluster_name
    cluster_endpoint   = local.cluster_vip_endpoint # All nodes use VIP
    machine_secrets    = talos_machine_secrets.talos
    talos_version      = var.talos_version
    kubernetes_version = var.kubernetes_version
    examples           = false
    docs               = false
  }
}

# Generate machine secrets once for the entire cluster
resource "talos_machine_secrets" "talos" {
  talos_version = var.talos_version
}

# Create each node using the module (DRY configuration)
module "nodes" {
  for_each = local.nodes
  source   = "./modules/talos-node"

  # Node-specific configuration
  node_name           = each.key
  node_type           = each.value.type
  vm_id               = each.value.vm_id
  ip_address          = each.value.ip_address
  memory_dedicated_mb = each.value.memory_dedicated_mb

  # Pass both shared config and talos base config
  shared_config     = local.shared_node_config
  talos_config_base = local.talos_machine_config_base

}

# Bootstrap the cluster using first controller
resource "talos_machine_bootstrap" "talos" {
  client_configuration = talos_machine_secrets.talos.client_configuration
  endpoint             = local.nodes_by_type.controlplane[0].ip_address
  node                 = local.nodes_by_type.controlplane[0].ip_address
  depends_on           = [module.nodes]
}

# Note: Removed problematic talos_cluster_health check
# The provider was checking for all nodes including workers, but workers
# can't join Kubernetes without CNI. Instead we use explicit bash-based
# API readiness check in cilium.tf that only verifies controller API access.

# Generate kubeconfig for cluster access
resource "talos_cluster_kubeconfig" "talos" {
  client_configuration = talos_machine_secrets.talos.client_configuration
  endpoint             = local.nodes_by_type.controlplane[0].ip_address
  node                 = local.nodes_by_type.controlplane[0].ip_address
  depends_on           = [talos_machine_bootstrap.talos]
}

# Generate talos client config
data "talos_client_configuration" "talos" {
  cluster_name         = var.cluster_name
  client_configuration = talos_machine_secrets.talos.client_configuration
  endpoints            = [for node in local.nodes_by_type.controlplane : node.ip_address]

  # Use validation locals to ensure no collisions
  lifecycle {
    postcondition {
      condition     = local.validate_vm_ids
      error_message = "VM ID collision detected in node configuration"
    }
    postcondition {
      condition     = local.validate_ip_addresses
      error_message = "IP address collision detected in node configuration"
    }
  }
}
