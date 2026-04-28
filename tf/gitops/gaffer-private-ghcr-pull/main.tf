# GHCR pull-secret automation for gaffer-private private images.
#
# Reads a SOPS-deployed read:packages PAT and synthesizes the
# `kubernetes.io/dockerconfigjson` Secret in two namespaces:
#
#   - `gaffer-ghcr-pull-flux` in flux-system (Flux ImageRepository
#     scanning of ghcr.io/agentydragon/<gaffer images>).
#   - `gaffer-ghcr-pull` in house-vallejo (kubelet pulls the image).
#
# The two-namespace shape avoids depending on the Reflector controller
# and keeps the dependency graph simple: this TF module dependsOn the
# `gaffer-private` Kustomization (which creates the house-vallejo
# namespace).

data "kubernetes_secret" "ghcr_pat" {
  metadata {
    name      = "github-pat-ghcr-read"
    namespace = "flux-system"
  }
}

locals {
  dockerconfigjson = jsonencode({
    auths = {
      "ghcr.io" = {
        auth = base64encode("agentydragon:${data.kubernetes_secret.ghcr_pat.data["token"]}")
      }
    }
  })
}

resource "kubernetes_secret" "flux_pull" {
  metadata {
    name      = "gaffer-ghcr-pull-flux"
    namespace = "flux-system"
    annotations = {
      description = "Read-only GHCR pull credential for Flux ImageRepository scanning of gaffer-private's private images."
    }
  }
  type = "kubernetes.io/dockerconfigjson"
  data = {
    ".dockerconfigjson" = local.dockerconfigjson
  }
}

resource "kubernetes_secret" "house_vallejo_pull" {
  metadata {
    name      = "gaffer-ghcr-pull"
    namespace = "house-vallejo"
    annotations = {
      description = "Read-only GHCR pull credential consumed by the house-vallejo Deployment's imagePullSecrets."
    }
  }
  type = "kubernetes.io/dockerconfigjson"
  data = {
    ".dockerconfigjson" = local.dockerconfigjson
  }
}
