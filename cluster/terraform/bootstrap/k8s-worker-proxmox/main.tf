# K8s Worker (Proxmox) — NixOS VM joining the Talos cluster via Nebula mesh
#
# Lifecycle: Independent of the cluster bootstrap (infrastructure/).
# Destroying the cluster does not destroy this VM.
#
# After boot, Nebula and kubelet auto-start.
# Approve the CSR: kubectl certificate approve <csr-name>

# =============================================================================
# REMOTE STATE
# =============================================================================

data "terraform_remote_state" "persistent_auth" {
  backend = "local"
  config = {
    path = "../persistent-auth/terraform.tfstate"
  }
}

data "terraform_remote_state" "infrastructure" {
  backend = "local"
  config = {
    path = "../infrastructure/terraform.tfstate"
  }
}

# =============================================================================
# LOCALS
# =============================================================================

locals {
  proxmox_endpoint = "https://${var.proxmox_api_host}/"

  # SSH key handling - try common key types in order of preference
  ssh_key_candidates = [
    pathexpand("~/.ssh/id_ed25519.pub"),
    pathexpand("~/.ssh/id_ecdsa.pub"),
    pathexpand("~/.ssh/id_rsa.pub")
  ]
  ssh_key_path = var.ssh_public_key != "" ? "" : (
    fileexists(local.ssh_key_candidates[0]) ? local.ssh_key_candidates[0] :
    fileexists(local.ssh_key_candidates[1]) ? local.ssh_key_candidates[1] :
    fileexists(local.ssh_key_candidates[2]) ? local.ssh_key_candidates[2] :
    ""
  )
  ssh_public_key = var.ssh_public_key != "" ? var.ssh_public_key : (
    local.ssh_key_path != "" ? trimspace(file(local.ssh_key_path)) : ""
  )

  # NixOS image build inputs
  nix_dir_hash = sha1(join("", [for f in sort(fileset("${path.module}/../../../../nix", "**/*.nix")) : filesha1("${path.module}/../../../../nix/${f}")]))
  repo_root    = "${path.module}/../../../.."

  # K8s credentials from infrastructure state
  infra = data.terraform_remote_state.infrastructure.outputs

  # The CA cert from talos_machine_secrets is already base64-encoded.
  # Decode it for the PEM file written by cloud-init.
  k8s_ca_cert_pem = base64decode(local.infra.k8s_ca_cert)

  # Construct bootstrap kubeconfig from infrastructure state.
  # Server is a control plane Nebula IP — Nebula mesh provides direct connectivity.
  bootstrap_kubeconfig = yamlencode({
    apiVersion = "v1"
    kind       = "Config"
    clusters = [{
      name = "kubernetes"
      cluster = {
        certificate-authority-data = local.infra.k8s_ca_cert
        server                     = "https://10.42.0.1:6443"
      }
    }]
    contexts = [{
      name = "bootstrap@kubernetes"
      context = {
        cluster = "kubernetes"
        user    = "bootstrap"
      }
    }]
    current-context = "bootstrap@kubernetes"
    users = [{
      name = "bootstrap"
      user = {
        token = local.infra.k8s_bootstrap_token
      }
    }]
  })

  # Nebula credentials from persistent-auth
  persistent = data.terraform_remote_state.persistent_auth.outputs
  node_name  = "k8s-worker-test"

  nebula_config = yamlencode({
    pki = {
      ca   = "/etc/nebula/ca.crt"
      cert = "/etc/nebula/host.crt"
      key  = "/etc/nebula/host.key"
    }
    static_host_map = {
      "10.42.0.1" = ["${local.infra.cluster_nodes.vps_ips["vps0"]}:4242"]
      "10.42.0.2" = ["${local.infra.cluster_nodes.vps_ips["vps1"]}:4242"]
    }
    lighthouse = {
      am_lighthouse = false
      interval      = 10
      hosts         = ["10.42.0.1", "10.42.0.2"]
    }
    relay  = { relays = ["10.42.0.1", "10.42.0.2"], use_relays = true }
    listen = { host = "0.0.0.0", port = 4242 }
    punchy = { punch = true, respond = true }
    tun    = { dev = "nebula1" }
    firewall = {
      outbound = [{ port = "any", proto = "any", host = "any" }]
      inbound  = [{ port = "any", proto = "any", host = "any" }]
    }
  })
}

# =============================================================================
# PROVIDERS
# =============================================================================

provider "proxmox" {
  endpoint  = local.proxmox_endpoint
  username  = "terraform@pve"
  api_token = data.terraform_remote_state.persistent_auth.outputs.terraform_pve_token.token
  insecure  = true

  ssh {
    agent    = true
    username = "root"
    node {
      name    = var.proxmox_node_name
      address = var.proxmox_host
    }
  }
}

# =============================================================================
# VALIDATION
# =============================================================================

check "ssh_key_required" {
  assert {
    condition     = local.ssh_public_key != ""
    error_message = "No SSH public key found. Provide via ssh_public_key variable or create ~/.ssh/id_ed25519."
  }
}

# =============================================================================
# NIXOS IMAGE
# =============================================================================

# Build and upload per-host NixOS qcow2 image (same pattern as nixos-dev-env)
module "k8s_worker_test_image" {
  source       = "../../../../terraform/modules/nixos-image"
  flake_target = "k8s-worker-test"
  proxmox_host = var.proxmox_host
  repo_root    = local.repo_root
  nix_dir_hash = local.nix_dir_hash
}

# =============================================================================
# VM INSTANCE
# =============================================================================

module "k8s_worker_test" {
  source = "../../../../terraform/modules/proxmox-vm"

  vm_name           = "k8s-worker-test"
  vm_id             = 111
  username          = var.username
  vcpus             = 4
  memory_mb         = 8192
  disk_size_gb      = 50
  auto_start        = true
  image_import_path = module.k8s_worker_test_image.import_path

  proxmox_node_name = var.proxmox_node_name
  storage           = var.storage
  network_bridge    = var.network_bridge
  ssh_public_key    = local.ssh_public_key

  k8s_cluster_join = {
    bootstrap_kubeconfig = local.bootstrap_kubeconfig
    ca_cert              = local.k8s_ca_cert_pem
    node_name            = local.node_name
    nebula_ca_cert       = local.persistent.nebula_ca_cert
    nebula_host_cert     = local.persistent.nebula_node_certs[local.node_name].cert
    nebula_host_key      = local.persistent.nebula_node_certs[local.node_name].key
    nebula_config        = local.nebula_config
  }

  depends_on = [module.k8s_worker_test_image]
}
