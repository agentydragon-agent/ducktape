# Talos Machine Secrets - Generated fresh on each cluster lifecycle
# This ensures a new cluster.id for KubeSpan discovery, preventing
# phantom peers from previous cluster incarnations.

resource "talos_machine_secrets" "cluster" {
  talos_version = var.talos_version
}
