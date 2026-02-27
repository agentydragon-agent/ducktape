terraform {
  required_version = ">= 1.0"

  required_providers {
    headscale = {
      source  = "awlsring/headscale"
      version = "~> 0.5.0"
    }
  }

  backend "kubernetes" {
    secret_suffix = "headscale-config"
    namespace     = "flux-system"
  }
}

provider "headscale" {
  endpoint = var.headscale_url
  api_key  = var.headscale_api_key
}

# Robot user for the ActivityWatch tailscale sidecar.
# Pre-auth key is created by k8s/activitywatch-authkey-bootstrap/ Job (not
# Terraform) because the headscale provider masks the key in state after the
# first Read — see docs/bugs/headscale-provider-key-masking.md.
# TODO: Move pre-auth key back to Terraform after upstream provider fix.
resource "headscale_user" "activitywatch" {
  name = "activitywatch"
}
