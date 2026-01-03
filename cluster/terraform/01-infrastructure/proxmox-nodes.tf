# Proxmox Home Nodes
# 1x controlplane (talos-pve-cp-0) + 1x worker (talos-pve-worker-0) on home Proxmox (atlas)
# Uses KubeSpan for mesh networking with VPS nodes

# ============================================================================
# TALOS IMAGE FACTORY - Generate custom Talos image with extensions
# ============================================================================

# Create schematic for Proxmox nodes
# Includes qemu-guest-agent for Proxmox integration and static IP via META
resource "talos_image_factory_schematic" "proxmox" {
  for_each = local.proxmox_nodes

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

# Get download URLs for the schematic
data "talos_image_factory_urls" "proxmox" {
  for_each = local.proxmox_nodes

  schematic_id  = talos_image_factory_schematic.proxmox[each.key].id
  talos_version = var.talos_version
  platform      = "metal"
  architecture  = "amd64"
}

# ============================================================================
# PROXMOX DISK IMAGES
# ============================================================================

# Download disk images to Proxmox
resource "proxmox_virtual_environment_download_file" "talos_disk" {
  for_each = local.proxmox_nodes

  content_type = "import"
  datastore_id = "local"
  node_name    = var.proxmox_node_name
  url          = replace(data.talos_image_factory_urls.proxmox[each.key].urls.disk_image, "metal-amd64.raw.zst", "metal-amd64.qcow2")
  file_name    = "talos-${talos_image_factory_schematic.proxmox[each.key].id}-amd64.qcow2"
  overwrite    = true
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
    import_from  = proxmox_virtual_environment_download_file.talos_disk[each.key].id
  }

  agent {
    enabled = true
    trim    = true
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
          }
          nodeIP = {
            validSubnets = ["10.2.0.0/16"]
          }
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
