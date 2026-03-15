# K8s Worker (Proxmox) Outputs

output "k8s_worker_test" {
  description = "k8s-worker-test VM info"
  value = {
    name           = module.k8s_worker_test.vm_name
    id             = module.k8s_worker_test.vm_id
    ipv4_addresses = module.k8s_worker_test.ipv4_addresses
  }
}

output "instructions" {
  description = "Post-deployment instructions"
  value       = <<-EOT

    k8s-worker-test VM deployed (ID: ${module.k8s_worker_test.vm_id})

    kubespand and kubelet auto-start on boot.
    After boot completes (~2-3 minutes), approve the CSR:
      kubectl get csr
      kubectl certificate approve <csr-name>

    Get IP: tofu output k8s_worker_test
  EOT
}
