# NixOS K8s Worker Outputs

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

    After boot completes (~2-3 minutes):
      1. SSH in: ssh ${var.username}@<vm-ip>
      2. Start KubeSpan: sudo systemctl start kubespand
      3. Start kubelet: sudo systemctl start kubelet
      4. Approve CSR: kubectl certificate approve <csr-name>

    Get IP: tofu output k8s_worker_test
  EOT
}
