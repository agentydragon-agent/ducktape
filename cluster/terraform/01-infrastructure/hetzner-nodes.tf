# Hetzner VPS Nodes
# 2x CPX31 controlplane+worker nodes in Hillsboro, OR

# ============================================================================
# VPS SERVERS
# ============================================================================

# VPS servers using Hetzner's public Talos ISO
# ISO boots → reads user_data → auto-installs to disk → reboots
resource "hcloud_server" "vps" {
  for_each = local.vps_nodes

  name        = each.value.name
  server_type = each.value.server_type
  location    = var.hetzner_location
  image       = "debian-12"     # Base image for disk provisioning (overwritten by Talos install)
  iso         = local.talos_iso # Boot from Talos ISO
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
      machine = {
        # Auto-install to disk when booting from ISO
        install = {
          disk = "/dev/sda"
        }
        network = {
          hostname = each.value.name
          kubespan = {
            enabled             = true
            allowDownPeerBypass = true
          }
        }
        nodeLabels = {
          "topology.kubernetes.io/region" = "hetzner"
          "topology.kubernetes.io/zone"   = var.hetzner_location
        }
        features = {
          kubePrism = {
            enabled = true
            port    = 7445
          }
        }
        kubelet = {
          # Allow TCP MTU probing sysctl for PowerDNS AXFR over Tailscale/KubeSpan
          # Required to handle MTU mismatch (WireGuard 1280 vs pod 1500)
          extraArgs = {
            allowed-unsafe-sysctls = "net.ipv4.tcp_mtu_probing"
          }
        }
      }
      cluster = {
        # Each VPS controlplane node consumes a whole VPS instance, so we need
        # to allow scheduling workloads on them to utilize the VPS resources
        allowSchedulingOnControlPlanes = true
        discovery = {
          enabled = true
        }
        network = {
          cni = { name = "none" }
        }
        proxy = { disabled = true }
      }
    })
  ]
}

# Apply machine configuration to each VPS node
resource "talos_machine_configuration_apply" "vps" {
  for_each = local.vps_nodes

  client_configuration        = local.client_configuration
  machine_configuration_input = data.talos_machine_configuration.vps[each.key].machine_configuration
  node                        = hcloud_server.vps[each.key].ipv4_address

  depends_on = [hcloud_server.vps]
}
