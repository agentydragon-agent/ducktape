# LAYER 2: SERVICES
# Service deployment via GitOps - requires Layer 1 to be complete

# Static provider configuration - Layer 1 writes kubeconfig to known location
provider "kubernetes" {
  config_path = "../01-infrastructure/kubeconfig"
}

provider "helm" {
  kubernetes {
    config_path = "../01-infrastructure/kubeconfig"
  }
}

provider "flux" {
  kubernetes = {
    config_path = "../01-infrastructure/kubeconfig"
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

# Vault secrets managed by tofu-controller after Flux deploys Vault
# See: terraform/gitops/secrets/ for Vault secret management

# FLUX BOOTSTRAP: Initialize GitOps engine
#
# kustomization_override adds sparseCheckout to GitRepository - required because:
# 1. The ducktape repo is ~14MB, exceeding tofu-controller's 4MB gRPC limit
# 2. flux_bootstrap_git doesn't natively support sparseCheckout
# 3. Without this, terraform generates gotk-sync.yaml without sparseCheckout
#
# The patch adds sparseCheckout: ["cluster/"] to only fetch the cluster/ directory,
# reducing the artifact size to ~200KB.
resource "flux_bootstrap_git" "cluster" {
  path = "cluster/k8s"

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

# NOTE: Service configuration moved to Layer 3 after services are deployed
# Layer 2 only deploys services via Flux - configuration happens in Layer 3
