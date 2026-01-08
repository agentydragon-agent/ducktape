# Attic JWT Token Generation - Terraform-managed
# JWT token for Attic HTTP API authentication
# Stored in terraform state for persistence

# Generate random bytes for JWT secret (32 bytes = 256 bits of entropy)
# We generate 48 chars of alphanumeric which provides ~285 bits of entropy
resource "random_password" "attic_jwt_token_raw" {
  length  = 48
  special = false
}

# Base64 encode the raw token for jwtSecretBase64 config
# Attic expects this field to be a base64-encoded string
locals {
  attic_jwt_token_base64 = base64encode(random_password.attic_jwt_token_raw.result)
}

# Generate SealedSecret for Attic JWT token
resource "null_resource" "attic_jwt_token_sealed_secret" {
  triggers = {
    # Re-run when token or keypair change
    token_hash   = sha256(local.attic_jwt_token_base64)
    keypair_hash = sha256(tls_self_signed_cert.sealed_secrets.cert_pem)
  }

  provisioner "local-exec" {
    command = <<-EOT
      # Get base64-encoded JWT token from terraform
      jwt_token_base64='${local.attic_jwt_token_base64}'

      # Create kubernetes secret YAML
      # The value is already base64-encoded, which is what Attic's jwtSecretBase64 expects
      cat > /tmp/attic-jwt-token.yaml <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: attic-jwt-token
  namespace: nix-cache
type: Opaque
stringData:
  jwt-token: "$jwt_token_base64"
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

      echo "✅ Generated sealed secret for Attic JWT token (base64-encoded)"
    EOT
  }
}

# Note: Commit sealed secrets manually after terraform apply:
# git add k8s/applications/nix-cache/jwt-token-sealed.yaml
# git commit -m "chore: update Attic JWT token sealed secret"
