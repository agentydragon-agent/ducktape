# Create ConfigMap with VPS IPs for in-cluster Terraform to consume
# This enables tofu-controller to manage DNS records with current VPS IPs
# Note: Uses kube-system namespace (always exists) since flux-system is created later
resource "kubernetes_config_map" "cluster_info" {
  metadata {
    name      = "cluster-info"
    namespace = "kube-system"
    annotations = {
      # Reflector copies to external-dns (--default-targets env vars)
      # and flux-system (Flux postBuild substituteFrom for Gateway annotation)
      "reflector.v1.k8s.emberstack.com/reflection-allowed"            = "true"
      "reflector.v1.k8s.emberstack.com/reflection-allowed-namespaces" = "external-dns,flux-system"
      "reflector.v1.k8s.emberstack.com/reflection-auto-enabled"       = "true"
      "reflector.v1.k8s.emberstack.com/reflection-auto-namespaces"    = "external-dns,flux-system"
    }
  }

  data = merge(
    {
      # CP nodes only — used by dns-records for NS glue, API endpoint, nameserver registration
      vps_cp_nodes = jsonencode({
        for k, v in hcloud_server.vps : k => {
          ip   = v.ipv4_address
          name = v.name
        } if local.vps_nodes[k].role == "controlplane"
      })
      # All VPS nodes — used by dns-records for Nebula lighthouse DNS
      vps_nodes = jsonencode({
        for k, v in hcloud_server.vps : k => {
          ip   = v.ipv4_address
          name = v.name
        }
      })
      # JSON list of all VPS IPs
      vps_ips = jsonencode([for k, v in hcloud_server.vps : v.ipv4_address])
      # Comma-separated for Flux postBuild substitution (Gateway target annotation)
      vps_ips_csv = join(",", [for k, v in hcloud_server.vps : v.ipv4_address])
    },
    # Flat keys for direct env var injection (e.g., external-dns --default-targets)
    { for k, v in hcloud_server.vps : "vps_ip_${k}" => v.ipv4_address },
  )

  depends_on = [
    null_resource.wait_for_nodes_ready, # Cluster must be fully ready
  ]
}
