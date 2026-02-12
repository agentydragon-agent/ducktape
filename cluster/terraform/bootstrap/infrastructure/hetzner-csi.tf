# Hetzner Cloud API token secret for the CSI driver.
# The hcloud-csi helm chart (managed by Flux in k8s/hcloud-csi/) expects
# a secret named "hcloud" in kube-system.
resource "kubernetes_secret" "hcloud_csi" {
  metadata {
    name      = "hcloud"
    namespace = "kube-system"
  }

  data = {
    token = var.hcloud_token
  }

  depends_on = [null_resource.cilium_bootstrap]
}


# hcloud-csi helm chart is now managed by Flux (k8s/hcloud-csi/).
# The kubernetes_secret above provides the API token the chart expects.
