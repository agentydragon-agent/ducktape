# K3s Cluster on Proxmox - Declarative Configuration

terraform {
  required_providers {
    proxmox = {
      source  = "bpg/proxmox"
      version = "~> 0.66"
    }
  }
}

# Providers
provider "proxmox" {
  endpoint  = "https://atlas.agentydragon.com/"
  api_token = var.proxmox_api_token

  ssh {
    agent    = true
    username = "root"
  }

  tmp_dir = "/var/tmp"
}



# Variables
variable "proxmox_api_token" {
  description = "Proxmox API token"
  type        = string
  sensitive   = true
}


# Ubuntu 24.04 Template VM (using manually downloaded image)
resource "proxmox_virtual_environment_vm" "ubuntu_24_04_template" {
  name      = "ubuntu-24.04-cloudinit-template"
  node_name = "atlas"
  vm_id     = 9001

  agent {
    enabled = true
    timeout = "5m"
    type    = "virtio"
  }

  cpu {
    cores   = 2
    sockets = 1
    units   = 1024
  }

  memory {
    dedicated = 2048
  }

  serial_device {
    device = "socket"
  }

  vga {
    type = "serial0"
  }

  disk {
    datastore_id = "local-zfs"
    size         = 32 # Template disk - will be resized on clone
    interface    = "scsi0"
    file_format  = "raw"
    cache        = "none"
    aio          = "io_uring"
    file_id      = "local:iso/ubuntu-24.04-cloudimg.img"
  }

  disk {
    datastore_id = "local-zfs"
    interface    = "ide2"
    file_format  = "raw"
    size         = 4 # Cloud-init disk
  }

  network_device {
    bridge = "vmbr0"
    model  = "virtio"
  }

  boot_order    = ["scsi0"]
  scsi_hardware = "virtio-scsi-pci"
  template      = true

  lifecycle {
    ignore_changes = [
      network_device[0].mac_address,
    ]
  }
}

# New VMs configuration
locals {
  new_nodes = {
    master2 = {
      name     = "k3s-master-2"
      vm_id    = 202
      ip       = "10.0.200.202/16"
      k3s_type = "agent" # Join existing cluster as worker (single-server cluster can't accept additional servers)
    }
    worker2 = {
      name     = "k3s-worker-2"
      vm_id    = 203
      ip       = "10.0.200.203/16"
      k3s_type = "agent" # Join existing cluster as worker
    }
  }

  vm_defaults = {
    cpu_cores      = 2
    cpu_sockets    = 1
    cpu_units      = 1024
    memory         = 4096
    disk_size      = 50
    disk_storage   = "local-zfs"
    network_bridge = "vmbr0"
    dns_servers    = ["8.8.8.8"]
    gateway        = "10.0.0.1"
    template_id    = proxmox_virtual_environment_vm.ubuntu_24_04_template.vm_id
  }
}

# New VMs (created with clean cloud-init)
module "new_vms" {
  source = "./modules/k3s-node"

  for_each = local.new_nodes

  node_name  = each.value.name
  vm_id      = each.value.vm_id
  ip_address = each.value.ip
  k3s_type   = each.value.k3s_type
  vm_config  = local.vm_defaults
  cloud_init_content = templatefile("${path.module}/cloud-init-basic.yaml.tpl", {
    hostname = each.value.name
  })
}

# Clean up - remove unused resources
# (Kubernetes connection removed - will be managed externally)

# Outputs  
output "k3s_cluster_config" {
  description = "k3s cluster configuration for Ansible"
  value = {
    nodes = [
      for k, v in local.new_nodes : {
        vm_id    = v.vm_id
        name     = v.name
        ip       = trimsuffix(v.ip, "/16")
        hostname = v.name
        k3s_type = v.k3s_type # Direct passthrough - no conversion!
      }
    ]
    cluster = {
      version = "v1.28.2+k3s1"
      cidr    = "10.42.0.0/16"
    }
  }
}

# Ansible-specific output - just the nodes list for easy consumption
output "k3s_nodes_ansible" {
  description = "K3s nodes list for Ansible playbook"
  value = [
    for k, v in local.new_nodes : {
      vm_id    = v.vm_id
      name     = v.name
      ip       = trimsuffix(v.ip, "/16")
      hostname = v.name
      k3s_type = v.k3s_type
    }
  ]
}
