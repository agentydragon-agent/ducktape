terraform {
  required_providers {
    null = {
      source = "hashicorp/null"
    }
  }
}

locals {
  sealed_secret_path = "${var.cluster_root}/k8s/${var.service_name}/${var.name}-sealed.yaml"
}

# Generate the bootstrap secret
resource "null_resource" "generate" {
  # Note: depends_on cannot use variables directly in terraform
  # Dependencies must be passed from parent module

  # Only run if sealed secret doesn't exist in filesystem
  count = fileexists(local.sealed_secret_path) ? 0 : 1

  provisioner "local-exec" {
    command = <<-EOF
      echo "🔐 Generating ${var.service_name} bootstrap secret..."

      if kubectl get secret ${var.name} -n ${var.namespace} 2>/dev/null; then
        echo "✓ ${var.name} already exists in cluster, skipping"
        exit 0
      fi

      openssl rand -hex 32 | \
        kubectl create secret generic ${var.name} \
        --from-file=${var.secret_key}=/dev/stdin \
        --namespace=${var.namespace} \
        --dry-run=client -o yaml | \
        kubeseal -o yaml > ${local.sealed_secret_path}

      echo "✅ Generated ${var.service_name} sealed secret"
    EOF
  }
}

# Cleanup on destroy - use triggers to store values for destroy-time access
resource "null_resource" "cleanup" {
  triggers = {
    sealed_secret_path = local.sealed_secret_path
    service_name       = var.service_name
  }

  provisioner "local-exec" {
    when    = destroy
    command = <<-EOF
      echo "🧹 Cleaning up ${self.triggers.service_name} sealed secret..."
      rm -f ${self.triggers.sealed_secret_path}
    EOF
  }
}

