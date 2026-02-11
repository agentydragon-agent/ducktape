# Talos Machine Secrets - Shared across all cluster nodes (VPS + Proxmox)
# These secrets are persistent and survive cluster destroy/recreate cycles
# All nodes in the hybrid cluster must use these same secrets

resource "talos_machine_secrets" "cluster" {
  talos_version = var.talos_version
}
