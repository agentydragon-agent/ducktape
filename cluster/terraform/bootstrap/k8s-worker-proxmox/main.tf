# K8s Worker (Proxmox) — NixOS VM joining the Talos cluster via KubeSpan
#
# Lifecycle: Independent of the cluster bootstrap (infrastructure/).
# Destroying the cluster does not destroy this VM.
#
# After boot, kubespand and kubelet auto-start.
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
  # Server is localhost:7445 — HAProxy on the VM proxies to api.allegedly.works:6443.
  bootstrap_kubeconfig = yamlencode({
    apiVersion = "v1"
    kind       = "Config"
    clusters = [{
      name = "kubernetes"
      cluster = {
        certificate-authority-data = local.infra.k8s_ca_cert
        server                     = "https://localhost:7445"
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
    cluster_id           = local.infra.kubespan_cluster_id
    cluster_secret       = local.infra.kubespan_cluster_secret
    node_name            = "k8s-worker-test"
  }

  depends_on = [module.k8s_worker_test_image]
}
