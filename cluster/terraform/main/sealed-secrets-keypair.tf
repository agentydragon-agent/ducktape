# Sealed Secrets Keypair — deploy to cluster
# Keypair read from SOPS in persistent-auth.tf.

# Apply our stable keypair to the cluster so sealed-secrets controller uses it
resource "kubernetes_secret" "sealed_secrets_key" {
  depends_on = [local_file.kubeconfig, null_resource.wait_for_k8s_api, null_resource.cilium_bootstrap]
  metadata {
    name      = "sealed-secrets-key"
    namespace = "kube-system"
    labels = {
      "sealedsecrets.bitnami.com/sealed-secrets-key" = "active"
    }
  }

  data = {
    "tls.crt" = local.sealed_secrets_crt
    "tls.key" = local.sealed_secrets_key
  }

  type = "kubernetes.io/tls"
}


# Random suffix to ensure unique key names (sealed-secrets keeps all keys)
resource "random_string" "key_suffix" {
  length  = 5
  special = false
  upper   = false
}
