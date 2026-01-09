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
# This resource creates initial GitRepository and Kustomization resources for Flux.
# After bootstrap, the authoritative configuration lives in:
#   k8s/flux-system/gotk-sync.yaml
#
# The gotk-sync.yaml file is included in k8s/kustomization.yaml and gets applied
# by Flux after bootstrap. It specifies additional config like sparseCheckout
# (required to keep artifact under tofu-controller's 4MB gRPC limit).
#
# KEEP IN SYNC: These settings must match gotk-sync.yaml:
#   - Git URL: provider.git.url ↔ spec.url
#   - Branch: provider.git.branch ↔ spec.ref.branch
#   - Path: path ↔ spec.path (in Kustomization)
#
# sparseCheckout is configured only in gotk-sync.yaml (spec.sparseCheckout)
resource "flux_bootstrap_git" "cluster" {
  path = "cluster/k8s"
}

# NOTE: Service configuration moved to Layer 3 after services are deployed
# Layer 2 only deploys services via Flux - configuration happens in Layer 3