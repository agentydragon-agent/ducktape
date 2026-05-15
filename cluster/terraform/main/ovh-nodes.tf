# OVH Eco Kimsufi KS-5 bare metal worker nodes (HIL, Hillsboro OR)
#
# Talos is installed via OVH rescue mode (netboot → dd image to disk).
# No Packer/snapshot mechanism available for OVH bare metal.
#
# Provisioning flow (per server):
#   1. Set rescue boot + reboot → rescue env (SSH with cluster SSH key)
#   2. dd Talos metal image to /dev/sda
#   3. Set harddisk boot + reboot → Talos boots
#   4. Apply Talos machine config (includes Nebula extension)
#
# Prerequisites:
#   - Server purchased via OVH web UI; set TF_VAR_kimsufi_service_name[_1]
#   - OVH API credentials in secrets/ovh-credentials.sops.yaml

# ============================================================================
# SERVER MAP
# ============================================================================

locals {
  kimsufi_servers = {
    kimsufi_worker0 = {
      service_name = var.kimsufi_service_name
      hostname     = "talos-kimsufi-worker-0"
      nebula_ip    = "10.42.0.13"
    }
    kimsufi_worker1 = {
      service_name = var.kimsufi_service_name_1
      hostname     = "talos-kimsufi-worker-1"
      nebula_ip    = "10.42.0.14"
    }
  }
  # Filter out unpurchased servers (empty service name)
  active_kimsufi_servers = {
    for k, v in local.kimsufi_servers : k => v if v.service_name != ""
  }
}

# ============================================================================
# TALOS IMAGE FACTORY - Metal platform with Nebula extension
# ============================================================================

resource "talos_image_factory_schematic" "kimsufi" {
  schematic = yamlencode({
    customization = {
      # KS-5 has no physical display; we only see boot output via OVH IPMI SOL.
      # Without console=ttyS0 every Talos boot log is invisible — silent reboot
      # loops mask whether the kernel even started.
      extraKernelArgs = [
        "console=tty0",
        "console=ttyS0,115200n8",
      ]
      systemExtensions = {
        officialExtensions = [
          "siderolabs/nebula",
        ]
      }
    }
  })
}

data "talos_image_factory_urls" "kimsufi" {
  schematic_id  = talos_image_factory_schematic.kimsufi.id
  talos_version = var.talos_version
  platform      = "metal"
  architecture  = "amd64"
}

# ============================================================================
# OVH SERVER DATA SOURCES
# ============================================================================

data "ovh_dedicated_server" "kimsufi" {
  for_each     = local.active_kimsufi_servers
  service_name = each.value.service_name
}

# Boot IDs are hardcoded because data.ovh_dedicated_server_boots returns BOTH
# the customer rescue (rescue12-customer, Debian-12-based) AND the iPXE shell
# (ipxe-shell, an interactive bootloader that does NOT auto-launch a Linux),
# and the data source only returns the IDs — no kernel/description to filter by.
# Picking [0] from the list gives iPXE shell → SSH never comes up → install hangs.
# Verified via GET /dedicated/server/{name}/boot/{id}.
locals {
  kimsufi_rescue_boot_id   = 218949 # rescue12-customer (Debian-12)
  kimsufi_harddisk_boot_id = 1      # harddisk
}

# ============================================================================
# SSH KEY — for OVH rescue mode authentication
# ============================================================================

# ED25519 keypair injected into the OVH rescue environment so remote-exec can
# SSH in to dd the Talos image. Stored in SOPS (secrets/ovh-rescue-ssh.sops.yaml),
# not generated in-TF, so it survives state loss without breaking access.
data "sops_file" "ovh_rescue_ssh" {
  source_file = "${path.module}/../../../secrets/ovh-rescue-ssh.sops.yaml"
}

# ============================================================================
# OVH SERVER RESOURCES — sets rescue SSH key + EFI bootloader
# ============================================================================

resource "ovh_dedicated_server" "kimsufi" {
  for_each = local.active_kimsufi_servers

  service_name   = each.value.service_name
  rescue_ssh_key = data.sops_file.ovh_rescue_ssh.data["public_key"]
  # Match iam.displayName so the resource's Read→Update cycle doesn't try to
  # PUT /services/{id} (requires API perms we don't have, and is a no-op anyway).
  # See cluster/docs/lessons_learned/2026_05_13_provisioning_ovh_kimsufi.md.
  display_name = each.value.service_name
  # Without this, OVH's iPXE falls back to rEFInd which "starts" the Talos UKI
  # but doesn't actually run it — control returns to firmware, BIOS reboots,
  # forever. systemd-boot (dropped at this path by the Talos metal image) IS
  # UKI-aware and chainloads it properly.
  efi_bootloader_path = "\\efi\\boot\\bootx64.efi"
}

# ============================================================================
# TALOS INSTALLATION — rescue boot, dd image, harddisk reboot
# ============================================================================

# Step 1: Set rescue boot mode.
# ignore_changes on boot_id: after initial creation this sets boot to rescue.
# Step 4 (kimsufi_harddisk) overwrites it to harddisk. Without ignore_changes,
# subsequent plans would see drift and try to revert to rescue.
resource "ovh_dedicated_server_update" "kimsufi_rescue" {
  for_each     = local.active_kimsufi_servers
  service_name = each.value.service_name
  boot_id      = local.kimsufi_rescue_boot_id
  depends_on   = [ovh_dedicated_server.kimsufi]

  lifecycle {
    ignore_changes = [boot_id]
  }
}

# Step 2: Reboot into rescue.
resource "ovh_dedicated_server_reboot_task" "kimsufi_to_rescue" {
  for_each     = local.active_kimsufi_servers
  service_name = each.value.service_name
  keepers      = [tostring(local.kimsufi_rescue_boot_id)]
  depends_on   = [ovh_dedicated_server_update.kimsufi_rescue]
}

# Step 3: SSH into rescue, dd Talos image.
# connection.timeout covers the window waiting for rescue to boot over SSH.
# triggers on schematic_id so a kernel/extension change triggers re-provisioning.
# To re-provision: tofu taint null_resource.install_talos_kimsufi["kimsufi_worker0"]
resource "null_resource" "install_talos_kimsufi" {
  for_each = local.active_kimsufi_servers

  # Re-run when the schematic changes (which changes the install image URL).
  # Schematic changes mean kernel-args/extensions changed — we want a fresh dd.
  triggers = {
    schematic_id = talos_image_factory_schematic.kimsufi.id
  }

  connection {
    type        = "ssh"
    host        = data.ovh_dedicated_server.kimsufi[each.key].ip
    user        = "root"
    private_key = data.sops_file.ovh_rescue_ssh.data["private_key"]
    timeout     = "15m"
  }

  provisioner "remote-exec" {
    # OVH rescue runs dash (no `set -o pipefail`). Decompress to a temp file
    # and dd from that, so an unrelated decompressor failure can't silently
    # feed dd zero bytes. `test -s` makes sure we actually got a raw image.
    # The Image Factory currently ships `metal-amd64.raw.zst`; older releases
    # used .xz, hence the URL-suffix switch.
    # KS-5 has 32 GB RAM; /tmp on tmpfs has room for the ~1.5 GB raw image.
    # /dev/sda is the KS-5 SATA SSD (verify with `lsblk` if cloning to other HW).
    inline = [
      "set -ex",
      # OVH Debian rescue doesn't have zstd pre-installed; xz-utils is there.
      "apt-get update -qq && apt-get install -y -qq zstd",
      "URL='${data.talos_image_factory_urls.kimsufi.urls.disk_image}'",
      "wget -q -O /tmp/talos.bin \"$URL\"",
      "case \"$URL\" in *.zst) zstd -dc /tmp/talos.bin > /tmp/talos.raw ;; *.xz) xz -dc /tmp/talos.bin > /tmp/talos.raw ;; *) echo \"unknown compression in $URL\" >&2; exit 1 ;; esac",
      "test -s /tmp/talos.raw",
      "dd if=/tmp/talos.raw of=/dev/sda bs=4M status=progress",
      "sync",
    ]
  }

  depends_on = [ovh_dedicated_server_reboot_task.kimsufi_to_rescue]
}

# Step 4: Switch to harddisk boot.
resource "ovh_dedicated_server_update" "kimsufi_harddisk" {
  for_each     = local.active_kimsufi_servers
  service_name = each.value.service_name
  boot_id      = local.kimsufi_harddisk_boot_id
  depends_on   = [null_resource.install_talos_kimsufi]
}

# Step 5: Reboot into Talos.
resource "ovh_dedicated_server_reboot_task" "kimsufi_to_talos" {
  for_each     = local.active_kimsufi_servers
  service_name = each.value.service_name
  keepers      = [tostring(local.kimsufi_harddisk_boot_id)]
  depends_on   = [ovh_dedicated_server_update.kimsufi_harddisk]
}

# ============================================================================
# TALOS MACHINE CONFIGURATION
# ============================================================================

locals {
  kimsufi_machine_config_patch = yamlencode({
    machine = merge(local.worker_machine_base, {
      install = {
        image = "factory.talos.dev/installer/${talos_image_factory_schematic.kimsufi.id}:${var.talos_version}"
      }
      # Topology labels set explicitly — no CCM for OVH bare metal.
      nodeLabels = {
        "topology.kubernetes.io/region" = "hil"
        "topology.kubernetes.io/zone"   = "hil-ovh"
      }
    })
    cluster = local.worker_cluster_config
  })
}

data "talos_machine_configuration" "kimsufi" {
  for_each = local.active_kimsufi_servers

  cluster_name       = var.cluster_name
  cluster_endpoint   = local.cluster_endpoint
  machine_secrets    = local.machine_secrets
  machine_type       = "worker"
  talos_version      = var.talos_version
  kubernetes_version = var.kubernetes_version
  examples           = false
  docs               = false

  config_patches = concat(
    [
      local.kimsufi_machine_config_patch,
      yamlencode({
        apiVersion = "v1alpha1"
        kind       = "HostnameConfig"
        auto       = "off"
        hostname   = each.value.hostname
      }),
    ],
    local.nebula_machine_patches[each.key],
  )
}

resource "talos_machine_configuration_apply" "kimsufi" {
  for_each = local.active_kimsufi_servers

  client_configuration        = local.client_configuration
  machine_configuration_input = data.talos_machine_configuration.kimsufi[each.key].machine_configuration
  node                        = data.ovh_dedicated_server.kimsufi[each.key].ip

  depends_on = [ovh_dedicated_server_reboot_task.kimsufi_to_talos]
}
