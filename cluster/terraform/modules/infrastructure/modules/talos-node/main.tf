terraform {
  required_providers {
    proxmox = {
      source = "bpg/proxmox"
    }
    talos = {
      source = "siderolabs/talos"
    }
    external = {
      source = "hashicorp/external"
    }
  }
}

locals {
  # Common VM configuration
  vm_config = {
    datastore_id = "local-zfs"
    file_format  = "raw"
    iothread     = true
    ssd          = true
    discard      = "on"
  }

  # Common VM settings
  vm_defaults = {
    bios          = "ovmf"
    machine       = "q35"
    scsi_hardware = "virtio-scsi-single"
    cpu_type      = "host"
    cpu_cores     = 4
    memory_mb     = 12 * 1024 # 12GB (increased from 8GB)
    vga_type      = "qxl"
    tags          = sort(["talos", var.node_type, "kubernetes", "terraform"])
  }

  # Create schematic YAML with static IP configuration in META key 0xa (10)
  schematic_yaml = yamlencode({
    customization = {
      extraKernelArgs = ["net.ifnames=0"]
      systemExtensions = {
        officialExtensions = [
          "siderolabs/qemu-guest-agent",
          "siderolabs/tailscale"
        ]
      }
      meta = [
        {
          key = 10 # META key 0xa for network configuration
          value = yamlencode({
            addresses = [
              {
                address  = "${var.ip_address}/16"
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
                gateway     = var.shared_config.gateway
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
                hostname = var.node_name
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

  # Common machine configuration (includes Tailscale extension)
  common_machine_config = {
    machine = {
      features = {
        kubePrism = {
          enabled = true
          port    = 7445
        }
        hostDNS = {
          enabled              = true
          forwardKubeDNSToHost = true
        }
      }
      nodeLabels = {
        "topology.kubernetes.io/region" = "cluster"
        "topology.kubernetes.io/zone"   = "atlas"
      }
      kubelet = {
        extraArgs = {
          provider-id = "proxmox://cluster/${var.vm_id}"
          # Allow TCP MTU probing sysctl for PMTUD blackhole mitigation
          "allowed-unsafe-sysctls" = "net.ipv4.tcp_mtu_probing"
        }
        # Explicitly set node IP to prevent conflicts with Tailscale IPs
        nodeIP = {
          validSubnets = ["10.2.0.0/16"] # Cluster network range (VLAN 4)
        }
      }
      # Harbor pull-through cache with fallback to upstream registries
      # Fallback ensures bootstrap works even when Harbor doesn't exist yet
      registries = {
        mirrors = {
          "docker.io" = {
            endpoints = [
              "https://registry.test-cluster.agentydragon.com/docker-hub-proxy",
              "https://registry-1.docker.io"
            ]
          }
          "ghcr.io" = {
            endpoints = [
              "https://registry.test-cluster.agentydragon.com/ghcr-proxy",
              "https://ghcr.io"
            ]
          }
          "quay.io" = {
            endpoints = [
              "https://registry.test-cluster.agentydragon.com/quay-proxy",
              "https://quay.io"
            ]
          }
          "registry.k8s.io" = {
            endpoints = [
              "https://registry.test-cluster.agentydragon.com/registry-k8s-io-proxy",
              "https://registry.k8s.io"
            ]
          }
        }
      }
    }
    cluster = {
      discovery = {
        enabled = false
        registries = {
          kubernetes = { disabled = true }
          service    = { disabled = true }
        }
      }
      network = { cni = { name = "none" } }
      proxy   = { disabled = true }
    }
  }
}

# Generate unique pre-auth key for this node via SSH
data "external" "preauth_key" {
  program = ["bash", "-c", <<-EOT
    key_json=$(ssh ${var.shared_config.global_config.headscale_server} "headscale preauthkeys create --user ${var.shared_config.global_config.headscale_user} --expiration 1h --output json")
    echo "$key_json" | jq '{key: .key, id: .id}'
  EOT
  ]
}

# Create schematic in Image Factory using Talos provider
resource "talos_image_factory_schematic" "schematic" {
  schematic = local.schematic_yaml
}

# Generate URLs for different image formats
data "talos_image_factory_urls" "urls" {
  schematic_id  = talos_image_factory_schematic.schematic.id
  talos_version = var.talos_config_base.talos_version
  platform      = "metal"
  architecture  = "amd64"
}

# Download the disk image with pre-installed Talos
resource "proxmox_virtual_environment_download_file" "disk_image" {
  content_type = "import" # Correct content type for disk images
  datastore_id = "local"  # Use local datastore (now configured with import support)
  node_name    = var.shared_config.proxmox_node_name
  url          = replace(data.talos_image_factory_urls.urls.urls.disk_image, "metal-amd64.raw.zst", "metal-amd64.qcow2")
  file_name    = "talos-${talos_image_factory_schematic.schematic.id}-amd64.qcow2"
  overwrite    = true
}

# Create the VM
resource "proxmox_virtual_environment_vm" "vm" {
  name            = "${var.shared_config.prefix}-${var.node_name}"
  vm_id           = var.vm_id
  node_name       = var.shared_config.proxmox_node_name
  tags            = local.vm_defaults.tags
  stop_on_destroy = true
  bios            = local.vm_defaults.bios
  machine         = local.vm_defaults.machine
  scsi_hardware   = local.vm_defaults.scsi_hardware

  operating_system {
    type = "l26"
  }

  cpu {
    type  = local.vm_defaults.cpu_type
    cores = local.vm_defaults.cpu_cores
  }

  memory {
    # Proxmox memory mapping:
    # - dedicated → Proxmox 'memory' (maximum RAM the VM can use)
    # - floating  → Proxmox 'balloon' (target/minimum guaranteed RAM)
    dedicated = local.vm_defaults.memory_mb # 12GB maximum (VM can grow to this)
    floating  = var.memory_dedicated_mb     # Minimum guaranteed (3GB controllers, 6GB workers)
  }

  vga {
    type = local.vm_defaults.vga_type
  }

  network_device {
    bridge = "vmbr4"
  }

  efi_disk {
    datastore_id = local.vm_config.datastore_id
    file_format  = local.vm_config.file_format
    type         = "4m"
  }

  # Use pre-installed Talos disk image as main boot disk
  disk {
    datastore_id = local.vm_config.datastore_id
    interface    = "scsi0"
    iothread     = local.vm_config.iothread
    ssd          = local.vm_config.ssd
    discard      = local.vm_config.discard
    size         = 40
    file_format  = local.vm_config.file_format
    import_from  = proxmox_virtual_environment_download_file.disk_image.id
  }

  # Proxmox CSI uses host storage directly - no additional disks needed

  agent {
    enabled = true
    trim    = true
  }
  # NOTE: Static IP and Talos OS are pre-baked into the disk image
}

# Print restart reminder when disk image changes
resource "terraform_data" "restart_reminder" {
  triggers_replace = [
    proxmox_virtual_environment_download_file.disk_image.id
  ]

  provisioner "local-exec" {
    command = <<-EOT
      echo ""
      echo "⚠️  RESTART REQUIRED for VM ${var.vm_id} (${var.node_name}) ⚠️"
      echo "Disk image changed: ${proxmox_virtual_environment_download_file.disk_image.file_name}"
      echo "Run: ssh ${var.shared_config.global_config.proxmox_server} 'qm reboot ${var.vm_id}'"
      echo ""
    EOT
  }

  depends_on = [proxmox_virtual_environment_vm.vm]
}

# Generate machine configuration based on node type
# This is as close as Terraform gets to "take this object + add these fields"
locals {
  # Merge base talos config + node-specific machine_type
  machine_config = merge(
    var.talos_config_base, # All the shared talos fields
    {
      machine_type    = var.node_type                                         # Node-specific override
      machine_secrets = var.talos_config_base.machine_secrets.machine_secrets # Extract the actual secrets
    }
  )
}

data "talos_machine_configuration" "config" {
  # Generate machine configuration with all config patches
  cluster_name       = local.machine_config.cluster_name
  cluster_endpoint   = local.machine_config.cluster_endpoint
  machine_secrets    = local.machine_config.machine_secrets
  machine_type       = local.machine_config.machine_type
  talos_version      = local.machine_config.talos_version
  kubernetes_version = local.machine_config.kubernetes_version
  examples           = local.machine_config.examples
  docs               = local.machine_config.docs

  config_patches = concat([
    yamlencode(local.common_machine_config) # Common machine configuration
    ], var.node_type == "controlplane" ? [
    # Control plane gets VIP configuration
    yamlencode({
      machine = {
        network = {
          interfaces = [{
            interface = "eth0"
            vip       = { ip = var.shared_config.cluster_vip }
          }]
        }
      }
    }),
    # Control plane gets apiServer configuration to listen on IPv4
    yamlencode({
      cluster = {
        apiServer = {
          certSANs = [
            var.shared_config.cluster_vip,
            "127.0.0.1"
          ]
          extraArgs = {
            "bind-address" = "0.0.0.0" # Force IPv4 binding
          }
        }
      }
    }),
    # Control plane gets Tailscale configuration with routing
    yamlencode({
      apiVersion = "v1alpha1"
      kind       = "ExtensionServiceConfig"
      name       = "tailscale"
      environment = [
        "TS_AUTHKEY=${data.external.preauth_key.result.key}",
        "TS_EXTRA_ARGS=${var.shared_config.tailscale_base_args} ${var.shared_config.tailscale_route_args}"
      ]
    })
    ] : [
    # Workers get explicit interface config to disable DHCP
    # (Controllers get this implicitly via VIP config, workers need it explicitly)
    # Without this, workers get a second IP from DHCP which confuses Talos NodeIPController
    yamlencode({
      machine = {
        network = {
          interfaces = [{
            interface = "eth0"
            dhcp      = false
          }]
        }
      }
    }),
    # Workers get basic Tailscale configuration
    yamlencode({
      apiVersion = "v1alpha1"
      kind       = "ExtensionServiceConfig"
      name       = "tailscale"
      environment = [
        "TS_AUTHKEY=${data.external.preauth_key.result.key}",
        "TS_EXTRA_ARGS=${var.shared_config.tailscale_base_args}"
      ]
    })
  ])
}

# Apply machine configuration BEFORE cluster bootstrap to avoid race condition
resource "talos_machine_configuration_apply" "apply" {
  client_configuration        = var.talos_config_base.machine_secrets.client_configuration
  machine_configuration_input = data.talos_machine_configuration.config.machine_configuration
  node                        = var.ip_address
  config_patches              = []

  # Apply configuration immediately after VM is ready but before bootstrap
  depends_on = [proxmox_virtual_environment_vm.vm]
}

# NOTE: Machine configuration is applied BEFORE cluster bootstrap to avoid race condition
# This ensures kubelet isn't running when config is applied, preventing mount controller issues
# TODO: May need to handle Tailscale key rotation when pre-auth keys expire (currently 1h)

# TOMBSTONE: Runtime configuration patching removed due to critical Talos bug
#
# SUMMARY OF INVESTIGATION AND REASONING:
#
# Timeline of failure:
# - 04:37:21Z: Workers healthy, kubelet running successfully
# - 04:43:22Z: Terraform applied config change (Flux embedded manifests)
# - 05:09:20Z: First mount controller failure on workers
# - Workers never recovered, stuck in crash-loop
#
# Root cause investigation:
# 1. Terraform sends runtime config patches to ALL nodes (control plane + workers)
# 2. Runtime patches trigger kubelet service restart via talos_machine_configuration_apply
# 3. During restart, mount requests get torn down
# 4. Mount controller tries to add finalizer to deleted mount request
# 5. Race condition: resource no longer exists when finalizer addition attempted
# 6. Mount controller fails, kubelet startup crashes
#
# Why control plane worked but workers failed:
# - Control plane kubelets have different mount request lifecycle
# - Different timing in mount request creation/deletion during restart
# - Control plane mounts (etcd, etc.) vs worker mounts (/var/log/audit/kube, etc.)
#
# Talos bug location:
# https://github.com/siderolabs/talos/blob/main/internal/app/machined/pkg/controllers/block/mount.go#L196-L198
# The mount controller assumes mount requests exist when adding finalizers,
# but they may be deleted during service restart lifecycle.
#
# Solution reasoning:
# - Machine generation patches are SAFE (baked into disk image, no runtime changes)
# - Runtime patches are DANGEROUS (trigger service restarts and race condition)
# - Eliminate runtime patching entirely = eliminate race condition
# - All config (VIP, Tailscale) moved to machine generation time
#
# TODO: Report this critical bug upstream to Talos project
#
# Previous runtime patching resource (talos_machine_configuration_apply) removed

# Node registration cleanup on destroy
resource "terraform_data" "node_registration" {
  # Store both pre-auth key ID and server for cleanup
  input = {
    key_id = data.external.preauth_key.result.id
    server = var.shared_config.global_config.headscale_server
  }

  # Cleanup pre-auth key when destroying (nodes auto-expire but keys don't)
  provisioner "local-exec" {
    when    = destroy
    command = "ssh ${self.input.server} 'headscale preauthkeys delete ${self.input.key_id}' || echo 'Pre-auth key ${self.input.key_id} already expired/removed'"
  }

  depends_on = [proxmox_virtual_environment_vm.vm]
}