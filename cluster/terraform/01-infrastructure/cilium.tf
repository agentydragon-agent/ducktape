# Cilium CNI deployment via helm CLI (null_resource)
#
# Uses helm CLI instead of helm_release resource because Helm provider v3
# has unfixed plan consistency bugs with OpenTofu (computed fields like
# status/id/metadata return null during plan but non-null during apply).
# https://github.com/hashicorp/terraform-provider-helm/pull/1739
#
# Infrastructure layer management - prevents GitOps circular dependencies.

resource "null_resource" "cilium_bootstrap" {
  depends_on = [
    null_resource.wait_for_k8s_api,
    local_file.kubeconfig,
  ]

  provisioner "local-exec" {
    environment = {
      KUBECONFIG = local_file.kubeconfig.filename
    }
    command = <<-EOT
      set -e
      helm repo add cilium https://helm.cilium.io/ && helm repo update cilium
      helm upgrade --install cilium cilium/cilium \
        --version 1.16.5 \
        --namespace kube-system \
        --create-namespace \
        -f ${path.module}/cilium-values.yaml \
        --wait \
        --wait-for-jobs \
        --atomic \
        --timeout 600s
    EOT
  }
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
    }
    # Retry loop handles connection refused during API startup (10 min timeout)
    command = "timeout 600 bash -c 'until kubectl get nodes --request-timeout=30s 2>/dev/null; do sleep 10; done'"
  }
}

# Wait for all nodes to be Ready using kubectl wait (has native retry/polling)
resource "null_resource" "wait_for_nodes_ready" {
  depends_on = [null_resource.cilium_bootstrap]

  provisioner "local-exec" {
    environment = {
      KUBECONFIG = local_file.kubeconfig.filename
    }
    command = "kubectl wait --for=condition=Ready node --all --timeout=600s"
  }
}
