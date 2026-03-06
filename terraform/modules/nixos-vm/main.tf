# NixOS VM Module
# Creates a NixOS VM with cloud-init provisioning
# Configuration is managed via flake after initial bootstrap

terraform {
  required_version = ">= 1.0"

  required_providers {
    proxmox = {
      source  = "bpg/proxmox"
      version = ">= 0.91.0"
    }
  }
}

locals {
  cloud_init_user_data = templatefile("${path.module}/cloud-init.yaml.tpl", {
    username               = var.username
    ssh_public_key         = var.ssh_public_key
    hostname               = var.vm_name
    nixos_flake_url        = var.nixos_flake_url
    nixos_host             = var.nixos_host
    home_manager_flake_url = var.home_manager_flake_url
    home_manager_host      = var.home_manager_host
    k8s_cluster_join       = var.k8s_cluster_join
  })
}

# Cloud-init configuration
resource "proxmox_virtual_environment_file" "cloud_init_config" {
  content_type = "snippets"
  datastore_id = "local"
  node_name    = var.proxmox_node_name

  source_raw {
    data      = local.cloud_init_user_data
    file_name = "${var.vm_name}-cloud-init.yaml"
  }
}

# The VM
resource "proxmox_virtual_environment_vm" "vm" {
  name        = var.vm_name
  description = "NixOS VM - managed via flake ${var.nixos_flake_url}#${var.nixos_host}"
  node_name   = var.proxmox_node_name
  vm_id       = var.vm_id
  pool_id     = var.pool_id != "" ? var.pool_id : null
  bios        = "ovmf" # UEFI boot required for qcow-efi images

  cpu {
    cores = var.vcpus
    type  = "host"
  }

  memory {
    dedicated = var.memory_mb
  }

  efi_disk {
    datastore_id = var.storage
    file_format  = "raw"
    type         = "4m"
  }

  disk {
    datastore_id = var.storage
    import_from  = "local:import/nixos-cloud.qcow2"
    interface    = "scsi0"
    iothread     = true
    discard      = "on"
    size         = var.disk_size_gb
  }

  network_device {
    bridge = var.network_bridge
    model  = "virtio"
  }

  initialization {
    datastore_id = var.storage
    interface    = "sata0"

    ip_config {
      ipv4 {
        address = "dhcp"
      }
    }

    user_account {
      username = var.username
      keys     = var.ssh_public_key != "" ? [var.ssh_public_key] : []
      password = ""
    }

    user_data_file_id = proxmox_virtual_environment_file.cloud_init_config.id
  }

  started = var.auto_start

  agent {
    enabled = true
    timeout = "10m" # Wait longer for guest agent to report IP (cloud-init takes time)
  }

  # Ignore changes to cloud-init after creation - updates happen via nixos-rebuild
  lifecycle {
    ignore_changes = [
      initialization[0].user_data_file_id,
    ]
  }
}
