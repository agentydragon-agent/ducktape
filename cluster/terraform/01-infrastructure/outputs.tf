# LAYER 1 OUTPUTS - Infrastructure components
# These outputs are consumed by subsequent layers via terraform_remote_state

# PVE-AUTH outputs
output "proxmox_tokens_created" {
  description = "Whether Proxmox tokens were created successfully"
  value       = module.pve_auth.terraform_token != null
  sensitive   = true
}

# INFRASTRUCTURE outputs
output "kubeconfig" {
  description = "Generated kubeconfig for cluster access"
  value       = module.infrastructure.kubeconfig
  sensitive   = true
}

output "kubeconfig_data" {
  description = "Kubeconfig data components for provider configuration"
  value       = module.infrastructure.kubeconfig_data
  sensitive   = true
}

output "talos_config" {
  description = "Talos client configuration"
  value       = module.infrastructure.talos_config
  sensitive   = true
}

output "cluster_endpoint" {
  description = "Kubernetes API cluster endpoint"
  value       = module.infrastructure.cluster_endpoint
}

output "cluster_domain" {
  description = "Cluster domain name for service configuration"
  value       = var.cluster_domain
}

output "cluster_vip" {
  description = "Cluster VIP for service endpoints"
  value       = var.cluster_vip
}

output "cluster_nodes" {
  description = "Cluster node information"
  value = {
    controlplane_ips = module.infrastructure.controlplane_ips
    worker_ips       = module.infrastructure.worker_ips
  }
}

# Infrastructure readiness indicator
output "infrastructure_ready" {
  description = "Indicates infrastructure layer is complete and ready for service deployment"
  value = {
    cluster_ready   = module.infrastructure.cluster_endpoint != null
    persistent_auth = data.terraform_remote_state.persistent_auth.outputs.persistent_auth_ready.csi_ready
    timestamp       = timestamp()
  }
}