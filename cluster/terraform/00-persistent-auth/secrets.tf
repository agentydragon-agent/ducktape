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
# Uses nix-store format, generated once and cached in local file
# File is gitignored, backed up with terraform state to Google Drive
# ============================================
data "external" "nix_cache_key" {
  program = ["bash", "-c", <<-EOT
    KEY_FILE="${path.module}/nix-cache-key.json"
    if [ ! -f "$KEY_FILE" ]; then
      nix-store --generate-binary-cache-key cache.test-cluster.agentydragon.com-1 /tmp/nix-priv.$$ /tmp/nix-pub.$$ 2>/dev/null
      jq -n --arg priv "$(cat /tmp/nix-priv.$$)" --arg pub "$(cat /tmp/nix-pub.$$)" \
        '{private_key: $priv, public_key: $pub}' > "$KEY_FILE"
      rm -f /tmp/nix-priv.$$ /tmp/nix-pub.$$
    fi
    cat "$KEY_FILE"
  EOT
  ]
}

locals {
  nix_cache_keys = data.external.nix_cache_key.result
}
