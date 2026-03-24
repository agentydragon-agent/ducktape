# Flux GitOps bootstrap — requires infrastructure to be applied first.
# The kubeconfig file must exist at ${path.module}/kubeconfig.

resource "flux_bootstrap_git" "cluster" {
  path             = "cluster/k8s"
  components_extra = ["image-reflector-controller", "image-automation-controller"]

  kustomization_override = <<-EOT
    apiVersion: kustomize.config.k8s.io/v1beta1
    kind: Kustomization
    resources:
      - gotk-components.yaml
      - gotk-sync.yaml
    patches:
      - target:
          kind: GitRepository
          name: flux-system
        patch: |
          - op: add
            path: /spec/sparseCheckout
            value:
              - cluster/
  EOT
}
