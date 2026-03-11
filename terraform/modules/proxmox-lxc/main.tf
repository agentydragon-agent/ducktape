# Proxmox LXC Module
# Creates an LXC container from a pre-built NixOS tarball on Proxmox.
# SSH keys are injected via Proxmox initialization.

terraform {
  required_version = ">= 1.0"

  required_providers {
    proxmox = {
      source  = "bpg/proxmox"
      version = ">= 0.91.0"
    }
  }
}

resource "proxmox_virtual_environment_container" "ct" {
  description  = "NixOS LXC - ${var.ct_name}"
  node_name    = var.proxmox_node_name
  vm_id        = var.ct_id
  pool_id      = var.pool_id != "" ? var.pool_id : null
  started      = true
  unprivileged = !var.privileged

  operating_system {
    template_file_id = var.template_file_id
    type             = "nixos"
  }

  cpu {
    cores = var.vcpus
  }

  memory {
    dedicated = var.memory_mb
    swap      = var.swap_mb
  }

  disk {
    datastore_id = var.storage
    size          = var.disk_size_gb
  }

  features {
    nesting = true
    keyctl  = true
  }

  network_interface {
    name   = "eth0"
    bridge = var.network_bridge
  }

  initialization {
    hostname = var.ct_name

    ip_config {
      ipv4 {
        address = "dhcp"
      }
    }

    user_account {
      keys     = var.ssh_public_key != "" ? [var.ssh_public_key] : []
      password = var.root_password
    }
  }

  dynamic "mount_point" {
    for_each = var.mount_points
    content {
      volume    = mount_point.value.volume
      path      = mount_point.value.path
      size      = lookup(mount_point.value, "size", null)
      read_only = lookup(mount_point.value, "read_only", null)
    }
  }

  startup {
    order = var.startup_order
  }
}
