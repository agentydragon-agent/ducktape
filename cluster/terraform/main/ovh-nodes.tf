# OVH Eco Kimsufi KS-1 bare metal worker node (HIL, Hillsboro OR)
# Xeon-D 1520 (4c/8t), 32GB RAM, 2×480GB SSD, ~$20/mo
#
# Talos is installed via OVH rescue mode (netboot → dd image to disk).
# No Packer/snapshot mechanism available for OVH bare metal.
#
# Provisioning flow:
#   1. Set rescue boot + reboot → rescue env (SSH with cluster SSH key)
#   2. dd Talos metal image to /dev/sda
#   3. Set harddisk boot + reboot → Talos boots
#   4. Apply Talos machine config (includes Nebula extension)
#
# Prerequisites:
#   - Server purchased via OVH web UI; set TF_VAR_kimsufi_service_name
#   - OVH API credentials in secrets/ovh-credentials.sops.yaml

# ============================================================================
# TALOS IMAGE FACTORY - Metal platform with Nebula extension
# ============================================================================

resource "talos_image_factory_schematic" "kimsufi" {
  schematic = yamlencode({
    customization = {
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
  service_name = var.kimsufi_service_name
}

data "ovh_dedicated_server_boots" "kimsufi_rescue" {
  service_name = var.kimsufi_service_name
  boot_type    = "rescue"
}

data "ovh_dedicated_server_boots" "kimsufi_harddisk" {
  service_name = var.kimsufi_service_name
  boot_type    = "harddisk"
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
# OVH SERVER RESOURCE — sets rescue SSH key
# ============================================================================

resource "ovh_dedicated_server" "kimsufi" {
  service_name   = var.kimsufi_service_name
  rescue_ssh_key = data.sops_file.ovh_rescue_ssh.data["public_key"]
}

# ============================================================================
# TALOS INSTALLATION — rescue boot, dd image, harddisk reboot
# ============================================================================

# Step 1: Set rescue boot mode.
# ignore_changes on boot_id: after initial creation this sets boot to rescue.
# Step 4 (kimsufi_harddisk) overwrites it to harddisk. Without ignore_changes,
# subsequent plans would see drift and try to revert to rescue.
resource "ovh_dedicated_server_update" "kimsufi_rescue" {
  service_name = var.kimsufi_service_name
  boot_id      = tolist(data.ovh_dedicated_server_boots.kimsufi_rescue.result)[0]
  depends_on   = [ovh_dedicated_server.kimsufi]

  lifecycle {
    ignore_changes = [boot_id]
  }
}

# Step 2: Reboot into rescue.
resource "ovh_dedicated_server_reboot_task" "kimsufi_to_rescue" {
  service_name = var.kimsufi_service_name
  keepers      = [tostring(tolist(data.ovh_dedicated_server_boots.kimsufi_rescue.result)[0])]
  depends_on   = [ovh_dedicated_server_update.kimsufi_rescue]
}

# Step 3: SSH into rescue, dd Talos image.
# connection.timeout covers the window waiting for rescue to boot over SSH.
# triggers = { once = "initial" } means this only runs on first apply.
# To re-provision: tofu taint null_resource.install_talos_kimsufi
resource "null_resource" "install_talos_kimsufi" {
  triggers = {
    once = "initial"
  }

  connection {
    type        = "ssh"
    host        = data.ovh_dedicated_server.kimsufi.ip
    user        = "root"
    private_key = data.sops_file.ovh_rescue_ssh.data["private_key"]
    timeout     = "15m"
  }

  provisioner "remote-exec" {
    inline = [
      "set -ex",
      # KS-1 uses /dev/sda (SATA SSD). Verify with: lsblk
      "wget -q -O /tmp/talos.raw.xz '${data.talos_image_factory_urls.kimsufi.urls.disk_image}'",
      "xz -d -c /tmp/talos.raw.xz | dd of=/dev/sda bs=4M status=progress",
      "sync",
    ]
  }

  depends_on = [ovh_dedicated_server_reboot_task.kimsufi_to_rescue]
}

# Step 4: Switch to harddisk boot.
resource "ovh_dedicated_server_update" "kimsufi_harddisk" {
  service_name = var.kimsufi_service_name
  boot_id      = tolist(data.ovh_dedicated_server_boots.kimsufi_harddisk.result)[0]
  depends_on   = [null_resource.install_talos_kimsufi]
}

# Step 5: Reboot into Talos.
resource "ovh_dedicated_server_reboot_task" "kimsufi_to_talos" {
  service_name = var.kimsufi_service_name
  keepers      = [tostring(tolist(data.ovh_dedicated_server_boots.kimsufi_harddisk.result)[0])]
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
        hostname   = "talos-kimsufi-worker-0"
      }),
    ],
    local.nebula_machine_patches["kimsufi_worker0"],
  )
}

resource "talos_machine_configuration_apply" "kimsufi" {
  client_configuration        = local.client_configuration
  machine_configuration_input = data.talos_machine_configuration.kimsufi.machine_configuration
  node                        = data.ovh_dedicated_server.kimsufi.ip

  depends_on = [ovh_dedicated_server_reboot_task.kimsufi_to_talos]
}
