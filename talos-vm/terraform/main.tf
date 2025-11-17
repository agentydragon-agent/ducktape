# Provider configuration
provider "libvirt" {
  uri = var.libvirt_uri
}

provider "talos" {}

# Generate Talos machine secrets
resource "talos_machine_secrets" "this" {
  talos_version = var.talos_version
}

# Generate Talos client configuration
data "talos_client_configuration" "this" {
  cluster_name         = var.cluster_name
  client_configuration = talos_machine_secrets.this.client_configuration
  endpoints            = ["127.0.0.1"]
  nodes                = ["127.0.0.1"]
}

# Create custom Image Factory schematic (vanilla Talos for now)
resource "talos_image_factory_schematic" "this" {
  schematic = yamlencode({
    customization = {
      # No system extensions needed for basic setup
      systemExtensions = {
        officialExtensions = []
      }
    }
  })
}

# Get Image Factory URLs for downloading Talos images
data "talos_image_factory_urls" "this" {
  talos_version = var.talos_version
  schematic_id  = talos_image_factory_schematic.this.id
  platform      = "metal"
  architecture  = "amd64"
}

# Generate control plane machine configuration
data "talos_machine_configuration" "controlplane" {
  cluster_name     = var.cluster_name
  cluster_endpoint = "https://127.0.0.1:6443"
  machine_type     = "controlplane"
  machine_secrets  = talos_machine_secrets.this.machine_secrets
  talos_version    = var.talos_version
  kubernetes_version = var.kubernetes_version

  config_patches = [
    yamlencode({
      machine = {
        certSANs = ["127.0.0.1"]

        time = {
          disabled = true # NTP blocked, rely on QEMU RTC sync
        }

        env = {
          HTTP_PROXY  = var.proxy_url
          HTTPS_PROXY = var.proxy_url
          NO_PROXY    = var.no_proxy
        }

        network = {
          nameservers = var.dns_servers
        }

        install = {
          disk  = "/dev/vda" # virtio disk
          image = data.talos_image_factory_urls.this.urls.installer
        }

        registries = {
          config = {
            for registry in var.insecure_registries : registry => {
              tls = {
                insecureSkipVerify = true
              }
            }
          }
        }

        kubelet = {
          image = "ghcr.io/siderolabs/kubelet:${var.kubernetes_version}"
        }
      }

      cluster = {
        network = {
          dnsDomain = "cluster.local"
          podSubnets = ["10.244.0.0/16"]
          serviceSubnets = ["10.96.0.0/12"]
        }
      }
    })
  ]
}

# Create libvirt storage pool (if not exists)
resource "libvirt_pool" "talos" {
  name = "${var.cluster_name}-pool"
  type = "dir"
  path = "/var/lib/libvirt/images/${var.cluster_name}"
}

# Download Talos kernel
resource "libvirt_volume" "talos_kernel" {
  name   = "${var.cluster_name}-kernel"
  pool   = libvirt_pool.talos.name
  source = data.talos_image_factory_urls.this.urls.kernel
  format = "raw"
}

# Download Talos initramfs
resource "libvirt_volume" "talos_initramfs" {
  name   = "${var.cluster_name}-initramfs"
  pool   = libvirt_pool.talos.name
  source = data.talos_image_factory_urls.this.urls.initramfs
  format = "raw"
}

# Create VM disk
resource "libvirt_volume" "talos_disk" {
  name   = "${var.cluster_name}-disk.qcow2"
  pool   = libvirt_pool.talos.name
  format = "qcow2"
  size   = var.vm_disk_size
}

# Create libvirt domain (VM)
resource "libvirt_domain" "talos" {
  name   = var.cluster_name
  memory = var.vm_memory
  vcpu   = var.vm_cpus

  cpu {
    mode = "custom"
    model = "Nehalem" # x86-64-v2 support for Talos v1.9.2
  }

  # Boot from kernel/initramfs (direct kernel boot)
  kernel = libvirt_volume.talos_kernel.id
  initrd = libvirt_volume.talos_initramfs.id

  # Kernel command line with KSPP parameters
  cmdline {
    _  = "console=ttyS0"
    talos_platform = "metal"
    slab_nomerge = ""
    pti = "on"
  }

  # Main disk
  disk {
    volume_id = libvirt_volume.talos_disk.id
  }

  # Network interface (user-mode networking)
  network_interface {
    network_name   = "default"
    wait_for_lease = false
  }

  # Console configuration
  console {
    type        = "pty"
    target_port = "0"
    target_type = "serial"
  }

  # Graphics (none for headless)
  graphics {
    type = "none"
  }

  # Clock sync with host
  clock {
    utc       = true
    sync_host = true
  }
}

# Apply machine configuration to the VM
resource "talos_machine_configuration_apply" "controlplane" {
  depends_on = [
    libvirt_domain.talos
  ]

  client_configuration        = talos_machine_secrets.this.client_configuration
  machine_configuration_input = data.talos_machine_configuration.controlplane.machine_configuration
  endpoint                    = "127.0.0.1"
  node                        = "127.0.0.1"

  config_patches = [
    yamlencode({
      machine = {
        install = {
          image = data.talos_image_factory_urls.this.urls.installer
        }
      }
    })
  ]
}

# Bootstrap the Kubernetes cluster
resource "talos_machine_bootstrap" "this" {
  depends_on = [
    talos_machine_configuration_apply.controlplane
  ]

  client_configuration = talos_machine_secrets.this.client_configuration
  endpoint             = "127.0.0.1"
  node                 = "127.0.0.1"
}

# Get cluster kubeconfig
data "talos_cluster_kubeconfig" "this" {
  depends_on = [
    talos_machine_bootstrap.this
  ]

  client_configuration = talos_machine_secrets.this.client_configuration
  endpoint             = "127.0.0.1"
  node                 = "127.0.0.1"
}

# Save kubeconfig to file
resource "local_file" "kubeconfig" {
  content         = data.talos_cluster_kubeconfig.this.kubeconfig_raw
  filename        = "${path.module}/kubeconfig"
  file_permission = "0600"
}

# Save talosconfig to file
resource "local_file" "talosconfig" {
  content         = data.talos_client_configuration.this.talos_config
  filename        = "${path.module}/talosconfig"
  file_permission = "0600"
}
