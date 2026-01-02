# Nix Cache Signing Key - now managed in secrets.tf
# Key is generated once and stored in local file (nix-cache-key.json)
# The file is backed up with terraform state

# Generate SealedSecret for Nix cache signing key
resource "null_resource" "nix_cache_signing_key_sealed_secret" {
  triggers = {
    # Re-run when keys or sealed-secrets keypair change
    keys_hash    = sha256("${local.nix_cache_keys.private_key}:${local.nix_cache_keys.public_key}")
    keypair_hash = sha256(tls_self_signed_cert.sealed_secrets.cert_pem)
  }

  provisioner "local-exec" {
    command = <<-EOT
      # Get keys from terraform-managed local file
      private_key='${local.nix_cache_keys.private_key}'
      public_key='${local.nix_cache_keys.public_key}'

      # Create kubernetes secret YAML
      cat > /tmp/nix-cache-signing-key.yaml <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: nix-cache-signing-key
  namespace: nix-cache
type: Opaque
stringData:
  signing-key.sec: |
    $private_key
  signing-key.pub: |
    $public_key
EOF

      # Seal the secret using terraform-generated keypair
      cat > /tmp/sealed-secrets-cert.pem <<'CERTEOF'
${tls_self_signed_cert.sealed_secrets.cert_pem}
CERTEOF
      kubeseal --cert /tmp/sealed-secrets-cert.pem \
        --format=yaml < /tmp/nix-cache-signing-key.yaml > ${path.root}/../../k8s/applications/nix-cache/signing-key-sealed.yaml
      rm /tmp/sealed-secrets-cert.pem

      # Clean up temporary file
      rm /tmp/nix-cache-signing-key.yaml

      echo "✅ Generated sealed secret for Nix cache signing key"
    EOT
  }

  depends_on = [null_resource.nix_cache_key_generate]
}

# Commit sealed secrets changes to git
resource "null_resource" "commit_nix_cache_sealed_secret" {
  triggers = {
    # Depend on the sealed secret generation
    sealed_secret_id = null_resource.nix_cache_signing_key_sealed_secret.id
  }

  provisioner "local-exec" {
    command = <<-EOT
      cd ${path.root}/../..
      if [ -f k8s/applications/nix-cache/signing-key-sealed.yaml ]; then
        if ! git diff --quiet k8s/applications/nix-cache/signing-key-sealed.yaml 2>/dev/null; then
          git add k8s/applications/nix-cache/signing-key-sealed.yaml
          git commit -m "chore: update Nix cache signing key sealed secret

🔄 Generated with terraform-managed sealed-secrets keypair
🔒 Persistent signing key - survives cluster lifecycle

🤖 Generated with Claude Code

Co-Authored-By: Claude <noreply@anthropic.com>"
          echo "✅ Committed updated Nix cache sealed secret"
        else
          echo "ℹ️  Nix cache sealed secret unchanged - no commit needed"
        fi
      else
        echo "⚠️  Nix cache sealed secret file not found - skipping commit"
      fi
    EOT
  }

  depends_on = [null_resource.nix_cache_signing_key_sealed_secret]
}
