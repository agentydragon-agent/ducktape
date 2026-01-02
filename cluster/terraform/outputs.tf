# CONSOLIDATED OUTPUTS from all modules

# PVE-AUTH outputs
output "proxmox_tokens_created" {
  description = "Whether Proxmox tokens were created successfully"
  value       = module.pve_auth.terraform_token != null
}

# INFRASTRUCTURE outputs
output "kubeconfig" {
  description = "Generated kubeconfig for cluster access"
  value       = module.infrastructure.kubeconfig
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

output "cluster_nodes" {
  description = "Cluster node information"
  value = {
    controlplane_ips = module.infrastructure.controlplane_ips
    worker_ips       = module.infrastructure.worker_ips
  }
}

# STORAGE outputs removed - CSI configuration handled in 00-persistent-auth layer

# GITOPS outputs
output "sso_configured" {
  description = "Whether SSO services were configured"
  value = {
    admin_groups = module.gitops.admin_groups
  }
  sensitive = true
}

# DNS outputs - conditional based on whether DNS module is enabled
output "dns_configured" {
  description = "DNS zone and records configured"
  value = length(module.dns) > 0 ? {
    cluster_zone = module.dns[0].cluster_zone
    dns_records  = module.dns[0].dns_records
    } : {
    cluster_zone = "not-configured"
    dns_records  = []
  }
}