# Hetzner Cloud CSI Driver
# Enables persistent volumes using Hetzner Block Storage
# https://github.com/hetznercloud/csi-driver

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

  depends_on = [helm_release.cilium_bootstrap]
}

# Add Hetzner helm repo
resource "null_resource" "add_hcloud_repo" {
  provisioner "local-exec" {
    command = "helm repo add hcloud https://charts.hetzner.cloud && helm repo update hcloud"
  }

  depends_on = [null_resource.wait_for_k8s_api]
}

# Deploy Hetzner CSI driver
resource "helm_release" "hcloud_csi" {
  name       = "hcloud-csi"
  repository = "https://charts.hetzner.cloud"
  chart      = "hcloud-csi"
  namespace  = "kube-system"
  version    = "2.10.1"

  values = [
    yamlencode({
      storageClasses = [{
        name                = "hcloud-volumes"
        defaultStorageClass = true
        reclaimPolicy       = "Retain"
      }]
      # Restrict CSI controller to Hetzner VPS nodes (needs metadata service)
      controller = {
        nodeSelector = {
          "topology.kubernetes.io/region" = "hetzner"
        }
      }
      # Restrict CSI node pods to Hetzner VPS nodes only
      node = {
        nodeSelector = {
          "topology.kubernetes.io/region" = "hetzner"
        }
      }
    })
  ]

  # Workaround: Helm provider v3 + OpenTofu plan consistency bug.
  # https://github.com/hashicorp/terraform-provider-helm/pull/1739
  pass_credentials           = false
  render_subchart_notes      = true
  dependency_update          = false
  replace                    = false
  disable_webhooks           = false
  disable_crd_hooks          = false
  skip_crds                  = false
  recreate_pods              = false
  lint                       = false
  reuse_values               = false
  disable_openapi_validation = false
  verify                     = false
  devel                      = false

  depends_on = [
    kubernetes_secret.hcloud_csi,
    null_resource.add_hcloud_repo,
    helm_release.cilium_bootstrap,
  ]
}
