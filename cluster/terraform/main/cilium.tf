# Wait resources for bootstrap sequencing.
#
# Cilium and Gateway API CRDs are now deployed as Talos inline/extra
# manifests (see cilium-inline.tf + infrastructure.tf). These wait
# resources remain for bootstrap.py sequencing — they ensure the k8s API
# is reachable and nodes are Ready before proceeding to Flux deployment.

# Wait for Kubernetes API to be accessible
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

# Wait for all nodes to be Ready (Cilium is an inline manifest, so it
# should be running by the time the API is reachable)
resource "null_resource" "wait_for_nodes_ready" {
  depends_on = [null_resource.wait_for_k8s_api]

  provisioner "local-exec" {
    environment = {
      KUBECONFIG = local_file.kubeconfig.filename
    }
    command = "kubectl wait --for=condition=Ready node --all --timeout=600s"
  }
}
