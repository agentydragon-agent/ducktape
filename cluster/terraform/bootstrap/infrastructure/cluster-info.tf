# Create ConfigMap with VPS IPs for in-cluster Terraform to consume
# This enables tofu-controller to manage DNS records with current VPS IPs
# Note: Uses kube-system namespace (always exists) since flux-system is created later
resource "kubernetes_config_map" "cluster_info" {
  metadata {
    name      = "cluster-info"
    namespace = "kube-system"
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
    null_resource.wait_for_nodes_ready, # Cluster must be fully ready
  ]
}
