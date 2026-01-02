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
resource "flux_bootstrap_git" "cluster" {
  path = "cluster/k8s"
}

# NOTE: Service configuration moved to Layer 3 after services are deployed
# Layer 2 only deploys services via Flux - configuration happens in Layer 3