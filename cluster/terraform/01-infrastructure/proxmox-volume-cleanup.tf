# Proxmox Volume Cleanup for Retain Policy
# Cleans up Proxmox storage volumes during terraform destroy while maintaining
# Retain policy for safety (accidental PVC deletion doesn't lose data)

resource "null_resource" "cleanup_proxmox_volumes" {
  # This resource depends on Cilium AND infrastructure to ensure:
  # 1. PVCs exist when cleanup queries them (Cilium = cluster working)
  # 2. Cluster API stays alive during cleanup (infrastructure = VMs running)
  # During destroy: cleanup runs FIRST, then Cilium, then infrastructure
  depends_on = [
    helm_release.cilium_bootstrap,
    module.infrastructure
  ]

  triggers = {
    # Track cluster instance to ensure cleanup runs on each destroy
    cluster_name = var.cluster_name
    proxmox_host = "root@atlas"
  }

  provisioner "local-exec" {
    when    = destroy
    command = "${path.module}/scripts/cleanup-proxmox-volumes.py ${path.module}/kubeconfig ${self.triggers.proxmox_host}"
  }
}
