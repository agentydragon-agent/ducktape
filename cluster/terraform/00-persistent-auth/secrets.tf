# ============================================
# TERRAFORM-MANAGED SECRETS
# All persistent secrets stored in terraform state
# No libsecret dependency
# ============================================

# ============================================
# SEALED SECRETS KEYPAIR
# RSA 4096-bit key with self-signed certificate
# ============================================
resource "tls_private_key" "sealed_secrets" {
  algorithm = "RSA"
  rsa_bits  = 4096
}

resource "tls_self_signed_cert" "sealed_secrets" {
  private_key_pem = tls_private_key.sealed_secrets.private_key_pem

  subject {
    common_name  = "sealed-secret"
    organization = "sealed-secrets"
  }

  validity_period_hours = 87600 # 10 years
  is_ca_certificate     = true

  allowed_uses = [
    "key_encipherment",
    "digital_signature",
    "cert_signing",
  ]
}

# ============================================
# FLUX DEPLOY KEY
# ED25519 key for GitHub repository access
# ============================================
resource "tls_private_key" "flux_deploy" {
  algorithm = "ED25519"
}

# ============================================
# NIX CACHE SIGNING KEY
# Uses nix-store format, generated once and stored in local file
# The file is NOT in git but backed up with terraform state
# ============================================
resource "null_resource" "nix_cache_key_generate" {
  # Only generate if file doesn't exist
  provisioner "local-exec" {
    command = <<-EOT
      if [ ! -f ${path.module}/nix-cache-key.json ]; then
        echo "🔑 Generating new Nix cache signing key..."
        nix-store --generate-binary-cache-key cache.test-cluster.agentydragon.com-1 /tmp/nix-private.key /tmp/nix-public.key
        jq -n --arg priv "$(cat /tmp/nix-private.key)" --arg pub "$(cat /tmp/nix-public.key)" \
          '{private_key: $priv, public_key: $pub}' > ${path.module}/nix-cache-key.json
        rm /tmp/nix-private.key /tmp/nix-public.key
        echo "✅ Nix cache signing key generated"
      else
        echo "ℹ️  Nix cache signing key already exists"
      fi
    EOT
  }
}

data "local_file" "nix_cache_key" {
  depends_on = [null_resource.nix_cache_key_generate]
  filename   = "${path.module}/nix-cache-key.json"
}

locals {
  nix_cache_keys = jsondecode(data.local_file.nix_cache_key.content)
}

# ============================================
# OUTPUTS
# ============================================

# Sealed secrets outputs
output "sealed_secrets_private_key_pem" {
  description = "Sealed secrets RSA private key (PEM format)"
  value       = tls_private_key.sealed_secrets.private_key_pem
  sensitive   = true
}

output "sealed_secrets_cert_pem" {
  description = "Sealed secrets self-signed certificate (PEM format)"
  value       = tls_self_signed_cert.sealed_secrets.cert_pem
  sensitive   = false
}

# Flux deploy key outputs
output "flux_deploy_public_key" {
  description = "Flux deploy key public key (OpenSSH format) - add to GitHub"
  value       = tls_private_key.flux_deploy.public_key_openssh
}

output "flux_deploy_private_key" {
  description = "Flux deploy key private key (OpenSSH format)"
  value       = tls_private_key.flux_deploy.private_key_openssh
  sensitive   = true
}

# Nix cache outputs
output "nix_cache_public_key" {
  description = "Nix cache signing public key for trusted-public-keys"
  value       = local.nix_cache_keys.public_key
}

output "nix_cache_private_key" {
  description = "Nix cache signing private key"
  value       = local.nix_cache_keys.private_key
  sensitive   = true
}
