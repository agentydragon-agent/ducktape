# ============================================================================
# KUBECONFIG & ACCESS
# ============================================================================

output "kubeconfig" {
  description = "Generated kubeconfig for cluster access (patched with real endpoint)"
  value = replace(
    talos_cluster_kubeconfig.cluster.kubeconfig_raw,
    "https://localhost:7445",
    "https://${hcloud_server.vps[local.bootstrap_node].ipv4_address}:6443"
  )
  sensitive = true
}

output "kubeconfig_data" {
  description = "Kubeconfig data components for provider configuration"
  value = {
    host                   = "https://${hcloud_server.vps[local.bootstrap_node].ipv4_address}:6443"
    client_certificate     = talos_cluster_kubeconfig.cluster.kubernetes_client_configuration.client_certificate
    client_key             = talos_cluster_kubeconfig.cluster.kubernetes_client_configuration.client_key
    cluster_ca_certificate = talos_cluster_kubeconfig.cluster.kubernetes_client_configuration.ca_certificate
  }
  sensitive = true
}

output "talos_config" {
  description = "Talos client configuration"
  value       = data.talos_client_configuration.cluster.talos_config
  sensitive   = true
}

# ============================================================================
# CLUSTER INFORMATION
# ============================================================================

output "cluster_endpoint" {
  description = "Kubernetes API cluster endpoint"
  value       = "https://${hcloud_server.vps[local.bootstrap_node].ipv4_address}:6443"
}

output "cluster_domain" {
  description = "Cluster domain name for service configuration"
  value       = var.cluster_domain
}

output "cluster_nodes" {
  description = "Cluster node information"
  value = {
    vps_ips     = { for k, v in hcloud_server.vps : k => v.ipv4_address }
    proxmox_ips = { for k, v in local.proxmox_nodes : k => v.ip }
  }
}

output "vps_node_ips" {
  description = "Public IP addresses of VPS nodes"
  value = {
    for k, v in hcloud_server.vps : k => {
      ipv4 = v.ipv4_address
      ipv6 = v.ipv6_address
    }
  }
}

output "bootstrap_node_ip" {
  description = "IP of the bootstrap node (primary API endpoint)"
  value       = hcloud_server.vps[local.bootstrap_node].ipv4_address
}


output "expected_node_count" {
  description = "Expected number of nodes in the cluster"
  value       = local.expected_node_count
}

# ============================================================================
# FLUX
# ============================================================================

output "flux_deployed" {
  description = "Status of Flux deployment"
  value = {
    flux_namespace = flux_bootstrap_git.cluster.namespace
    timestamp      = timestamp()
  }
}

output "service_endpoints" {
  description = "Service endpoints for API configuration"
  value = {
    authentik_url = "https://authentik.${var.cluster_domain}"
    harbor_url    = "https://harbor.${var.cluster_domain}"
    gitea_url     = "https://gitea.${var.cluster_domain}"
    powerdns_url  = "http://powerdns-api.dns-system.svc.cluster.local:8081"
  }
}

# ============================================================================
# WYRM2 (NixOS dev env)
# ============================================================================

output "wyrm2" {
  description = "Wyrm2 VM info"
  value = {
    name           = module.wyrm2.vm_name
    id             = module.wyrm2.vm_id
    ipv4_addresses = module.wyrm2.ipv4_addresses
  }
}

output "instructions" {
  description = "Setup instructions and next steps"
  value       = <<-EOT

    VM: wyrm2 (ID: ${module.wyrm2.vm_id})

    Workflows:

    Initial provisioning (build bootstrap image + deploy full config):
      tofu apply -var="rebuild_image=true" -var="nixos_rebuild=true"

    VM hardware changes only (CPU, RAM, disks):
      tofu apply

    Deploy NixOS config changes:
      tofu apply -var="nixos_rebuild=true"
      # or manually:
      ssh wyrm2 'sudo nixos-rebuild switch --flake github:agentydragon/ducktape?ref=devel#wyrm2'

    After deploying, approve the kubelet CSR to join the cluster:
      kubectl get csr
      kubectl certificate approve <csr-name>
  EOT
}

# ============================================================================
# PERSISTENT AUTH
# ============================================================================

output "flux_deploy_public_key" {
  description = "Flux deploy key public key (OpenSSH format) - add to GitHub"
  value       = data.sops_file.flux_deploy_key.data["public_key"]
  sensitive   = true
}

# ============================================================================
# K8S WORKER JOIN CREDENTIALS (consumed by k8s-worker-proxmox / k8s-worker-libvirt)
# ============================================================================

output "k8s_ca_cert" {
  description = "Kubernetes CA certificate (PEM, base64-encoded)"
  value       = talos_machine_secrets.cluster.machine_secrets.certs.k8s.cert
  sensitive   = true
}

output "k8s_bootstrap_token" {
  description = "Kubernetes bootstrap token for kubelet TLS bootstrap"
  value       = talos_machine_secrets.cluster.machine_secrets.secrets.bootstrap_token
  sensitive   = true
}
