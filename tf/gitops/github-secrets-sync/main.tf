# GitHub Actions Secrets Sync
#
# Syncs a single SOPS age key to GitHub Actions so CI can decrypt secrets
# from git. Managed by tofu-controller (15m interval).
#
# The CI age key is a narrow-scope key that can only decrypt CI-relevant
# secrets (BuildBuddy API key, Docker CI mTLS, Attic token, props registry
# creds, GitHub PAT). It cannot decrypt cluster tokens, Nebula keys, or other
# infrastructure secrets.
#
# Auth: fine-grained GitHub PAT stored as K8s Secret (SOPS-deployed by Flux).
# Required PAT permissions are documented in
# cluster/k8s/github-secrets-sync/README.md.

provider "github" {
  owner = "agentydragon"
  token = data.kubernetes_secret.github_secrets_sync_pat.data["token"]
}

# --- Data Sources ---

data "kubernetes_secret" "github_secrets_sync_pat" {
  metadata {
    name      = "github-secrets-sync-pat"
    namespace = "flux-system"
  }
}

data "kubernetes_secret" "ci_age_key" {
  metadata {
    name      = "ci-age-key"
    namespace = "flux-system"
  }
}

data "github_user" "agentydragon" {
  username = "agentydragon"
}

resource "random_password" "pr_visuals_access_key" {
  length  = 32
  special = false
  keepers = {
    rotation = "2026-07-12-1"
  }
}

resource "random_password" "pr_visuals_secret_key" {
  length  = 64
  special = false
  keepers = {
    rotation = "2026-07-12-1"
  }
}

resource "kubernetes_secret" "pr_visuals_s3_credentials" {
  metadata {
    name      = "pr-visuals-s3-credentials"
    namespace = "seaweedfs"
  }
  data = {
    prVisualsAccessKey = random_password.pr_visuals_access_key.result
    prVisualsSecretKey = random_password.pr_visuals_secret_key.result
  }
}

# --- GitHub Actions Secrets ---

resource "github_actions_secret" "sops_age_key" {
  repository      = "ducktape"
  secret_name     = "SOPS_AGE_KEY"
  plaintext_value = data.kubernetes_secret.ci_age_key.data["age-key"]
}

resource "github_actions_secret" "sops_age_key_gaffer_private" {
  repository      = "gaffer-private"
  secret_name     = "SOPS_AGE_KEY"
  plaintext_value = data.kubernetes_secret.ci_age_key.data["age-key"]
}

# Fork pull requests cannot receive repository Actions secrets, even after a
# maintainer clicks GitHub's "Approve and run workflows" button.  This
# environment is used by the base-branch-owned pull_request_target workflow:
# each new PR head waits for an explicit review before any PR code runs with
# the CI SOPS identity.
resource "github_repository_environment" "trusted_pr_ci" {
  repository          = "ducktape"
  environment         = "trusted-pr-ci"
  can_admins_bypass   = false
  prevent_self_review = true

  reviewers {
    users = [data.github_user.agentydragon.id]
  }
}

resource "github_actions_environment_secret" "trusted_pr_ci_sops_age_key" {
  repository      = "ducktape"
  environment     = github_repository_environment.trusted_pr_ci.environment
  secret_name     = "SOPS_AGE_KEY"
  plaintext_value = data.kubernetes_secret.ci_age_key.data["age-key"]
}

resource "github_actions_secret" "pr_visuals_access_key" {
  #checkov:skip=CKV_GIT_4: Value is generated in Terraform state and sent over TLS; GitHub encrypts it at rest. This module's existing SOPS key uses the same provider path.
  repository      = "ducktape"
  secret_name     = "PR_VISUALS_ACCESS_KEY"
  plaintext_value = random_password.pr_visuals_access_key.result
}

resource "github_actions_secret" "pr_visuals_secret_key" {
  #checkov:skip=CKV_GIT_4: Value is generated in Terraform state and sent over TLS; GitHub encrypts it at rest. This module's existing SOPS key uses the same provider path.
  repository      = "ducktape"
  secret_name     = "PR_VISUALS_SECRET_KEY"
  plaintext_value = random_password.pr_visuals_secret_key.result
}

# --- GitHub Actions Variables ---

# The variable predates Terraform ownership. Import it so tofu-controller adopts
# the existing GitHub Actions variable instead of trying to create a duplicate.
import {
  to = github_actions_variable.props_registry_url
  id = "ducktape:PROPS_REGISTRY_URL"
}

# Where props CI pushes agent images: the standalone props registry proxy, which
# records agent definitions and forwards to Forgejo's registry. CI authenticates
# as the evaluator Postgres role (secrets/ci/props-registry.sops.yaml).
resource "github_actions_variable" "props_registry_url" {
  repository    = "ducktape"
  variable_name = "PROPS_REGISTRY_URL"
  value         = "props-registry.allegedly.works"
}

# Data sources for harbor_ci_robot, buildbuddy_api_key, attic_push_token, and
# vm_images_s3_credentials were removed (no `removed` block needed for data
# sources — just delete). The GitHub Actions secrets VM_IMAGES_S3_* are no
# longer needed since publishing moved in-cluster (see
# cluster/k8s/vm-images-publisher/). Removing the resource blocks here will
# destroy the GitHub secrets on the next tofu apply.
