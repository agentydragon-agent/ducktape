# Hetzner VPS Nodes
# 2x CPX31 controlplane+worker nodes in Hillsboro, OR
#
# All nodes get config applied in parallel. They install to disk, reboot,
# and wait in an etcd join retry loop until talos_machine_bootstrap is called
# on one node. etcd handles sequential learner promotion internally.

# ============================================================================
# VPS SERVERS
# ============================================================================

resource "hcloud_server" "vps" {
  for_each = local.vps_nodes

  name        = each.value.name
  server_type = each.value.server_type
  location    = var.hetzner_location
  image       = "debian-12"
  iso         = local.talos_iso
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
          hostDNS = {
            enabled              = true
            forwardKubeDNSToHost = true
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

# ============================================================================
# ISO DETACHMENT
# ============================================================================

resource "terraform_data" "detach_iso" {
  for_each = local.vps_nodes

  triggers_replace = [hcloud_server.vps[each.key].id]

  provisioner "local-exec" {
    command = "hcloud server detach-iso ${hcloud_server.vps[each.key].id}"
    environment = {
      HCLOUD_TOKEN = var.hcloud_token
    }
  }

  depends_on = [talos_machine_configuration_apply.vps]
}
