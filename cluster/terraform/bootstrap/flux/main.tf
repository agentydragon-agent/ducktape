# LAYER 2: FLUX
# GitOps bootstrap - requires Layer 1 (infrastructure) to be complete

# Static provider configuration - Layer 1 writes kubeconfig to known location
provider "kubernetes" {
  config_path = "../infrastructure/kubeconfig"
}

provider "helm" {
  kubernetes {
    config_path = "../infrastructure/kubeconfig"
  }
}

provider "flux" {
  kubernetes = {
    config_path = "../infrastructure/kubeconfig"
  }
  git = {
    url    = "ssh://git@github.com/agentydragon/ducktape.git"
    branch = "devel"
    ssh = {
      username    = "git"
      private_key = data.terraform_remote_state.persistent_auth.outputs.flux_deploy_private_key
    }
  }
}

# FLUX BOOTSTRAP: Initialize GitOps engine
#
# kustomization_override adds sparseCheckout to GitRepository - required because:
# 1. The ducktape repo is ~14MB, exceeding tofu-controller's 4MB gRPC limit
# 2. flux_bootstrap_git doesn't natively support sparseCheckout
# 3. Without this, terraform generates gotk-sync.yaml without sparseCheckout
#
# The patch adds sparseCheckout: ["cluster/"] to only fetch the cluster/ directory.
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

# All service deployment and configuration is handled by Flux via gitops/
