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
    powerdns_url  = "http://${data.terraform_remote_state.infrastructure.outputs.cluster_vip}:8081"
  }
}