# NixOS Dev Environment Infrastructure
# Proxmox infrastructure + dev workstation VMs using the shared proxmox-vm module

# =============================================================================
# REMOTE STATE (Proxmox auth token)
# =============================================================================

data "terraform_remote_state" "persistent_auth" {
  backend = "local"
  config = {
    path = "${path.module}/../../cluster/terraform/bootstrap/persistent-auth/terraform.tfstate"
  }
}

locals {
  # Proxmox configuration
  proxmox_endpoint = "https://${var.proxmox_api_host}/"
  proxmox_insecure = true # Accept self-signed certs

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
  nix_dir_hash = sha1(join("", [for f in sort(fileset("${path.module}/../../nix", "**/*.nix")) : filesha1("${path.module}/../../nix/${f}")]))
  repo_root    = "${path.module}/../.."

}

# =============================================================================
# VALIDATION CHECKS
# =============================================================================

check "ssh_key_required" {
  assert {
    condition     = local.ssh_public_key != ""
    error_message = <<-EOT
      No SSH public key found!
      Tried: ${join(", ", local.ssh_key_candidates)}

      Fix by either:
      1. Creating an SSH key: ssh-keygen -t ed25519 -C "your_email@example.com"
      2. Providing key via variable: terraform apply -var="ssh_public_key=$(cat ~/.ssh/id_ed25519.pub)"
    EOT
  }
}

# Check if nix/ tree has uncommitted changes
# (nix/ config is baked into the qcow2 image built locally)
data "external" "git_status" {
  program = ["bash", "-c", <<-EOT
    cd "${path.module}/../.."
    dirty="false"

    if ! git diff --quiet HEAD -- nix/ 2>/dev/null || [ -n "$(git status --porcelain -- nix/ 2>/dev/null)" ]; then
      dirty="true"
    fi

    printf '{"dirty":"%s"}' "$dirty"
  EOT
  ]
}

check "git_clean" {
  assert {
    condition     = data.external.git_status.result.dirty == "false"
    error_message = <<-EOT
      WARNING: nix/ tree has uncommitted changes!
      The VM image is built from committed nix/ config. Uncommitted changes
      will not be included in the image. Commit your changes first.
    EOT
  }
}

# =============================================================================
# PROXMOX USER/TOKEN PROVISIONING (agent-test — commented out, using
# persistent-auth terraform@pve token instead for full Mapping.Use etc.)
# =============================================================================

# data "external" "terraform_user" {
#   program = ["bash", "-c", <<-EOT
#     ssh ${local.proxmox_host} '
#       pveum user add terraform@pve --comment "Terraform automation (ephemeral)" 2>/dev/null || true
#       pveum role add TerraformAdmin -privs "Datastore.Allocate,Datastore.AllocateSpace,Datastore.AllocateTemplate,Datastore.Audit,Pool.Allocate,Pool.Audit,SDN.Use,Sys.Audit,Sys.Console,Sys.Modify,VM.Allocate,VM.Audit,VM.Clone,VM.Config.CDROM,VM.Config.CPU,VM.Config.Cloudinit,VM.Config.Disk,VM.Config.HWType,VM.Config.Memory,VM.Config.Network,VM.Config.Options,VM.Console,VM.Migrate,VM.PowerMgmt,User.Modify,Permissions.Modify" 2>/dev/null || \
#       pveum role modify TerraformAdmin -privs "Datastore.Allocate,Datastore.AllocateSpace,Datastore.AllocateTemplate,Datastore.Audit,Pool.Allocate,Pool.Audit,SDN.Use,Sys.Audit,Sys.Console,Sys.Modify,VM.Allocate,VM.Audit,VM.Clone,VM.Config.CDROM,VM.Config.CPU,VM.Config.Cloudinit,VM.Config.Disk,VM.Config.HWType,VM.Config.Memory,VM.Config.Network,VM.Config.Options,VM.Console,VM.Migrate,VM.PowerMgmt,User.Modify,Permissions.Modify"
#       pveum aclmod / -user terraform@pve -role TerraformAdmin
#     '
#     printf '{"success":"true"}'
#   EOT
#   ]
# }
#
# data "external" "terraform_token" { ... }
# data "external" "pool_user" { ... }
# data "external" "user_token" { ... }

# =============================================================================
# PROXMOX PROVIDER
# Uses terraform@pve token from persistent-auth (same as cluster infrastructure)
# =============================================================================

provider "proxmox" {
  endpoint  = local.proxmox_endpoint
  username  = "terraform@pve"
  api_token = data.terraform_remote_state.persistent_auth.outputs.terraform_pve_token.token
  insecure  = local.proxmox_insecure

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
# SHARED INFRASTRUCTURE
# Agent-test pool/ACL resources commented out — using persistent-auth token.
# =============================================================================

# resource "proxmox_virtual_environment_pool" "user_pool" {
#   comment = "Resource pool for ${local.proxmox_user_base}"
#   pool_id = local.pool_name_computed
# }
#
# resource "proxmox_virtual_environment_acl" "pool_admin" { ... }
# resource "proxmox_virtual_environment_acl" "storage_access" { ... }
# resource "proxmox_virtual_environment_acl" "storage_access_local" { ... }
# resource "proxmox_virtual_environment_acl" "sdn_access" { ... }

# Per-host NixOS qcow2 images (built via nix, uploaded to Proxmox)
# Uses system.build.images.qemu-efi (nixos-generators upstreamed in nixpkgs 25.05+)
module "wyrm2_image" {
  source       = "../modules/nixos-image"
  flake_target = "wyrm2"
  proxmox_host = var.proxmox_host
  repo_root    = local.repo_root
  nix_dir_hash = local.nix_dir_hash
}

# Cleanup on destroy (agent-test user — commented out, no longer provisioned)
# resource "null_resource" "cleanup" { ... }

# =============================================================================
# VM INSTANCES
# =============================================================================

# Wyrm2 - NixOS dev workstation + k8s worker (pre-built image, cloud-init for k8s creds)
module "wyrm2" {
  source = "../modules/proxmox-vm"

  vm_name  = "wyrm2"
  vm_id    = 110
  username = "agentydragon"
  vcpus    = 32
  # 96GB. Reduced from 112GB — with balloon=0 (VFIO requires pinned memory),
  # 112GB + Talos CP (8GB) left only 8GB for host+ZFS ARC, causing ZFS write
  # stalls (memory_available_bytes went negative). 96GB leaves 24GB headroom.
  memory_mb          = 98304
  disk_size_gb       = 300
  auto_start         = true
  image_import_path  = module.wyrm2_image.import_path
  machine_type       = "q35"
  memory_floating_mb = 0 # Disable balloon (VFIO incompatible)
  gpu_pci_ids        = ["0000:01:00.0", "0000:03:00.0"]
  vga_type           = "qxl"
  # cache=never: virtiofsd with cache=auto leaks memory — it caches all accessed
  # files with no eviction, growing to 10+ GiB over days. On a 128 GiB host with
  # 96 GiB pinned for this VM, that starves ZFS ARC and causes system-wide stalls.
  # See debug/wyrm-oom/LOG.md (virtiofsd FD leak) and
  # debug/atlas/black_screen_lockup.md (incident 15, memory overcommit).
  virtiofs_mounts = [
    { mapping = "tankshare", cache = "never" },
    { mapping = "code", cache = "never" },
  ]
  additional_disks = [
    { interface = "scsi30", size_gb = 200 },  # containerd (/var/lib/containerd)
    { interface = "virtio0", size_gb = 500 }, # local-path provisioner (/var/local-path-provisioner)
    { interface = "virtio1", size_gb = 100 }, # Longhorn (/var/mnt/longhorn)
  ]

  proxmox_node_name = var.proxmox_node_name
  storage           = var.storage
  network_bridge    = var.network_bridge
  ssh_public_key    = local.ssh_public_key

  # K8s + Nebula credentials managed by sops-nix on the NixOS side,
  # no cloud-init credential injection needed.

  depends_on = [module.wyrm2_image]
}
