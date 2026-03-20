# Nebula certs for ActivityWatch sidecar — SealedSecret
#
# Generates a SealedSecret containing the Nebula CA cert, host cert, and host key
# for the ActivityWatch pod's Nebula sidecar. The pod uses these to join the mesh.

resource "null_resource" "nebula_activitywatch_sealed_secret" {
  triggers = {
    ca_hash      = sha256(data.local_file.nebula_ca_crt.content)
    cert_hash    = sha256(data.local_file.nebula_node_crt["activitywatch"].content)
    key_hash     = sha256(data.local_sensitive_file.nebula_node_key["activitywatch"].content)
    keypair_hash = sha256(tls_self_signed_cert.sealed_secrets.cert_pem)
  }

  provisioner "local-exec" {
    command = <<-EOT
      set -e

      ca_crt='${data.local_file.nebula_ca_crt.content}'
      host_crt='${data.local_file.nebula_node_crt["activitywatch"].content}'
      host_key='${data.local_sensitive_file.nebula_node_key["activitywatch"].content}'

      cat > /tmp/nebula-activitywatch-secret.yaml <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: activitywatch-nebula-certs
  namespace: activitywatch
type: Opaque
stringData:
  ca.crt: |
$(echo "$ca_crt" | sed 's/^/    /')
  host.crt: |
$(echo "$host_crt" | sed 's/^/    /')
  host.key: |
$(echo "$host_key" | sed 's/^/    /')
EOF

      cat > /tmp/sealed-secrets-cert.pem <<'CERTEOF'
${tls_self_signed_cert.sealed_secrets.cert_pem}
CERTEOF

      kubeseal --cert /tmp/sealed-secrets-cert.pem \
        --format=yaml < /tmp/nebula-activitywatch-secret.yaml \
        > ${path.module}/../../../k8s/applications/activitywatch/nebula-certs-sealed.yaml

      rm -f /tmp/sealed-secrets-cert.pem /tmp/nebula-activitywatch-secret.yaml

      echo "Generated sealed secret for ActivityWatch Nebula certs"
    EOT
  }

  depends_on = [
    null_resource.nebula_node_cert,
    null_resource.nebula_ca,
  ]
}
