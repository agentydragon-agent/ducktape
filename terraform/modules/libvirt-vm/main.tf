# Libvirt VM Module (0.9.x provider schema)
# Creates a VM from a pre-built qcow2 image on a local QEMU/KVM host.
# SSH keys and optional cloud-init userdata are injected via NoCloud ISO.

terraform {
  required_version = ">= 1.0"

  required_providers {
    libvirt = {
      source  = "dmacvicar/libvirt"
      version = ">= 0.9.0"
    }
  }
}

# Base volume from pre-built qcow2
resource "libvirt_volume" "os_image" {
  name = "${var.vm_name}-base.qcow2"
  pool = var.storage_pool
  target = {
    format = {
      type = "qcow2"
    }
  }
  create = {
    content = {
      url = var.qcow2_image_path
    }
  }
}

# CoW overlay disk with desired size
resource "libvirt_volume" "os_disk" {
  name     = "${var.vm_name}.qcow2"
  pool     = var.storage_pool
  capacity = var.disk_size_gb * 1024 * 1024 * 1024
  target = {
    format = {
      type = "qcow2"
    }
  }
  backing_store = {
    path = libvirt_volume.os_image.path
    format = {
      type = "qcow2"
    }
  }
}

# Cloud-init ISO (only when cloud_init_user_data is provided)
resource "libvirt_cloudinit_disk" "cloud_init" {
  count     = var.cloud_init_user_data != null ? 1 : 0
  name      = "${var.vm_name}-cloudinit"
  user_data = var.cloud_init_user_data
  meta_data = yamlencode({
    instance-id    = var.vm_name
    local-hostname = var.vm_name
  })
}

# Upload cloud-init ISO to storage pool
resource "libvirt_volume" "cloud_init" {
  count = var.cloud_init_user_data != null ? 1 : 0
  name  = "${var.vm_name}-cloudinit.iso"
  pool  = var.storage_pool
  create = {
    content = {
      url = libvirt_cloudinit_disk.cloud_init[0].path
    }
  }
}

# The VM
resource "libvirt_domain" "vm" {
  name        = var.vm_name
  type        = "kvm"
  vcpu        = var.vcpus
  memory      = var.memory_mb
  memory_unit = "MiB"

  cpu = {
    mode = "host-passthrough"
  }

  os = {
    type            = "hvm"
    type_arch       = "x86_64"
    type_machine    = "q35"
    firmware        = "efi"
    loader          = var.uefi_firmware_path
    loader_readonly = true
    loader_type     = "pflash"
  }

  devices = {
    disks = concat(
      [
        {
          source = {
            volume = {
              pool   = libvirt_volume.os_disk.pool
              volume = libvirt_volume.os_disk.name
            }
          }
          target = {
            dev = "vda"
            bus = "virtio"
          }
          driver = {
            type = "qcow2"
          }
        }
      ],
      var.cloud_init_user_data != null ? [
        {
          device = "cdrom"
          source = {
            volume = {
              pool   = libvirt_volume.cloud_init[0].pool
              volume = libvirt_volume.cloud_init[0].name
            }
          }
          target = {
            dev = "sda"
            bus = "sata"
          }
        }
      ] : []
    )

    interfaces = [
      {
        model = {
          type = "virtio"
        }
        source = {
          network = {
            network = var.network_name
          }
        }
        wait_for_ip = {}
      }
    ]

    consoles = [
      {
        target = {
          type = "serial"
          port = 0
        }
      }
    ]

    graphics = [
      {
        vnc = {
          auto_port = true
        }
      }
    ]
  }

  autostart = var.auto_start

  lifecycle {
    ignore_changes = [
      # Cloud-init is one-shot; don't re-create VM on template changes
      devices,
    ]
  }
}

# Query IP addresses after domain creation
data "libvirt_domain_interface_addresses" "vm" {
  domain = libvirt_domain.vm.name
  source = "lease"
}
