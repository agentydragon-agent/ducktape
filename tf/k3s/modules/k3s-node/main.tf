terraform {
  required_providers {
    proxmox = {
      source  = "bpg/proxmox"
      version = "~> 0.66"
    }
  }
}

# Cloud-init file - ensure datastore supports snippets 
resource "proxmox_virtual_environment_file" "cloud_init" {
  count = var.cloud_init_content != null ? 1 : 0

  content_type = "snippets"
  datastore_id = "local" # We'll need to enable snippets or use different datastore
  node_name    = var.proxmox_node
  overwrite    = true

  source_raw {
    file_name = "${var.node_name}-cloud-init.yaml"
    data      = var.cloud_init_content
  }
}

# The k3s node VM
resource "proxmox_virtual_environment_vm" "node" {
  name      = var.node_name
  node_name = var.proxmox_node
  vm_id     = var.vm_id

  # Clone from template
  clone {
    vm_id = var.vm_config.template_id
    full  = true
  }

  agent {
    enabled = true
    timeout = "15m"
    type    = "virtio"
  }

  cpu {
    cores   = var.vm_config.cpu_cores
    sockets = var.vm_config.cpu_sockets
    units   = var.vm_config.cpu_units
  }

  memory {
    dedicated = var.vm_config.memory
  }

  serial_device {
    device = "socket"
  }

  disk {
    datastore_id = var.vm_config.disk_storage
    size         = var.vm_config.disk_size
    interface    = "scsi0"
    file_format  = "raw"
    cache        = "none"
    aio          = "io_uring"
  }

  network_device {
    bridge = var.vm_config.network_bridge
    model  = "virtio"
  }

  initialization {
    datastore_id = var.vm_config.disk_storage
    interface    = "ide2"

    dns {
      servers = var.vm_config.dns_servers
    }

    ip_config {
      ipv4 {
        address = var.ip_address
        gateway = var.vm_config.gateway
      }
    }

    user_account {
      username = "ubuntu"
      keys     = [] # No SSH keys for security
    }

    # Use cloud-init file if provided
    user_data_file_id = var.cloud_init_content != null ? proxmox_virtual_environment_file.cloud_init[0].id : null
  }

  on_boot         = true
  keyboard_layout = "en-us"

  operating_system {
    type = "l26"
  }

  lifecycle {
    ignore_changes = [
      vm_id,
      node_name,
      clone,
      network_device[0].mac_address,
      initialization[0].user_account[0].password
    ]
  }
}
