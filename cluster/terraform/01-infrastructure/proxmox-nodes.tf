# Proxmox Home Nodes
# 1x controlplane (talos-pve-cp-0) + 1x worker (talos-pve-worker-0) on home Proxmox (atlas)
# Uses KubeSpan for mesh networking with VPS nodes

# ============================================================================
# TALOS IMAGE FACTORY - Generate custom Talos image with extensions
# ============================================================================

# =========================
# META MODE (per-node images with IP baked in)
# =========================

# Create per-node schematic with static IP via META key 0xa
resource "talos_image_factory_schematic" "proxmox" {
  for_each = var.proxmox_network_config_method == "meta" ? local.proxmox_nodes : {}

  schematic = yamlencode({
    customization = {
      extraKernelArgs = ["net.ifnames=0"]
      systemExtensions = {
        officialExtensions = [
          "siderolabs/qemu-guest-agent"
        ]
      }
      meta = [
        {
          key = 10 # META key 0xa for network configuration
          value = yamlencode({
            addresses = [
              {
                address  = "${each.value.ip}/16"
                linkName = "eth0"
                family   = "inet4"
                scope    = "global"
                flags    = "permanent"
                layer    = "platform"
              }
            ]
            routes = [
              {
                family      = "inet4"
                dst         = ""
                gateway     = local.proxmox_gateway
                outLinkName = "eth0"
                table       = "main"
                priority    = 1024
                scope       = "global"
                type        = "unicast"
                protocol    = "static"
                layer       = "platform"
              }
            ]
            hostnames = [
              {
                hostname = each.value.name
                layer    = "platform"
              }
            ]
            resolvers = [
              {
                dnsServers = ["1.1.1.1", "8.8.8.8"]
                layer      = "platform"
              }
            ]
          })
        }
      ]
    }
  })
}

# Get download URLs for per-node schematic
data "talos_image_factory_urls" "proxmox" {
  for_each = var.proxmox_network_config_method == "meta" ? local.proxmox_nodes : {}

  schematic_id  = talos_image_factory_schematic.proxmox[each.key].id
  talos_version = var.talos_version
  platform      = "metal"
  architecture  = "amd64"
}

# =========================
# CLOUDINIT MODE (shared image + per-node snippets)
# =========================

# Create shared schematic with just extensions (no network config)
resource "talos_image_factory_schematic" "proxmox_shared" {
  count = var.proxmox_network_config_method == "cloudinit" ? 1 : 0

  schematic = yamlencode({
    customization = {
      extraKernelArgs = ["net.ifnames=0"]
      systemExtensions = {
        officialExtensions = [
          "siderolabs/qemu-guest-agent"
        ]
      }
      # NO META network config - handled by cloud-init snippets
    }
  })
}

# Get download URLs for shared schematic
data "talos_image_factory_urls" "proxmox_shared" {
  count = var.proxmox_network_config_method == "cloudinit" ? 1 : 0

  schematic_id  = talos_image_factory_schematic.proxmox_shared[0].id
  talos_version = var.talos_version
  platform      = "metal"
  architecture  = "amd64"
}

# ============================================================================
# PROXMOX DISK IMAGES
# ============================================================================

# Download per-node disk images (META mode)
resource "proxmox_virtual_environment_download_file" "talos_disk" {
  for_each = var.proxmox_network_config_method == "meta" ? local.proxmox_nodes : {}

  content_type = "import"
  datastore_id = "local"
  node_name    = var.proxmox_node_name
  url          = replace(data.talos_image_factory_urls.proxmox[each.key].urls.disk_image, "metal-amd64.raw.zst", "metal-amd64.qcow2")
  file_name    = "talos-${talos_image_factory_schematic.proxmox[each.key].id}-amd64.qcow2"
  overwrite    = true
}

# Download shared disk image (CLOUDINIT mode) - one image for all nodes
resource "proxmox_virtual_environment_download_file" "talos_disk_shared" {
  count = var.proxmox_network_config_method == "cloudinit" ? 1 : 0

  content_type = "import"
  datastore_id = "local"
  node_name    = var.proxmox_node_name
  url          = replace(data.talos_image_factory_urls.proxmox_shared[0].urls.disk_image, "metal-amd64.raw.zst", "metal-amd64.qcow2")
  file_name    = "talos-shared-${talos_image_factory_schematic.proxmox_shared[0].id}-amd64.qcow2"
  overwrite    = true
}

# ============================================================================
# CLOUD-INIT NETWORK SNIPPETS (CLOUDINIT mode only)
# ============================================================================

# Create per-node network-config snippets for cloud-init
resource "proxmox_virtual_environment_file" "network_config" {
  for_each = var.proxmox_network_config_method == "cloudinit" ? local.proxmox_nodes : {}

  content_type = "snippets"
  datastore_id = "local"
  node_name    = var.proxmox_node_name

  source_raw {
    data = yamlencode({
      network = {
        version = 2
        ethernets = {
          eth0 = {
            dhcp4     = false
            dhcp6     = false
            addresses = ["${each.value.ip}/16"]
            gateway4  = local.proxmox_gateway
            nameservers = {
              addresses = ["1.1.1.1", "8.8.8.8"]
            }
          }
        }
      }
    })
    file_name = "talos-${each.key}-network.yaml"
  }
}

# ============================================================================
# PROXMOX VMS
# ============================================================================

resource "proxmox_virtual_environment_vm" "talos" {
  for_each = local.proxmox_nodes

  name            = each.value.name
  vm_id           = each.value.vm_id
  node_name       = var.proxmox_node_name
  tags            = sort(["talos", each.value.type, "kubernetes", "terraform", "hybrid"])
  stop_on_destroy = true
  bios            = "ovmf"
  machine         = "q35"
  scsi_hardware   = "virtio-scsi-single"

  operating_system {
    type = "l26"
  }

  cpu {
    type  = "host"
    cores = 4
  }

  memory {
    dedicated = 12 * 1024                                       # 12GB max
    floating  = each.value.type == "controlplane" ? 4096 : 6144 # 4GB controllers, 6GB workers
  }

  vga {
    type = "qxl"
  }

  network_device {
    bridge = "vmbr4"
  }

  efi_disk {
    datastore_id = "local-zfs"
    file_format  = "raw"
    type         = "4m"
  }

  disk {
    datastore_id = "local-zfs"
    interface    = "scsi0"
    iothread     = true
    ssd          = true
    discard      = "on"
    size         = 40
    file_format  = "raw"
    # Use per-node image in META mode, shared image in CLOUDINIT mode
    import_from = (
      var.proxmox_network_config_method == "cloudinit"
      ? proxmox_virtual_environment_download_file.talos_disk_shared[0].id
      : proxmox_virtual_environment_download_file.talos_disk[each.key].id
    )
  }

  agent {
    enabled = true
    trim    = true
  }

  # Cloud-init drive for network configuration (CLOUDINIT mode only)
  dynamic "initialization" {
    for_each = var.proxmox_network_config_method == "cloudinit" ? [1] : []
    content {
      datastore_id         = "local-zfs"
      network_data_file_id = proxmox_virtual_environment_file.network_config[each.key].id
    }
  }
}

# ============================================================================
# TALOS MACHINE CONFIGURATION
# ============================================================================

data "talos_machine_configuration" "proxmox" {
  for_each = local.proxmox_nodes

  cluster_name       = var.cluster_name
  cluster_endpoint   = local.cluster_endpoint
  machine_secrets    = local.machine_secrets
  machine_type       = each.value.type
  talos_version      = var.talos_version
  kubernetes_version = var.kubernetes_version
  examples           = false
  docs               = false

  config_patches = [
    # Common configuration for all nodes
    yamlencode({
      machine = {
        network = {
          kubespan = {
            enabled             = true
            allowDownPeerBypass = true
          }
          # Disable DHCP for workers (controllers get it via VIP config)
          interfaces = each.value.type == "worker" ? [{
            interface = "eth0"
            dhcp      = false
          }] : null
        }
        nodeLabels = {
          "topology.kubernetes.io/region" = "proxmox"
          "topology.kubernetes.io/zone"   = "atlas"
        }
        features = {
          kubePrism = {
            enabled = true
            port    = 7445
          }
        }
        kubelet = {
          extraArgs = {
            provider-id = "proxmox://cluster/${each.value.vm_id}"
            # Allow TCP MTU probing sysctl for PowerDNS AXFR over Tailscale/KubeSpan
            # Required to handle MTU mismatch (WireGuard 1280 vs pod 1500)
            allowed-unsafe-sysctls = "net.ipv4.tcp_mtu_probing"
          }
          # No nodeIP.validSubnets - let kubelet auto-detect
          # KubeSpan IPv6 IPs (fd05::/64) are globally routable via WireGuard mesh
        }
      }
      cluster = {
        # Allow scheduling on controlplanes for consistency with VPS nodes
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

# Apply machine configuration to Proxmox nodes
resource "talos_machine_configuration_apply" "proxmox" {
  for_each = local.proxmox_nodes

  client_configuration        = local.client_configuration
  machine_configuration_input = data.talos_machine_configuration.proxmox[each.key].machine_configuration
  node                        = each.value.ip

  depends_on = [
    proxmox_virtual_environment_vm.talos,
    talos_machine_bootstrap.cluster # Wait for cluster to be bootstrapped first
  ]
}
