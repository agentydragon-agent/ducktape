# BOOTSTRAP SECRETS: Wait for sealed-secrets controller
# Authentik bootstrap now handled by ESO password generator

# Wait for sealed-secrets controller to be ready after Flux deploys it
resource "null_resource" "wait_for_sealed_secrets" {
  provisioner "local-exec" {
    command = <<-EOF
      echo "⏳ Waiting for sealed-secrets controller to be deployed by Flux..."
      # Wait for sealed-secrets controller to be deployed by Flux
      kubectl wait --for=condition=available deployment/sealed-secrets-controller -n kube-system --timeout=300s
      echo "✅ Sealed-secrets controller is ready"
    EOF
  }

  depends_on = [flux_bootstrap_git.cluster]
}