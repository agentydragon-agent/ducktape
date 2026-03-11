# NixOS LXC Image Module
# Builds a per-host LXC tarball via `nix build` and uploads it to Proxmox.
# Uses system.build.tarball from the proxmox-lxc.nix nixpkgs module.

terraform {
  required_version = ">= 1.0"

  required_providers {
    external = {
      source  = "hashicorp/external"
      version = ">= 2.3.0"
    }
    null = {
      source  = "hashicorp/null"
      version = ">= 3.2.0"
    }
  }
}

# Fail fast if SSH to the Proxmox host doesn't work.
data "external" "ssh_check" {
  program = ["bash", "-c", <<-EOT
    if ssh -o BatchMode=yes -o ConnectTimeout=5 root@${var.proxmox_host} true 2>/dev/null; then
      printf '{"status":"ok"}'
    else
      echo "ERROR: SSH to root@${var.proxmox_host} failed." >&2
      echo "Ensure your SSH key is loaded (ssh-add) and the host key is in known_hosts." >&2
      exit 1
    fi
  EOT
  ]
}

# Build the NixOS LXC tarball.
resource "null_resource" "build" {
  triggers = {
    nix_dir_hash = var.nix_dir_hash
    flake_target = var.flake_target
  }

  provisioner "local-exec" {
    command = <<-EOT
      set -e
      echo "Building ${var.flake_target} NixOS LXC tarball..."
      cd "${var.repo_root}"
      nix build ./nix#${var.flake_target}-lxc -o /tmp/${var.flake_target}-lxc
    EOT
  }

  depends_on = [data.external.ssh_check]
}

# Upload the tarball to Proxmox template cache.
resource "null_resource" "upload" {
  triggers = {
    nix_dir_hash = var.nix_dir_hash
    proxmox_host = var.proxmox_host
    flake_target = var.flake_target
  }

  provisioner "local-exec" {
    command = <<-EOT
      set -e
      echo "Uploading ${var.flake_target} LXC template to Proxmox..."
      ssh root@${var.proxmox_host} "mkdir -p /var/lib/vz/template/cache"
      scp /tmp/${var.flake_target}-lxc/tarball/*.tar.xz \
        "root@${var.proxmox_host}:/var/lib/vz/template/cache/${var.flake_target}.tar.xz"
      echo "${var.flake_target} template ready at local:vztmpl/${var.flake_target}.tar.xz"
    EOT
  }

  depends_on = [null_resource.build]
}
