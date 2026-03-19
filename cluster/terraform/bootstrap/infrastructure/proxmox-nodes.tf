# Proxmox Home Nodes
# 1x controlplane (talos-pve-cp-0) on home Proxmox (atlas), 24 GB RAM
# 1x GPU worker (talos-pve-gpu-worker-0) with 2x RTX 5090, 32 GB fixed RAM
# Uses KubeSpan for mesh networking with VPS nodes

# ============================================================================
# TALOS IMAGE FACTORY - Generate custom Talos image with extensions
# ============================================================================

# Shared schematic with just extensions (network config via cloud-init snippets)
resource "talos_image_factory_schematic" "proxmox" {
  schematic = yamlencode({
    customization = {
      extraKernelArgs = ["net.ifnames=0"]
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

# Get download URL for shared schematic
data "talos_image_factory_urls" "proxmox" {
  schematic_id  = talos_image_factory_schematic.proxmox.id
  talos_version = var.talos_version
  platform      = "nocloud" # nocloud platform reads cloud-init from cidata ISO
  architecture  = "amd64"
}

# GPU schematic — disabled: GPUs now on wyrm2 (NixOS bare-metal), not Talos VM.
# resource "talos_image_factory_schematic" "proxmox_gpu" {
#   schematic = yamlencode({
#     customization = {
#       extraKernelArgs = ["net.ifnames=0"]
#       systemExtensions = {
#         officialExtensions = [
#           "siderolabs/qemu-guest-agent",
#           "siderolabs/iscsi-tools",
#           "siderolabs/nvidia-open-gpu-kernel-modules",
#           "siderolabs/nvidia-container-toolkit",
#         ]
#       }
#     }
#   })
# }
#
# data "talos_image_factory_urls" "proxmox_gpu" {
#   schematic_id  = talos_image_factory_schematic.proxmox_gpu.id
#   talos_version = var.talos_version
#   platform      = "nocloud"
#   architecture  = "amd64"
# }

# ============================================================================
# PROXMOX DISK IMAGES
# ============================================================================

# Standard disk image for non-GPU nodes
resource "proxmox_virtual_environment_download_file" "talos_disk" {
  content_type = "import"
  datastore_id = "local" # dir storage, configured via ansible for images content
  node_name    = var.proxmox_node_name
  # Replace any .raw.xz or .raw.zst extension with .qcow2 for Proxmox import
  url       = replace(replace(data.talos_image_factory_urls.proxmox.urls.disk_image, ".raw.xz", ".qcow2"), ".raw.zst", ".qcow2")
  file_name = "talos-${talos_image_factory_schematic.proxmox.id}-amd64.qcow2"
  overwrite = true
}

# GPU disk image — disabled: GPUs now on wyrm2.
# resource "proxmox_virtual_environment_download_file" "talos_disk_gpu" {
#   content_type = "import"
#   datastore_id = "local"
#   node_name    = var.proxmox_node_name
#   url          = replace(replace(data.talos_image_factory_urls.proxmox_gpu.urls.disk_image, ".raw.xz", ".qcow2"), ".raw.zst", ".qcow2")
#   file_name    = "talos-gpu-${talos_image_factory_schematic.proxmox_gpu.id}-amd64.qcow2"
#   overwrite    = true
# }

# ============================================================================
# GPU PCI HARDWARE MAPPINGS
# ============================================================================

# GPU PCI mappings — disabled: GPUs now on wyrm2 (bare-metal passthrough).
# resource "proxmox_virtual_environment_hardware_mapping_pci" "gpu0" {
#   name    = "gpu0"
#   comment = "NVIDIA RTX 5090 #0 (ZOTAC)"
#   map = [
#     {
#       id           = "10de:2b85"
#       iommu_group  = 14
#       node         = var.proxmox_node_name
#       path         = "0000:01:00.0"
#       subsystem_id = "19da:1761"
#     },
#   ]
# }
#
# resource "proxmox_virtual_environment_hardware_mapping_pci" "gpu1" {
#   name    = "gpu1"
#   comment = "NVIDIA RTX 5090 #1 (Gigabyte)"
#   map = [
#     {
#       id           = "10de:2b85"
#       iommu_group  = 16
#       node         = var.proxmox_node_name
#       path         = "0000:03:00.0"
#       subsystem_id = "1458:416f"
#     },
#   ]
# }

# ============================================================================
# CLOUD-INIT NETWORK SNIPPETS
# ============================================================================

# Create per-node network-config snippets for cloud-init (all Proxmox nodes)
resource "proxmox_virtual_environment_file" "network_config" {
  for_each = local.proxmox_nodes

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
    dedicated = 8 * 1024 # 8GB (pure control plane, no workloads)
    floating  = 0        # Disable balloon — OOM kills kube-apiserver when ballooned down
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
    size         = 300
    file_format  = "raw"
    import_from  = proxmox_virtual_environment_download_file.talos_disk.id
  }

  # Dedicated Longhorn storage disk (mounted at /var/mnt/longhorn by Talos).
  # Uses scsi30 (highest slot) to avoid conflicts with Proxmox CSI which
  # allocates upward from scsi1 for PVC volumes.
  disk {
    datastore_id = "local-zfs"
    interface    = "scsi30"
    iothread     = true
    ssd          = true
    discard      = "on"
    size         = var.longhorn_disk_size_gb
    file_format  = "raw"
  }

  agent {
    enabled = true
    trim    = true
  }

  # Cloud-init drive for network configuration
  initialization {
    datastore_id         = "local-zfs"
    network_data_file_id = proxmox_virtual_environment_file.network_config[each.key].id
  }
}

# GPU worker VMs — disabled: GPUs now on wyrm2 (NixOS bare-metal).
# resource "proxmox_virtual_environment_vm" "talos_gpu" {
#   for_each = local.proxmox_gpu_nodes
#
#   name            = each.value.name
#   vm_id           = each.value.vm_id
#   node_name       = var.proxmox_node_name
#   tags            = sort(["talos", each.value.type, "kubernetes", "terraform", "hybrid", "gpu"])
#   stop_on_destroy = true
#   bios            = "ovmf"
#   machine         = "q35"
#   scsi_hardware   = "virtio-scsi-single"
#
#   operating_system {
#     type = "l26"
#   }
#
#   cpu {
#     type  = "host"
#     cores = 8
#   }
#
#   memory {
#     dedicated = 32 * 1024
#     floating  = 0
#   }
#
#   vga {
#     type = "qxl"
#   }
#
#   network_device {
#     bridge = "vmbr4"
#   }
#
#   efi_disk {
#     datastore_id = "local-zfs"
#     file_format  = "raw"
#     type         = "4m"
#   }
#
#   disk {
#     datastore_id = "local-zfs"
#     interface    = "scsi0"
#     iothread     = true
#     ssd          = true
#     discard      = "on"
#     size         = 300
#     file_format  = "raw"
#     import_from  = proxmox_virtual_environment_download_file.talos_disk_gpu.id
#   }
#
#   disk {
#     datastore_id = "local-zfs"
#     interface    = "scsi30"
#     iothread     = true
#     ssd          = true
#     discard      = "on"
#     size         = var.longhorn_disk_size_gb
#     file_format  = "raw"
#   }
#
#   agent {
#     enabled = true
#     trim    = true
#   }
#
#   hostpci {
#     device  = "hostpci0"
#     mapping = proxmox_virtual_environment_hardware_mapping_pci.gpu0.name
#     pcie    = true
#     rombar  = true
#   }
#
#   hostpci {
#     device  = "hostpci1"
#     mapping = proxmox_virtual_environment_hardware_mapping_pci.gpu1.name
#     pcie    = true
#     rombar  = true
#   }
#
#   initialization {
#     datastore_id         = "local-zfs"
#     network_data_file_id = proxmox_virtual_environment_file.network_config[each.key].id
#   }
# }

# ============================================================================
# TALOS MACHINE CONFIGURATION
# ============================================================================

# Common config patch builder for all Proxmox nodes
locals {
  # Base config patch shared by all Proxmox nodes
  proxmox_base_config_patch = {
    machine = local.common_machine_base
    cluster = local.common_cluster_config
  }

  # Worker LinkConfig: disable DHCP on eth0
  worker_link_config = yamlencode({
    apiVersion = "v1alpha1"
    kind       = "LinkConfig"
    name       = "eth0"
    up         = true
  })

  # Common node labels for all Proxmox nodes
  proxmox_node_labels = {
    "topology.kubernetes.io/region"                   = "proxmox"
    "topology.kubernetes.io/zone"                     = "atlas"
    "csi.proxmox.sinextra.dev/max-volume-attachments" = "29"
    "node.longhorn.io/create-default-disk"            = "true"
  }

  # Longhorn dedicated disk mount (selected by stable by-id path).
  # Proxmox with virtio-scsi-single uses the drive ID (drive-scsi<N>) as the
  # SCSI device_id, which udev exposes as /dev/disk/by-id/scsi-0QEMU_QEMU_HARDDISK_drive-scsi<N>.
  # This is stable regardless of how many CSI PVC disks are attached.
  longhorn_disk_config = yamlencode({
    machine = {
      disks = [
        {
          device = "/dev/disk/by-id/scsi-0QEMU_QEMU_HARDDISK_drive-scsi30"
          partitions = [
            { mountpoint = "/var/mnt/longhorn" }
          ]
        }
      ]
    }
  })

  # NVIDIA-specific config patches — disabled: GPUs now on wyrm2.
  # nvidia_config_patches = [
  #   yamlencode({
  #     machine = {
  #       kernel = {
  #         modules = [
  #           { name = "nvidia" },
  #           { name = "nvidia_uvm" },
  #           { name = "nvidia_drm" },
  #           { name = "nvidia_modeset" },
  #         ]
  #       }
  #       sysctls = {
  #         "net.core.bpf_jit_harden" = "1"
  #       }
  #       files = [
  #         {
  #           path        = "/etc/cri/conf.d/20-customization.part"
  #           op          = "create"
  #           content     = <<-EOT
  #             [plugins]
  #               [plugins."io.containerd.cri.v1.runtime"]
  #                 [plugins."io.containerd.cri.v1.runtime".containerd]
  #                   default_runtime_name = "nvidia"
  #           EOT
  #           permissions = 0
  #         }
  #       ]
  #     }
  #   }),
  # ]
}

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

  config_patches = concat(
    [yamlencode(merge(local.proxmox_base_config_patch, {
      machine = merge(local.proxmox_base_config_patch.machine, {
        # Explicit network config — cloud-init network-config isn't preserved
        # across talosctl upgrade (kexec or powercycle). Without this, the node
        # gets a DHCP address instead of the configured static IP.
        network = merge(local.proxmox_base_config_patch.machine.network, {
          interfaces = [{
            interface = "eth0"
            dhcp      = false
            addresses = ["${each.value.ip}/16"]
            routes = [{
              network = "0.0.0.0/0"
              gateway = local.proxmox_gateway
            }]
          }]
          nameservers = ["1.1.1.1", "8.8.8.8"]
        })
        nodeLabels = local.proxmox_node_labels
        kubelet = {
          extraArgs = {
            provider-id            = "proxmox://cluster/${each.value.vm_id}"
            allowed-unsafe-sysctls = "net.ipv4.tcp_mtu_probing"
            # TODO: Make PVE CP mostly unschedulable — only allow core quorum
            # services (Vault, etc.) that need a third node when a VPS goes down.
            register-with-taints = "node-role.kubernetes.io/control-plane=:NoSchedule"
          }
        }
      })
      })),
      # Explicit hostname — overrides HostnameConfig auto: stable (Talos v1.12+).
      # Also needed because `talosctl upgrade` uses kexec which doesn't re-read
      # nocloud platform metadata (cloud-init). Without this, the node loses BOTH
      # its hostname AND static IP after upgrade (gets DHCP address instead of
      # the configured static IP, breaking etcd peering).
      # Use `talosctl upgrade --reboot-mode powercycle` as a workaround if this
      # patch isn't applied before upgrade.
      yamlencode({
        apiVersion = "v1alpha1"
        kind       = "HostnameConfig"
        auto       = "off"
        hostname   = each.value.name
      }),
    ],
    each.value.type == "worker" ? [local.worker_link_config] : [],
    [local.longhorn_disk_config],
    local.nebula_machine_patches[each.key],
  )
}

# GPU machine config — disabled: GPUs now on wyrm2.
# data "talos_machine_configuration" "proxmox_gpu" {
#   for_each = local.proxmox_gpu_nodes
#
#   cluster_name       = var.cluster_name
#   cluster_endpoint   = local.cluster_endpoint
#   machine_secrets    = local.machine_secrets
#   machine_type       = each.value.type
#   talos_version      = var.talos_version
#   kubernetes_version = var.kubernetes_version
#   examples           = false
#   docs               = false
#
#   config_patches = concat(
#     [yamlencode(merge(local.proxmox_base_config_patch, {
#       machine = merge(local.proxmox_base_config_patch.machine, {
#         nodeLabels = local.proxmox_node_labels
#         kubelet = {
#           extraArgs = {
#             provider-id            = "proxmox://cluster/${each.value.vm_id}"
#             allowed-unsafe-sysctls = "net.ipv4.tcp_mtu_probing"
#             register-with-taints   = "nvidia.com/gpu=true:PreferNoSchedule"
#           }
#         }
#       })
#     }))],
#     local.nvidia_config_patches,
#     [local.worker_link_config],
#     [local.longhorn_disk_config],
#   )
# }

# ============================================================================
# MACHINE CONFIGURATION APPLY
# ============================================================================

resource "talos_machine_configuration_apply" "proxmox" {
  for_each = local.proxmox_nodes

  client_configuration        = local.client_configuration
  machine_configuration_input = data.talos_machine_configuration.proxmox[each.key].machine_configuration
  node                        = each.value.ip

  depends_on = [proxmox_virtual_environment_vm.talos]
}

# GPU config apply — disabled: GPUs now on wyrm2.
# resource "talos_machine_configuration_apply" "proxmox_gpu" {
#   for_each = local.proxmox_gpu_nodes
#
#   client_configuration        = local.client_configuration
#   machine_configuration_input = data.talos_machine_configuration.proxmox_gpu[each.key].machine_configuration
#   node                        = each.value.ip
#
#   depends_on = [proxmox_virtual_environment_vm.talos_gpu]
# }
