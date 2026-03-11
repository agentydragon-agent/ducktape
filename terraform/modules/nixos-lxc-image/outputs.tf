output "template_file_id" {
  description = "Proxmox template file ID (e.g., 'local:vztmpl/lxc-k8s-test.tar.xz')"
  value       = "local:vztmpl/${var.flake_target}.tar.xz"
  depends_on  = [null_resource.upload]
}
