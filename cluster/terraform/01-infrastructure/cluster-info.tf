# Create ConfigMap with VPS IPs for in-cluster Terraform to consume
# This enables tofu-controller to manage DNS records with current VPS IPs
resource "kubernetes_config_map" "cluster_info" {
  metadata {
    name      = "cluster-info"
    namespace = "flux-system"
  }

  data = {
    # JSON structure for easy parsing: {"vps0": {"ip": "...", "name": "..."}, ...}
    vps_nodes = jsonencode({
      for k, v in hcloud_server.vps : k => {
        ip   = v.ipv4_address
        name = v.name
      }
    })
  }

  depends_on = [
    talos_machine_bootstrap.cluster, # Cluster must be up
  ]
}
