# Attic JWT Token Generation - Terraform-managed
# JWT token for Attic HTTP API authentication
# Stored in terraform state for persistence

# Generate Attic JWT token if local file doesn't exist
resource "null_resource" "attic_jwt_token_generate" {
  provisioner "local-exec" {
    command = <<-EOT
      if [ ! -f ${path.module}/attic-jwt-token.json ]; then
        echo "🔑 Generating new Attic JWT token..."
        jwt_token=$(openssl rand 64 | base64 -w0)
        jq -n --arg token "$jwt_token" '{jwt_token: $token}' > ${path.module}/attic-jwt-token.json
        echo "✅ Attic JWT token generated"
      else
        echo "ℹ️  Attic JWT token already exists"
      fi
    EOT
  }
}

data "local_file" "attic_jwt_token" {
  depends_on = [null_resource.attic_jwt_token_generate]
  filename   = "${path.module}/attic-jwt-token.json"
}

locals {
  attic_jwt_token = jsondecode(data.local_file.attic_jwt_token.content).jwt_token
}

# Generate SealedSecret for Attic JWT token
resource "null_resource" "attic_jwt_token_sealed_secret" {
  triggers = {
    # Re-run when token or keypair change
    token_hash   = sha256(local.attic_jwt_token)
    keypair_hash = sha256(tls_self_signed_cert.sealed_secrets.cert_pem)
  }

  provisioner "local-exec" {
    command = <<-EOT
      # Get JWT token from terraform-managed file
      jwt_token='${local.attic_jwt_token}'

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

  depends_on = [null_resource.attic_jwt_token_generate]
}

# Commit sealed secrets changes to git
resource "null_resource" "commit_attic_jwt_sealed_secret" {
  triggers = {
    # Depend on the sealed secret generation
    sealed_secret_id = null_resource.attic_jwt_token_sealed_secret.id
  }

  provisioner "local-exec" {
    command = <<-EOT
      cd ${path.root}/../..
      if [ -f k8s/applications/nix-cache/jwt-token-sealed.yaml ]; then
        if ! git diff --quiet k8s/applications/nix-cache/jwt-token-sealed.yaml 2>/dev/null; then
          git add k8s/applications/nix-cache/jwt-token-sealed.yaml
          git commit -m "chore: update Attic JWT token sealed secret

🔄 Generated with terraform-managed sealed-secrets keypair
🔒 Persistent JWT token - survives cluster lifecycle

🤖 Generated with Claude Code

Co-Authored-By: Claude <noreply@anthropic.com>"
          echo "✅ Committed updated Attic JWT token sealed secret"
        else
          echo "ℹ️  Attic JWT token sealed secret unchanged - no commit needed"
        fi
      else
        echo "⚠️  Attic JWT token sealed secret file not found - skipping commit"
      fi
    EOT
  }

  depends_on = [null_resource.attic_jwt_token_sealed_secret]
}

# Output for verification
output "attic_jwt_token" {
  value       = local.attic_jwt_token
  description = "Attic JWT token for HTTP API authentication"
  sensitive   = true
}
