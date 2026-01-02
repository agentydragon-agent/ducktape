# Bootstrap Flux GitOps after CNI is ready
# This completes the full cluster setup in a single terraform apply

# Bootstrap Flux using native provider with pinned version
resource "flux_bootstrap_git" "cluster" {
  count = var.enable_flux_bootstrap ? 1 : 0

  depends_on = [
    talos_cluster_kubeconfig.talos,
    talos_machine_bootstrap.talos
  ]

  path = "k8s"

  # Pin Flux version to prevent drift
  version = "v2.7.3"

  # Use embedded manifests to avoid GitOps version mismatches
  embedded_manifests = true

  # Components to install
  components_extra = [
    "image-reflector-controller",
    "image-automation-controller"
  ]

  # Network policies for additional security
  network_policy = true
}

