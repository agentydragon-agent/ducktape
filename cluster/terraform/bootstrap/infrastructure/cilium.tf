# Cilium CNI deployment via helm CLI (null_resource)
#
# Uses helm CLI instead of helm_release resource because Helm provider v3
# has unfixed plan consistency bugs with OpenTofu (computed fields like
# status/id/metadata return null during plan but non-null during apply).
# https://github.com/hashicorp/terraform-provider-helm/pull/1739
#
# Infrastructure layer management - prevents GitOps circular dependencies.

# Gateway API CRDs must be installed before Cilium so that Cilium can register
# as a GatewayClass provider. CRDs are not bundled in the Cilium Helm chart.
# See: https://github.com/cilium/cilium/issues/39843
#
# TODO: Consider replacing null_resource with alekc/kubectl provider
# (kubectl_manifest + wait_for condition). Currently using raw kubectl because
# kubernetes_manifest requires API server during plan (breaks bootstrap-from-nothing)
# and yamldecode can't reliably split multi-document YAML.
resource "null_resource" "gateway_api_crds" {
  depends_on = [
    null_resource.wait_for_k8s_api,
    local_file.kubeconfig,
  ]

  provisioner "local-exec" {
    environment = {
      KUBECONFIG = local_file.kubeconfig.filename
    }
    # Experimental channel includes TLSRoute CRD required by Cilium 1.16.x.
    # Standard channel only has GA CRDs and Cilium refuses to start the
    # gateway controller without TLSRoute.
    command = <<-EOT
      set -e
      kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.3.0/experimental-install.yaml
      kubectl wait --for=condition=Established \
        crd/gatewayclasses.gateway.networking.k8s.io \
        crd/gateways.gateway.networking.k8s.io \
        crd/httproutes.gateway.networking.k8s.io \
        crd/tlsroutes.gateway.networking.k8s.io \
        crd/referencegrants.gateway.networking.k8s.io \
        --timeout=60s
    EOT
  }
}

resource "null_resource" "cilium_bootstrap" {
  depends_on = [
    null_resource.gateway_api_crds,
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
