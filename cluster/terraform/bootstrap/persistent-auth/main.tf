# LAYER 0: PERSISTENT AUTH
# Persistent authentication credentials that survive VM lifecycle
# Includes: CSI tokens, sealed secrets keypair, persistent auth storage

terraform {
  required_version = ">= 1.0"

  required_providers {
    external = {
      source  = "hashicorp/external"
      version = "~> 2.3.0"
    }
    proxmox = {
      source  = "bpg/proxmox"
      version = "~> 0.91.0"
    }
    local = {
      source  = "hashicorp/local"
      version = "~> 2.5.0"
    }
    null = {
      source  = "hashicorp/null"
      version = "~> 3.2.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.7.0"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.1.0"
    }
  }
}

# DRY configuration for persistent auth
# TODO: Consider whether terraform@pve is still needed now that root@pam!tofu exists.
# Infrastructure and nixos-k8s-worker could read the root token from the keyring via
# their own .envrc instead. Keeping for now for least-privilege (TerraformAdmin is
# narrower than root). kubernetes-csi@pve is definitely still needed — it runs inside
# the cluster and can't access the keyring.
locals {
  # Persistent Proxmox users - survive VM lifecycle
  pve_persistent_users = {
    csi = {
      name    = "kubernetes-csi@pve"
      comment = "Kubernetes CSI driver service account (persistent)"
      role    = "CSI"
      privs = [
        "Datastore.Allocate",
        "Datastore.AllocateSpace",
        "Datastore.Audit",
        "VM.Audit",
        "VM.Config.Disk",
      ]
      token = "csi"
    }
    terraform = {
      name    = "terraform@pve"
      comment = "Terraform automation user (persistent)"
      role    = "TerraformAdmin"
      privs = [
        "Datastore.Allocate",
        "Datastore.AllocateSpace",
        "Datastore.AllocateTemplate",
        "Datastore.Audit",
        "Mapping.Modify",
        "Mapping.Use",
        "Permissions.Modify",
        "Pool.Allocate",
        "SDN.Use",
        "Sys.Audit",
        "Sys.Console",
        "Sys.Modify",
        "User.Modify",
        "VM.Allocate",
        "VM.Audit",
        "VM.Clone",
        "VM.Config.CDROM",
        "VM.Config.CPU",
        "VM.Config.Cloudinit",
        "VM.Config.Disk",
        "VM.Config.HWType",
        "VM.Config.Memory",
        "VM.Config.Network",
        "VM.Config.Options",
        "VM.Console",
        "VM.GuestAgent.Audit",
        "VM.Migrate",
        "VM.PowerMgmt",
      ]
      token = "terraform-token"
    }
  }
}

# Proxmox provider — authenticated via PROXMOX_VE_API_TOKEN env var (root@pam!tofu
# token from GNOME keyring, exported by .envrc via direnv).
provider "proxmox" {
  endpoint = "https://${var.proxmox_api_host}:8006/"
  insecure = true
}

# Manage Proxmox roles, users, and API tokens as native resources.
# Token values persist in state and are only created once (idempotent).
resource "proxmox_virtual_environment_role" "persistent" {
  for_each   = local.pve_persistent_users
  role_id    = each.value.role
  privileges = each.value.privs
}

resource "proxmox_virtual_environment_user" "persistent" {
  for_each = local.pve_persistent_users
  user_id  = each.value.name
  comment  = each.value.comment
  acl {
    path      = "/"
    role_id   = proxmox_virtual_environment_role.persistent[each.key].role_id
    propagate = true
  }
}

resource "proxmox_virtual_environment_user_token" "persistent" {
  for_each              = local.pve_persistent_users
  user_id               = proxmox_virtual_environment_user.persistent[each.key].user_id
  token_name            = each.value.token
  privileges_separation = false
  comment               = "Managed by OpenTofu"
}

locals {
  # bpg/proxmox user_token.value returns "token_id=secret_uuid" (full API token string).
  # Split to extract just the UUID for consumers that need token_id and secret separately.
  pve_token_configs = {
    for key, user in local.pve_persistent_users : key => {
      url          = "https://${var.proxmox_api_host}:8006/api2/json"
      insecure     = true
      token_id     = proxmox_virtual_environment_user_token.persistent[key].id
      token_secret = element(split("=", proxmox_virtual_environment_user_token.persistent[key].value), 1)
      region       = "proxmox"
      token        = proxmox_virtual_environment_user_token.persistent[key].value
    }
  }
}

# Generate Proxmox CSI storage secrets using terraform-generated sealed-secrets keypair
resource "null_resource" "proxmox_csi_sealed_secret" {
  # Re-run when PVE auth tokens or keypair change
  triggers = {
    csi_config_hash = sha256(jsonencode(local.pve_token_configs["csi"]))
    keypair_hash    = sha256(tls_self_signed_cert.sealed_secrets.cert_pem)
  }

  provisioner "local-exec" {
    command = <<-EOT
      set -e

      # Create kubernetes secret YAML with CSI configuration
      cat > /tmp/proxmox-csi-secret.yaml <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: proxmox-csi-plugin
  namespace: csi-proxmox
type: Opaque
stringData:
  config.yaml: |
    clusters:
      - url: ${local.pve_token_configs["csi"].url}
        insecure: ${local.pve_token_configs["csi"].insecure}
        token_id: ${local.pve_token_configs["csi"].token_id}
        token_secret: ${local.pve_token_configs["csi"].token_secret}
        region: ${local.pve_token_configs["csi"].region}
EOF

      # Seal the secret using terraform-generated keypair
      cat > /tmp/sealed-secrets-cert.pem <<'CERTEOF'
${tls_self_signed_cert.sealed_secrets.cert_pem}
CERTEOF
      kubeseal --cert /tmp/sealed-secrets-cert.pem \
        --format=yaml < /tmp/proxmox-csi-secret.yaml > ${path.module}/../../../k8s/proxmox-csi/proxmox-csi-sealed.yaml
      rm /tmp/sealed-secrets-cert.pem

      # Clean up temporary file
      rm /tmp/proxmox-csi-secret.yaml

      echo "Generated sealed secret for Proxmox CSI"
    EOT
  }
}

# NOTE: Auto-commit removed - user must manually commit sealed secrets after terraform apply
# Run: git add k8s/proxmox-csi/proxmox-csi-sealed.yaml && git commit -m "chore: update sealed secret"
#
# The seal-secret.sh helper script reads the cert directly from terraform state
# via `terraform output -raw sealed_secrets_cert_pem`

# NOTE: No cleanup provisioner here - persistent tokens only destroyed when this layer is explicitly destroyed
