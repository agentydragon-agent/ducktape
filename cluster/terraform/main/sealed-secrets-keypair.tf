# Sealed Secrets Keypair — deploy to cluster
# References keypair from persistent-auth.tf (same root).

locals {
  sealed_secrets_cert_pem = tls_self_signed_cert.sealed_secrets.cert_pem
  sealed_secrets_key_pem  = tls_private_key.sealed_secrets.private_key_pem
}

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
    "tls.crt" = local.sealed_secrets_cert_pem
    "tls.key" = local.sealed_secrets_key_pem
  }

  type = "kubernetes.io/tls"

}

# Expose the sealed-secrets RSA keypair as a SOPS age identity for Flux.
# age supports ssh-rsa recipients, so we reuse the same key material rather
# than introducing a separate age key. The OpenSSH-format private key is what
# age's identity parser expects.
# TODO: consider migrating to a dedicated age key and fully replacing
#       SealedSecrets with SOPS at some point.
resource "kubernetes_secret" "flux_sops_age" {
  depends_on = [local_file.kubeconfig, null_resource.wait_for_k8s_api, null_resource.cilium_bootstrap]
  metadata {
    name      = "sops-age"
    namespace = "flux-system"
    annotations = {
      description = "SOPS age identity derived from sealed-secrets RSA keypair (ssh-rsa recipient)"
    }
  }
  data = {
    "age.agekey" = tls_private_key.sealed_secrets.private_key_openssh
  }
}

# Random suffix to ensure unique key names (sealed-secrets keeps all keys)
resource "random_string" "key_suffix" {
  length  = 5
  special = false
  upper   = false
}
