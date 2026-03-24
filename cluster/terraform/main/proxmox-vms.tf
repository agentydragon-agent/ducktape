# Wyrm2 — NixOS dev workstation + k8s GPU worker on Proxmox
# Uses shared proxmox-vm and nixos-image modules.

# ============================================================================
# SSH KEY DETECTION
# ============================================================================

locals {
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

  repo_root = "${path.module}/../../.."
}

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

# ============================================================================
# NIXOS BOOTSTRAP IMAGE
# ============================================================================

# Bootstrap NixOS qcow2 image — minimal SSH-able image for initial VM provisioning.
# Only rebuilt when rebuild_image=true. After boot, nixos-rebuild deploys the full config.
module "wyrm2_image" {
  source        = "../../../terraform/modules/nixos-image"
  flake_target  = "bootstrap"
  proxmox_host  = var.proxmox_node_name
  repo_root     = local.repo_root
  build_enabled = var.rebuild_image
}

# ============================================================================
# VM INSTANCE
# ============================================================================

# Wyrm2 - NixOS dev workstation + k8s worker (pre-built image, cloud-init for k8s creds)
module "wyrm2" {
  source = "../../../terraform/modules/proxmox-vm"

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
  vga_type           = "virtio"
  audio_device       = "ich9-intel-hda"
  audio_driver       = "spice"
  # cache=never: virtiofsd with cache=auto leaks memory — it caches all accessed
  # files with no eviction, growing to 10+ GiB over days. On a 128 GiB host with
  # 96 GiB pinned for this VM, that starves ZFS ARC and causes system-wide stalls.
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

# ============================================================================
# NIXOS-REBUILD (optional — deploys full wyrm2 config from GitHub)
# ============================================================================

resource "null_resource" "wyrm2_nixos_rebuild" {
  count = var.nixos_rebuild ? 1 : 0

  triggers = {
    # Always re-run when the variable is set (user explicitly requested it)
    run = timestamp()
  }

  connection {
    type    = "ssh"
    host    = module.wyrm2.ipv4_addresses[1][0]
    user    = "root"
    timeout = "5m"
    agent   = true
  }

  provisioner "remote-exec" {
    inline = [
      "until nix --version 2>/dev/null; do sleep 2; done",
      "nixos-rebuild switch --flake github:agentydragon/ducktape?ref=devel#wyrm2",
    ]
  }

  depends_on = [module.wyrm2]
}
