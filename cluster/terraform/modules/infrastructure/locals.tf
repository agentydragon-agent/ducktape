terraform {
  required_providers {
    talos = {
      source = "siderolabs/talos"
    }
    helm = {
      source = "hashicorp/helm"
    }
    kubernetes = {
      source = "hashicorp/kubernetes"
    }
    flux = {
      source = "fluxcd/flux"
    }
    null = {
      source = "hashicorp/null"
    }
    external = {
      source = "hashicorp/external"
    }
    random = {
      source = "hashicorp/random"
    }
  }
}

# CONSOLIDATED LOCALS for all layers

locals {
  # Layer control (already defined in main.tf)

  # PVE-AUTH layer locals (already defined in pve-auth.tf)

  # INFRASTRUCTURE layer locals
  # Host configuration
  hosts = {
    proxmox   = "atlas"
    headscale = "agentydragon.com"
  }

  # SSH targets for auto-provisioning
  ssh_targets = {
    proxmox   = "root@${local.hosts.proxmox}"
    headscale = "root@${local.hosts.headscale}"
  }

}