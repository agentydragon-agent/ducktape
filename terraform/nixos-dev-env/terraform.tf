# Unified Proxmox User + NixOS VM Environment
# Creates an isolated user with resource pool and provisions a NixOS VM

terraform {
  required_version = ">= 1.0"

  # State stored in CNPG postgres (tofu-state-db in k8s).
  # PG_CONN_STR env var set by .envrc via kubectl port-forward.
  backend "pg" {}

  required_providers {
    null = {
      source  = "hashicorp/null"
      version = "~> 3.2.0"
    }
    proxmox = {
      source  = "bpg/proxmox"
      version = "~> 0.91.0"
    }
  }
}
