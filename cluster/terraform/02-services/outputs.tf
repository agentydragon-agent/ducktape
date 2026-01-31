# LAYER 2 OUTPUTS - Service deployment status
# These outputs are consumed by layer 3 for service configuration

# Flux deployment status
output "flux_deployed" {
  description = "Status of Flux deployment"
  value = {
    flux_namespace = flux_bootstrap_git.cluster.namespace
    timestamp      = timestamp()
  }
}

# Service endpoints for layer 3 configuration
output "service_endpoints" {
  description = "Service endpoints for API configuration"
  value = {
    authentik_url = "https://authentik.${data.terraform_remote_state.infrastructure.outputs.cluster_domain}"
    harbor_url    = "https://harbor.${data.terraform_remote_state.infrastructure.outputs.cluster_domain}"
    gitea_url     = "https://gitea.${data.terraform_remote_state.infrastructure.outputs.cluster_domain}"
    # PowerDNS accessible via MetalLB at 10.2.3.3 (Proxmox network) or via K8s service
    powerdns_url = "http://powerdns-api.dns-system.svc.cluster.local:8081"
  }
}
