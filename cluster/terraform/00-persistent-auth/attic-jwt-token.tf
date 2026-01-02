# Attic JWT Token Generation - Terraform-managed
# JWT token for Attic HTTP API authentication
# Stored in terraform state for persistence

# Generate random JWT token - terraform manages this directly in state
resource "random_password" "attic_jwt_token" {
  length  = 86 # ~64 bytes of entropy
  special = false
}

# Generate SealedSecret for Attic JWT token
resource "null_resource" "attic_jwt_token_sealed_secret" {
  triggers = {
    # Re-run when token or keypair change
    token_hash   = sha256(random_password.attic_jwt_token.result)
    keypair_hash = sha256(tls_self_signed_cert.sealed_secrets.cert_pem)
  }

  provisioner "local-exec" {
    command = <<-EOT
      # Get JWT token from terraform
      jwt_token='${random_password.attic_jwt_token.result}'

      # Create kubernetes secret YAML
      cat > /tmp/attic-jwt-token.yaml <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: attic-jwt-token
  namespace: nix-cache
type: Opaque
stringData:
  jwt-token: "$jwt_token"
EOF

      # Seal the secret using terraform-generated keypair
      cat > /tmp/sealed-secrets-cert.pem <<'CERTEOF'
${tls_self_signed_cert.sealed_secrets.cert_pem}
CERTEOF
      kubeseal --cert /tmp/sealed-secrets-cert.pem \
        --format=yaml < /tmp/attic-jwt-token.yaml > ${path.root}/../../k8s/applications/nix-cache/jwt-token-sealed.yaml
      rm /tmp/sealed-secrets-cert.pem

      # Clean up temporary file
      rm /tmp/attic-jwt-token.yaml

      echo "✅ Generated sealed secret for Attic JWT token"
    EOT
  }
}

# Note: Commit sealed secrets manually after terraform apply:
# git add k8s/applications/nix-cache/jwt-token-sealed.yaml
# git commit -m "chore: update Attic JWT token sealed secret"

# Output for verification
output "attic_jwt_token" {
  value       = random_password.attic_jwt_token.result
  description = "Attic JWT token for HTTP API authentication"
  sensitive   = true
}
