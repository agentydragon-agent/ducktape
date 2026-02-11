# Sealed Secrets Keypair from Persistent Auth Layer
# References keypair managed in 00-persistent-auth to avoid duplication

# Import keypair from persistent auth layer (now terraform-generated, not base64 encoded)
locals {
  sealed_secrets_cert_pem = data.terraform_remote_state.persistent_auth.outputs.sealed_secrets_keypair.certificate
  sealed_secrets_key_pem  = data.terraform_remote_state.persistent_auth.outputs.sealed_secrets_keypair.private_key
}

# Apply our stable keypair to the cluster so sealed-secrets controller uses it
resource "kubernetes_secret" "sealed_secrets_key" {
  depends_on = [local_file.kubeconfig, null_resource.wait_for_k8s_api, helm_release.cilium_bootstrap]
  metadata {
    name      = "sealed-secrets-key"
    namespace = "kube-system"
    labels = {
      "sealedsecrets.bitnami.com/sealed-secrets-key" = "active"
    }
  }

  data = {
    "tls.crt" = local.sealed_secrets_cert_pem
    "tls.key" = local.sealed_secrets_key_pem
  }

  type = "kubernetes.io/tls"

}

# Random suffix to ensure unique key names (sealed-secrets keeps all keys)
resource "random_string" "key_suffix" {
  length  = 5
  special = false
  upper   = false
}
