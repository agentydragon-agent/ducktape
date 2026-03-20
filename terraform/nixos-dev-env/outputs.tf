# Outputs for NixOS Dev Environment

# Wyrm2 outputs
output "wyrm2" {
  description = "Wyrm2 VM info"
  value = {
    name           = module.wyrm2.vm_name
    id             = module.wyrm2.vm_id
    ipv4_addresses = module.wyrm2.ipv4_addresses
  }
}

output "instructions" {
  description = "Setup instructions and next steps"
  value       = <<-EOT

    VM: wyrm2 (ID: ${module.wyrm2.vm_id})

    Workflows:

    Initial provisioning (build bootstrap image + deploy full config):
      tofu apply -var="rebuild_image=true" -var="nixos_rebuild=true"

    VM hardware changes only (CPU, RAM, disks):
      tofu apply

    Deploy NixOS config changes:
      tofu apply -var="nixos_rebuild=true"
      # or manually:
      ssh wyrm2 'sudo nixos-rebuild switch --flake github:agentydragon/ducktape?ref=devel#wyrm2'

    After deploying, approve the kubelet CSR to join the cluster:
      kubectl get csr
      kubectl certificate approve <csr-name>
  EOT
}
