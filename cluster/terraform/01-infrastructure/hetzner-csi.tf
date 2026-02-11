# Hetzner Cloud CSI Driver
# Enables persistent volumes using Hetzner Block Storage
# https://github.com/hetznercloud/csi-driver
#
# Uses helm CLI instead of helm_release resource due to Helm provider v3
# plan consistency bugs with OpenTofu.
# https://github.com/hashicorp/terraform-provider-helm/pull/1739

# Secret for CSI driver to access Hetzner API
# Note: The hcloud-csi helm chart expects a secret named "hcloud" by default
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

resource "null_resource" "hcloud_csi" {
  depends_on = [
    kubernetes_secret.hcloud_csi,
    null_resource.cilium_bootstrap,
  ]

  provisioner "local-exec" {
    environment = {
      KUBECONFIG = local_file.kubeconfig.filename
    }
    command = <<-EOT
      set -e
      helm repo add hcloud https://charts.hetzner.cloud && helm repo update hcloud
      helm upgrade --install hcloud-csi hcloud/hcloud-csi \
        --version 2.10.1 \
        --namespace kube-system \
        --values - <<'VALUES'
      storageClasses:
        - name: hcloud-volumes
          defaultStorageClass: true
          reclaimPolicy: Retain
      controller:
        nodeSelector:
          topology.kubernetes.io/region: hetzner
      node:
        nodeSelector:
          topology.kubernetes.io/region: hetzner
      VALUES
    EOT
  }
}
