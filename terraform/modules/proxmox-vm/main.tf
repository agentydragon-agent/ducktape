# Proxmox VM Module
# Creates a VM from a pre-built qcow2 image on Proxmox.
#
# Cloud-init / k8s credential injection was removed — the only consumer
# (wyrm2) uses NixOS declarative config instead. To re-add cloud-init,
# see the bpg/proxmox provider docs for the `initialization` block and
# `proxmox_virtual_environment_file` (snippets) resource.

terraform {
  required_version = ">= 1.0"

  required_providers {
    proxmox = {
      source  = "bpg/proxmox"
      version = ">= 0.91.0"
    }
  }
}

# The VM
resource "proxmox_virtual_environment_vm" "vm" {
  name        = var.vm_name
  description = "NixOS VM - ${var.vm_name}"
  node_name   = var.proxmox_node_name
  vm_id       = var.vm_id
  pool_id     = var.pool_id != "" ? var.pool_id : null
  bios        = "ovmf" # UEFI boot required for qcow-efi images
  machine     = var.machine_type

  cpu {
    cores = var.vcpus
    type  = "host"
  }

  memory {
    dedicated = var.memory_mb
    floating  = var.memory_floating_mb
  }

  # GPU passthrough via raw PCI device IDs
  dynamic "hostpci" {
    for_each = { for i, id in var.gpu_pci_ids : i => id }
    content {
      device = "hostpci${hostpci.key}"
      id     = hostpci.value
      pcie   = true
      rombar = true
    }
  }

  # Audio device (e.g. ich9-intel-hda with spice driver for SPICE client audio)
  dynamic "audio_device" {
    for_each = var.audio_device != null ? [var.audio_device] : []
    content {
      device  = audio_device.value
      driver  = var.audio_driver
      enabled = true
    }
  }

  # USB devices (e.g. SPICE USB redirection)
  dynamic "usb" {
    for_each = var.usb_devices
    content {
      host = usb.value.host
      usb3 = usb.value.usb3
    }
  }

  # VGA display (e.g. virtio for VNC console, qxl for SPICE)
  dynamic "vga" {
    for_each = var.vga_type != null ? [var.vga_type] : []
    content {
      type   = vga.value
      memory = var.vga_memory_mb
    }
  }

  # virtiofs shared filesystems from Proxmox host
  dynamic "virtiofs" {
    for_each = var.virtiofs_mounts
    content {
      mapping = virtiofs.value.mapping
      cache   = virtiofs.value.cache
    }
  }

  efi_disk {
    datastore_id = var.storage
    file_format  = "raw"
    type         = "4m"
  }

  disk {
    datastore_id = var.storage
    import_from  = var.image_import_path
    interface    = "scsi0"
    iothread     = true
    discard      = "on"
    size         = var.disk_size_gb
  }

  # Additional data disks at explicit SCSI slots (use high numbers to avoid CSI range)
  dynamic "disk" {
    for_each = { for d in var.additional_disks : d.interface => d }
    content {
      datastore_id = coalesce(disk.value.datastore_id, var.storage)
      interface    = disk.value.interface
      iothread     = true
      discard      = "on"
      size         = disk.value.size_gb
      file_format  = "raw"
    }
  }

  network_device {
    bridge = var.network_bridge
    model  = "virtio"
  }

  started = var.auto_start

  agent {
    enabled = true
    timeout = "2m"
  }

  lifecycle {
    ignore_changes = [
      disk,           # CSI driver attaches PVC disks dynamically; tofu can't distinguish them
      initialization, # Stale cloud-init ISO may exist on disk; don't touch it
    ]
  }
}
