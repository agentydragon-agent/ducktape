# Hetzner VPS Nodes
# 2x CPX31 controlplane+worker nodes in Hillsboro, OR
#
# Talos is pre-installed on a Hetzner snapshot (built by Packer via rescue+dd).
# Servers boot directly from the snapshot — single Talos boot, single identity.
# This eliminates the KubeSpan phantom peer problem from ISO-to-disk reboot.

# ============================================================================
# TALOS IMAGE FACTORY - Generate custom Talos image for Hetzner
# ============================================================================

resource "talos_image_factory_schematic" "hcloud" {
  schematic = yamlencode({
    customization = {
      systemExtensions = {
        officialExtensions = [
          "siderolabs/qemu-guest-agent",
          "siderolabs/iscsi-tools",
          "siderolabs/nebula",
        ]
      }
    }
  })
}

data "talos_image_factory_urls" "hcloud" {
  schematic_id  = talos_image_factory_schematic.hcloud.id
  talos_version = var.talos_version
  platform      = "hcloud"
  architecture  = "amd64"
}

# ============================================================================
# HETZNER SNAPSHOT - Built by Packer (rescue mode + dd)
# ============================================================================

resource "terraform_data" "talos_hcloud_image" {
  triggers_replace = [
    var.talos_version,
    talos_image_factory_schematic.hcloud.id,
  ]

  provisioner "local-exec" {
    working_dir = "${path.module}/packer"
    command     = <<-EOT
      set -e
      SELECTOR="os=talos,version=${var.talos_version},schematic_id=${substr(talos_image_factory_schematic.hcloud.id, 0, 8)}"
      if hcloud image list --type snapshot --selector "$SELECTOR" -o noheader 2>/dev/null | grep -q .; then
        echo "Snapshot already exists (selector: $SELECTOR), skipping Packer build"
        exit 0
      fi
      packer init talos-hcloud.pkr.hcl && \
      packer build \
        -var 'talos_image_url=${data.talos_image_factory_urls.hcloud.urls.disk_image}' \
        -var 'talos_version=${var.talos_version}' \
        -var 'schematic_id=${talos_image_factory_schematic.hcloud.id}' \
        -var 'server_location=${var.hetzner_location}' \
        talos-hcloud.pkr.hcl
    EOT
    environment = {
      HCLOUD_TOKEN = nonsensitive(var.hcloud_token)
    }
  }
}

data "hcloud_image" "talos" {
  with_selector     = "os=talos,version=${var.talos_version},schematic_id=${substr(talos_image_factory_schematic.hcloud.id, 0, 8)}"
  most_recent       = true
  with_architecture = "x86"

  depends_on = [terraform_data.talos_hcloud_image]
}

# ============================================================================
# VPS SERVERS
# ============================================================================

resource "hcloud_server" "vps" {
  for_each = local.vps_nodes

  name        = each.value.name
  server_type = each.value.server_type
  location    = var.hetzner_location
  image       = data.hcloud_image.talos.id
  ssh_keys    = [hcloud_ssh_key.talos.id]
  user_data   = data.talos_machine_configuration.vps[each.key].machine_configuration

  labels = {
    cluster = var.cluster_name
    role    = "controlplane"
    node    = each.key
  }

  backups = true

  firewall_ids = [hcloud_firewall.talos.id]

  public_net {
    ipv4_enabled = true
    ipv6_enabled = true
  }

  # Hetzner treats user_data and image as immutable — any change forces server
  # replacement. Talos only reads user_data on first boot; ongoing config is
  # managed via the Talos API (talos_machine_configuration_apply). Image changes
  # (new schematic) are applied via talosctl upgrade, not server replacement.
  lifecycle {
    ignore_changes = [user_data, image]
  }
}

# ============================================================================
# TALOS MACHINE CONFIGURATION
# ============================================================================

data "talos_machine_configuration" "vps" {
  for_each = local.vps_nodes

  cluster_name       = var.cluster_name
  cluster_endpoint   = local.cluster_endpoint
  machine_secrets    = local.machine_secrets
  machine_type       = "controlplane"
  talos_version      = var.talos_version
  kubernetes_version = var.kubernetes_version
  examples           = false
  docs               = false

  config_patches = [
    yamlencode({
      machine = merge(local.common_machine_base, {
        nodeLabels = {
          "topology.kubernetes.io/region"        = "hetzner"
          "topology.kubernetes.io/zone"          = var.hetzner_location
          "node.longhorn.io/create-default-disk" = "true"
        }
        kubelet = {
          extraArgs = {
            allowed-unsafe-sysctls = "net.ipv4.tcp_mtu_probing"
          }
        }
      })
      cluster = local.common_cluster_config
    }),
    # Hostname is set via HostnameConfig in data.talos_machine_configuration.vps_nebula.
    # NOTE: nebula_machine_patch is NOT included here — it references
    # hcloud_server.vps[*].ipv4_address which would create a dependency cycle
    # (hcloud_server.user_data → machine_config → nebula_patch → hcloud_server.ipv4_address).
    # Applied separately via talos_machine_configuration_apply.vps_nebula below.
  ]
}

# ============================================================================
# MACHINE CONFIGURATION APPLY
# ============================================================================

resource "talos_machine_configuration_apply" "vps" {
  for_each = local.vps_nodes

  client_configuration        = local.client_configuration
  machine_configuration_input = data.talos_machine_configuration.vps[each.key].machine_configuration
  node                        = hcloud_server.vps[each.key].ipv4_address

  depends_on = [hcloud_server.vps]
}

# Nebula config applied via a separate data source + apply to break the dependency cycle:
#   hcloud_server.user_data → data.talos_machine_configuration.vps (no nebula patch)
#   data.talos_machine_configuration.vps_nebula → nebula_patch → hcloud_server.ipv4_address
# hcloud_server.user_data only references the non-nebula data source, so no cycle.
data "talos_machine_configuration" "vps_nebula" {
  for_each = local.vps_nodes

  cluster_name       = var.cluster_name
  cluster_endpoint   = local.cluster_endpoint
  machine_secrets    = local.machine_secrets
  machine_type       = "controlplane"
  talos_version      = var.talos_version
  kubernetes_version = var.kubernetes_version
  examples           = false
  docs               = false

  config_patches = concat(
    [
      yamlencode({
        machine = merge(local.common_machine_base, {
          nodeLabels = {
            "topology.kubernetes.io/region"        = "hetzner"
            "topology.kubernetes.io/zone"          = var.hetzner_location
            "node.longhorn.io/create-default-disk" = "true"
          }
          kubelet = {
            extraArgs = {
              allowed-unsafe-sysctls = "net.ipv4.tcp_mtu_probing"
            }
          }
        })
        cluster = local.common_cluster_config
      }),
      # Explicit hostname — overrides the auto-generated HostnameConfig
      # (auto: stable) that the Terraform provider appends. Without this,
      # talosctl upgrade (kexec) loses the platform-derived hostname.
      yamlencode({
        apiVersion = "v1alpha1"
        kind       = "HostnameConfig"
        auto       = "off"
        hostname   = each.value.name
      }),
    ],
    local.nebula_machine_patches[each.key],
  )
}

resource "talos_machine_configuration_apply" "vps_nebula" {
  for_each = local.vps_nodes

  client_configuration        = local.client_configuration
  machine_configuration_input = data.talos_machine_configuration.vps_nebula[each.key].machine_configuration
  node                        = hcloud_server.vps[each.key].ipv4_address

  depends_on = [talos_machine_configuration_apply.vps]
}
