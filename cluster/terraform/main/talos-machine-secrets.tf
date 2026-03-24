# Talos Machine Secrets - Generated fresh on each cluster lifecycle
# This ensures a new cluster.id, preventing stale discovery from
# previous cluster incarnations.

resource "talos_machine_secrets" "cluster" {
  talos_version = var.talos_version
}
