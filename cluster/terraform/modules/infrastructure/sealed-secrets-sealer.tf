# Sealed secrets sealing infrastructure
# CSI secrets moved to storage module - this now handles infrastructure-only secrets


# Auto-commit any sealed secret changes in the repository
resource "null_resource" "commit_sealed_secrets" {
  # Run whenever terraform applies to check for any sealed secret changes
  triggers = {
    timestamp = timestamp()
  }

  provisioner "local-exec" {
    command = <<-EOF
      cd ${path.module}/../..

      # Check if there are changes to sealed secrets
      if git diff --quiet k8s/**/*-sealed.yaml 2>/dev/null; then
        echo "No changes to sealed secrets"
      else
        # Add and commit the changes
        git add k8s/**/*-sealed.yaml
        git commit -m "chore: auto-seal secrets with terraform-generated keypair

Terraform automatically resealed secrets with the stable keypair.

🤖 Generated with [Claude Code](https://claude.ai/code)

Co-Authored-By: Claude <noreply@anthropic.com>" || true
        echo "Committed updated sealed secrets"
      fi
    EOF
  }
}

