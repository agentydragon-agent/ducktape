# Cilium CNI deployment via Terraform Helm provider
# Infrastructure layer management - prevents GitOps circular dependencies

# Add Cilium helm repository
resource "null_resource" "add_cilium_repo" {
  provisioner "local-exec" {
    command = "helm repo add cilium https://helm.cilium.io/ && helm repo update"
  }
  depends_on = [null_resource.wait_for_k8s_api, local_file.kubeconfig]
}

resource "helm_release" "cilium_bootstrap" {
  name             = "cilium"
  repository       = "cilium"
  chart            = "cilium"
  version          = "1.16.5"
  namespace        = "kube-system"
  create_namespace = true

  values = [
    file("${path.module}/cilium-values.yaml")
  ]

  # Native Helm provider reliability and health checking
  wait            = true
  wait_for_jobs   = true
  atomic          = true
  cleanup_on_fail = true
  timeout         = 600
  max_history     = 3
  force_update    = false
  reset_values    = false

  # Prevent accidental networking breakage
  lifecycle {
    ignore_changes = [
      version,
      values
    ]
  }

  depends_on = [
    null_resource.wait_for_k8s_api,
    null_resource.add_cilium_repo,
    local_file.kubeconfig
  ]
}

# Wait for Kubernetes API to be accessible before installing Cilium
resource "null_resource" "wait_for_k8s_api" {
  depends_on = [
    talos_machine_bootstrap.cluster,
    local_file.kubeconfig
  ]

  provisioner "local-exec" {
    environment = {
      KUBECONFIG = local_file.kubeconfig.filename
      K8S_SERVER = "https://${hcloud_server.vps[local.bootstrap_node].ipv4_address}:6443"
    }
    command = "${path.module}/wait-for-k8s-api.sh"
  }
}
