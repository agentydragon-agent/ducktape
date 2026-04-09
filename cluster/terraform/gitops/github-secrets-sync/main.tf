# GitHub Actions Secrets Sync
#
# Syncs a single SOPS age key to GitHub Actions so CI can decrypt secrets
# from git. Managed by tofu-controller (15m interval).
#
# The CI age key is a narrow-scope key that can only decrypt CI-relevant
# secrets (BuildBuddy API key, Docker CI mTLS, Attic token, Harbor creds,
# GitHub PAT). It cannot decrypt cluster tokens, Nebula keys, or other
# infrastructure secrets.
#
# Auth: fine-grained GitHub PAT stored as K8s Secret (SOPS-deployed by Flux).

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

# --- GitHub Actions Secrets ---

resource "github_actions_secret" "sops_age_key" {
  repository      = "ducktape"
  secret_name     = "SOPS_AGE_KEY"
  plaintext_value = data.kubernetes_secret.ci_age_key.data["age-key"]
}

# CLEANUP(2026-04-09): Old per-secret GHA secrets replaced by SOPS_AGE_KEY.
# Remove these blocks once GHA workflows are confirmed working with SOPS
# decryption and the old secrets are deleted from GitHub.
removed {
  from = github_actions_secret.buildbuddy_api_key
  lifecycle { destroy = true }
}
removed {
  from = github_actions_secret.props_registry_username
  lifecycle { destroy = true }
}
removed {
  from = github_actions_secret.props_registry_password
  lifecycle { destroy = true }
}
removed {
  from = github_actions_secret.attic_token
  lifecycle { destroy = true }
}
removed {
  from = data.kubernetes_secret.harbor_ci_robot
  lifecycle { destroy = false }
}
removed {
  from = data.kubernetes_secret.buildbuddy_api_key
  lifecycle { destroy = false }
}
removed {
  from = data.kubernetes_secret.attic_push_token
  lifecycle { destroy = false }
}
