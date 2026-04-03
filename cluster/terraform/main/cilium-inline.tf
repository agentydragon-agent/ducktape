# Cilium CNI — inline manifest for bootstrap.
#
# Rendered from the Cilium Helm chart with values from cilium-values.yaml.
# Talos applies inline manifests during bootstrap before any pods schedule,
# avoiding the chicken-and-egg: Cilium must be running for pods to get
# network, but Flux (which would deploy Cilium) needs network to run.
#
# After bootstrap, Cilium is NOT managed by Flux — the inline manifest is
# the sole manager. To upgrade, bump cilium_version here and re-apply
# machine config (`tofu apply`).
#
# Gateway API CRDs are loaded via extraManifests (URL fetch) because
# Cilium registers as a GatewayClass provider on startup.

locals {
  cilium_version      = "1.18.7"
  cilium_values       = file("${path.module}/cilium-values.yaml")
  gateway_api_version = "v1.4.1"
}

data "helm_template" "cilium" {
  name       = "cilium"
  namespace  = "kube-system"
  repository = "https://helm.cilium.io/"
  chart      = "cilium"
  version    = local.cilium_version
  values     = [local.cilium_values]
}
