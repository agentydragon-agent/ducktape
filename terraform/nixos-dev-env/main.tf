# Unified Proxmox User + NixOS VM Environment
# Creates isolated user with pool and provisions NixOS VM with ducktape home-manager

locals {
  # Proxmox configuration
  proxmox_host     = "root@${var.proxmox_host}"
  proxmox_endpoint = "https://${var.proxmox_api_host}/"
  proxmox_insecure = true  # Accept self-signed certs

  # User and pool
  proxmox_user_base  = var.proxmox_username != "" ? var.proxmox_username : var.username
  pool_name_computed = var.pool_name != "" ? var.pool_name : "pool-${local.proxmox_user_base}"
  vm_name_computed   = var.vm_name != "" ? var.vm_name : "${var.username}-nixos"
  proxmox_username   = "${local.proxmox_user_base}@pve"

  # VM admin privileges for the pool
  vm_admin_privs = "VM.Allocate,VM.Audit,VM.Clone,VM.Config.CDROM,VM.Config.CPU,VM.Config.Cloudinit,VM.Config.Disk,VM.Config.HWType,VM.Config.Memory,VM.Config.Network,VM.Config.Options,VM.Console,VM.Migrate,VM.Monitor,VM.PowerMgmt,VM.Snapshot,VM.Snapshot.Rollback"

  # SSH key handling - try common key types in order of preference
  ssh_key_candidates = [
    pathexpand("~/.ssh/id_ed25519.pub"),
    pathexpand("~/.ssh/id_ecdsa.pub"),
    pathexpand("~/.ssh/id_rsa.pub")
  ]
  ssh_key_path = var.ssh_public_key != "" ? "" : (
    fileexists(local.ssh_key_candidates[0]) ? local.ssh_key_candidates[0] :
    fileexists(local.ssh_key_candidates[1]) ? local.ssh_key_candidates[1] :
    fileexists(local.ssh_key_candidates[2]) ? local.ssh_key_candidates[2] :
    ""
  )
  ssh_public_key = var.ssh_public_key != "" ? var.ssh_public_key : (
    local.ssh_key_path != "" ? trimspace(file(local.ssh_key_path)) : ""
  )

  # NixOS image URLs (latest versions)
  nixos_image_urls = {
    "unstable" = "https://channels.nixos.org/nixos-unstable/latest-nixos-minimal-x86_64-linux.iso"
    "24.11"    = "https://channels.nixos.org/nixos-24.11/latest-nixos-minimal-x86_64-linux.iso"
    "24.05"    = "https://channels.nixos.org/nixos-24.05/latest-nixos-minimal-x86_64-linux.iso"
  }
  nixos_image_url = lookup(local.nixos_image_urls, var.nixos_channel, local.nixos_image_urls["unstable"])
}

# Validation: Ensure SSH key is available
check "ssh_key_required" {
  assert {
    condition     = local.ssh_public_key != ""
    error_message = <<-EOT
      No SSH public key found!
      Tried: ${join(", ", local.ssh_key_candidates)}

      Fix by either:
      1. Creating an SSH key: ssh-keygen -t ed25519 -C "your_email@example.com"
      2. Providing key via variable: terraform apply -var="ssh_public_key=$(cat ~/.ssh/id_ed25519.pub)"
    EOT
  }
}

# AUTO-PROVISION: Create Proxmox terraform admin user
data "external" "terraform_user" {
  program = ["bash", "-c", <<-EOT
    ssh ${local.proxmox_host} '
      # Create terraform user
      pveum user add terraform@pve --comment "Terraform automation (ephemeral)" 2>/dev/null || true

      # Create role with necessary permissions
      pveum role add TerraformAdmin -privs "Datastore.Allocate,Datastore.AllocateSpace,Datastore.AllocateTemplate,Datastore.Audit,Pool.Allocate,Pool.Audit,SDN.Use,Sys.Audit,Sys.Console,Sys.Modify,VM.Allocate,VM.Audit,VM.Clone,VM.Config.CDROM,VM.Config.CPU,VM.Config.Cloudinit,VM.Config.Disk,VM.Config.HWType,VM.Config.Memory,VM.Config.Network,VM.Config.Options,VM.Console,VM.Migrate,VM.Monitor,VM.PowerMgmt,User.Modify,Permissions.Modify" 2>/dev/null || true

      # Set ACL
      pveum aclmod / -user terraform@pve -role TerraformAdmin
    '
    printf '{"success":"true"}'
  EOT
  ]
}

# Generate terraform admin token
# Note: Delete-then-create ensures idempotency since we can't retrieve existing token secrets
# Token is ephemeral per-run but user persists, proper cleanup happens in destroy provisioner
data "external" "terraform_token" {
  program = ["bash", "-c", <<-EOT
    token_json=$(ssh ${local.proxmox_host} '
      # Delete old token if exists (idempotency)
      pveum user token delete terraform@pve terraform 2>/dev/null || true
      # Create fresh token
      pveum user token add terraform@pve terraform --privsep 0 --output-format json
    ')
    token_value=$(echo "$token_json" | jq -r '.value')
    token="terraform@pve!terraform=$token_value"
    printf '{"token":"%s"}' "$token"
  EOT
  ]

  depends_on = [data.external.terraform_user]
}

# Create pool user
data "external" "pool_user" {
  program = ["bash", "-c", <<-EOT
    ssh ${local.proxmox_host} '
      # Create user
      pveum user add ${local.proxmox_username} --comment "${var.user_comment}" 2>/dev/null || true

      # Create custom role
      pveum role add VMAdmin-${local.proxmox_user_base} -privs "${local.vm_admin_privs}" 2>/dev/null || true
    '
    printf '{"success":"true"}'
  EOT
  ]

  depends_on = [data.external.terraform_user]
}

# Generate user API token
# Note: Delete-then-create ensures idempotency since we can't retrieve existing token secrets
# Token is ephemeral per-run but user persists, proper cleanup happens in destroy provisioner
data "external" "user_token" {
  program = ["bash", "-c", <<-EOT
    token_json=$(ssh ${local.proxmox_host} '
      # Delete old token if exists (idempotency)
      pveum user token delete ${local.proxmox_username} api 2>/dev/null || true
      # Create fresh token
      pveum user token add ${local.proxmox_username} api --privsep 0 --output-format json
    ')
    token_value=$(echo "$token_json" | jq -r '.value')
    token="${local.proxmox_username}!api=$token_value"
    printf '{"token":"%s"}' "$token"
  EOT
  ]

  depends_on = [data.external.pool_user]
}

# PROXMOX PROVIDER - Admin (for pool creation and permissions)
provider "proxmox" {
  alias     = "admin"
  endpoint  = local.proxmox_endpoint
  username  = "terraform@pve"
  api_token = data.external.terraform_token.result.token
  insecure  = local.proxmox_insecure
}

# PROXMOX PROVIDER - User (for VM creation in their pool)
provider "proxmox" {
  alias     = "user"
  endpoint  = local.proxmox_endpoint
  username  = local.proxmox_username
  api_token = data.external.user_token.result.token
  insecure  = local.proxmox_insecure

  ssh {
    agent    = true
    username = "root"
    node {
      name    = var.proxmox_node_name
      address = var.proxmox_host
    }
  }
}

# Default provider uses admin credentials
provider "proxmox" {
  endpoint  = local.proxmox_endpoint
  username  = "terraform@pve"
  api_token = data.external.terraform_token.result.token
  insecure  = local.proxmox_insecure
}

# RESOURCE POOL
resource "proxmox_virtual_environment_pool" "user_pool" {
  comment = "Resource pool for ${local.proxmox_user_base}"
  pool_id = local.pool_name_computed
}

# POOL PERMISSIONS
resource "proxmox_virtual_environment_acl" "pool_admin" {
  path      = "/pool/${proxmox_virtual_environment_pool.user_pool.pool_id}"
  role_id   = "PVEVMAdmin"
  user_id   = local.proxmox_username
  propagate = true
}

# STORAGE PERMISSIONS
resource "proxmox_virtual_environment_acl" "storage_access" {
  path    = "/storage/${var.storage}"
  role_id = "PVEDatastoreUser"
  user_id = local.proxmox_username
}

# STORAGE PERMISSIONS FOR SNIPPETS (local datastore)
resource "proxmox_virtual_environment_acl" "storage_access_local" {
  path    = "/storage/local"
  role_id = "PVEDatastoreAdmin"
  user_id = local.proxmox_username
}

# NETWORK/SDN PERMISSIONS
resource "proxmox_virtual_environment_acl" "sdn_access" {
  path      = "/sdn"
  role_id   = "PVESDNUser"
  user_id   = local.proxmox_username
  propagate = true
}

# NIXOS CLOUD IMAGE - Build and upload qcow2
resource "null_resource" "nixos_cloud_image" {
  triggers = {
    # Rebuild if cloud-image.nix changes
    cloud_image_config = filemd5("${path.module}/cloud-image.nix")
    proxmox_host      = var.proxmox_host
    storage           = var.storage
  }

  provisioner "local-exec" {
    command = <<-EOT
      set -e
      echo "Building NixOS qcow2 cloud image..."

      # Build the qcow2 image
      nix run github:nix-community/nixos-generators -- \
        --format qcow-efi \
        --configuration ${path.module}/cloud-image.nix \
        -o nixos-cloud-image

      # Get the actual qcow2 path from the symlink
      QCOW2_PATH=$(readlink -f nixos-cloud-image)/nixos.qcow2

      echo "Uploading qcow2 to Proxmox import directory..."
      # Upload to the import directory on Proxmox for use with import_from
      ssh root@${var.proxmox_host} "mkdir -p /var/lib/vz/import"
      scp "$QCOW2_PATH" "root@${var.proxmox_host}:/var/lib/vz/import/nixos-cloud.qcow2"

      echo "qcow2 image ready for import at local:import/nixos-cloud.qcow2"
    EOT
    working_dir = path.module
  }
}

# NIXOS ISO (kept as fallback, but not used if qcow2 is available)
# Download NixOS minimal ISO to Proxmox (using admin provider since it's shared)
resource "proxmox_virtual_environment_download_file" "nixos_image" {
  provider     = proxmox.admin
  content_type = "iso"
  datastore_id = "local"
  node_name    = var.proxmox_node_name
  url          = local.nixos_image_url
  file_name    = "nixos-${var.nixos_channel}-minimal.iso"

  # Don't re-download if already exists
  overwrite = false
}

# NIXOS CONFIGURATION FILE
locals {
  # Build environment variables map
  proxmox_env_vars = {
    PROXMOX_VE_ENDPOINT  = local.proxmox_endpoint
    PROXMOX_VE_USERNAME  = local.proxmox_username
    PROXMOX_VE_API_TOKEN = data.external.user_token.result.token
    PROXMOX_VE_INSECURE  = tostring(local.proxmox_insecure)
    PROXMOX_POOL_ID      = local.pool_name_computed
  }

  # Copy LLM API keys if provided
  llm_api_keys = merge(
    var.openai_api_key != "" ? { OPENAI_API_KEY = var.openai_api_key } : {},
    var.anthropic_api_key != "" ? { ANTHROPIC_API_KEY = var.anthropic_api_key } : {}
  )

  # Merge: Proxmox creds + LLM keys + custom env vars
  all_env_vars = merge(local.proxmox_env_vars, local.llm_api_keys, var.custom_env_vars)

  nixos_configuration = templatefile("${path.module}/configuration.nix.tpl", {
    username       = var.username
    ssh_public_key = local.ssh_public_key
    hostname       = local.vm_name_computed
    enable_gui     = var.enable_gui
    nixos_channel  = var.nixos_channel
    env_vars       = local.all_env_vars
  })

  home_manager_flake = templatefile("${path.module}/flake.nix.tpl", {
    username      = var.username
    hostname      = local.vm_name_computed
    ducktape_repo = var.ducktape_repo
    nixos_channel = var.nixos_channel
  })
}

resource "proxmox_virtual_environment_file" "nixos_config" {
  provider     = proxmox.user
  content_type = "snippets"
  datastore_id = "local"
  node_name    = var.proxmox_node_name

  source_raw {
    data      = local.nixos_configuration
    file_name = "${local.vm_name_computed}-configuration.nix"
  }

  depends_on = [
    proxmox_virtual_environment_acl.storage_access,
    proxmox_virtual_environment_acl.storage_access_local,
    null_resource.cleanup  # Ensures cleanup is destroyed AFTER files
  ]
}

resource "proxmox_virtual_environment_file" "home_manager_flake" {
  provider     = proxmox.user
  content_type = "snippets"
  datastore_id = "local"
  node_name    = var.proxmox_node_name

  source_raw {
    data      = local.home_manager_flake
    file_name = "${local.vm_name_computed}-flake.nix"
  }

  depends_on = [
    proxmox_virtual_environment_acl.storage_access,
    proxmox_virtual_environment_acl.storage_access_local,
    null_resource.cleanup  # Ensures cleanup is destroyed AFTER files
  ]
}

# CLOUD-INIT CONFIGURATION
locals {
  cloud_init_user_data = templatefile("${path.module}/cloud-init.yaml.tpl", {
    username              = var.username
    ssh_public_key        = local.ssh_public_key
    hostname              = local.vm_name_computed
    nixos_config_snippet  = "${local.vm_name_computed}-configuration.nix"
    flake_snippet         = "${local.vm_name_computed}-flake.nix"
    proxmox_api_host      = var.proxmox_api_host
  })
}

resource "proxmox_virtual_environment_file" "cloud_init_config" {
  provider     = proxmox.user
  content_type = "snippets"
  datastore_id = "local"
  node_name    = var.proxmox_node_name

  source_raw {
    data      = local.cloud_init_user_data
    file_name = "${local.vm_name_computed}-cloud-init.yaml"
  }

  depends_on = [
    proxmox_virtual_environment_file.nixos_config,
    proxmox_virtual_environment_file.home_manager_flake,
    proxmox_virtual_environment_acl.storage_access,
    proxmox_virtual_environment_acl.storage_access_local,
    null_resource.cleanup  # Ensures cleanup is destroyed AFTER files
  ]
}

# NIXOS VM (created with user credentials)
resource "proxmox_virtual_environment_vm" "nixos_vm" {
  provider    = proxmox.user
  name        = local.vm_name_computed
  description = "NixOS ${var.nixos_channel} with ducktape home-manager for ${var.username}"
  node_name   = var.proxmox_node_name
  vm_id       = var.vm_id != 0 ? var.vm_id : null
  pool_id     = proxmox_virtual_environment_pool.user_pool.pool_id
  bios        = "ovmf"  # UEFI boot required for qcow-efi images

  # CPU
  cpu {
    cores = var.vcpus
    type  = "host"
  }

  # Memory
  memory {
    dedicated = var.memory_mb
  }

  # EFI disk for UEFI boot
  efi_disk {
    datastore_id = var.storage
    file_format  = "raw"
    type         = "4m"
  }

  # Boot disk - import from pre-built qcow2
  disk {
    datastore_id = var.storage
    import_from  = "local:import/nixos-cloud.qcow2"  # Native provider support for importing qcow2
    interface    = "scsi0"
    iothread     = true
    discard      = "on"
    size         = var.disk_size_gb
  }

  # Network
  network_device {
    bridge = var.network_bridge
    model  = "virtio"
  }

  # Cloud-init drive (using SATA for better compatibility)
  initialization {
    datastore_id = var.storage
    interface    = "sata0"  # Use SATA instead of IDE for better NixOS support

    ip_config {
      ipv4 {
        address = "dhcp"
      }
    }

    user_account {
      username = var.username
      keys     = local.ssh_public_key != "" ? [local.ssh_public_key] : []
      password = ""  # Passwordless
    }

    user_data_file_id = proxmox_virtual_environment_file.cloud_init_config.id
  }

  # VM Options
  started = var.auto_start

  agent {
    enabled = true
  }

  depends_on = [
    proxmox_virtual_environment_acl.pool_admin,
    proxmox_virtual_environment_acl.storage_access,
    null_resource.nixos_cloud_image,
    null_resource.cleanup  # Ensures cleanup is destroyed AFTER VM
  ]
}

# CLEANUP
resource "null_resource" "cleanup" {
  triggers = {
    username     = local.proxmox_username
    proxmox_host = local.proxmox_host
    role_name    = "VMAdmin-${local.proxmox_user_base}"
  }

  provisioner "local-exec" {
    when    = destroy
    command = <<-EOT
      echo "Cleaning up Proxmox users and roles"
      ssh ${self.triggers.proxmox_host} '
        # Delete user tokens
        pveum user token delete ${self.triggers.username} api 2>/dev/null || true
        pveum user token delete terraform@pve terraform 2>/dev/null || true

        # Delete users
        pveum user delete ${self.triggers.username} 2>/dev/null || true
        pveum user delete terraform@pve 2>/dev/null || true

        # Delete custom roles if unused
        if [ "$(pveum aclmod / -role ${self.triggers.role_name} 2>/dev/null | wc -l)" -eq 0 ]; then
          pveum role delete ${self.triggers.role_name} 2>/dev/null || true
        fi
        pveum role delete TerraformAdmin 2>/dev/null || true

        echo "Cleanup completed"
      ' || true
    EOT
  }

  # No depends_on - this ensures cleanup is destroyed LAST, after all resources
  # that use the user credentials (VM, files, ACLs) are already destroyed
}
