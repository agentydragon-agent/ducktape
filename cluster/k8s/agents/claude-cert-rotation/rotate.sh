#!/bin/bash
set -euo pipefail

CSR_NAME="claude-code-web-$(date +%s)"
KEY_FILE="/tmp/client.key"
CSR_FILE="/tmp/client.csr"
CERT_FILE="/tmp/client.crt"
GITHUB_PAT=$(cat /var/run/secrets/github-pat/token)

# Generate private key and CSR.
# O= maps to Kubernetes groups — this puts the cert bearer in the OIDC sandbox group.
openssl genrsa -out "$KEY_FILE" 4096 2>/dev/null
openssl req -new -key "$KEY_FILE" \
  -subj "/CN=claude-code-web/O=oidc-ksbx-groups:kubectl-sandbox-users" \
  -out "$CSR_FILE"

# Submit CSR to the Kubernetes API
CSR_B64=$(base64 -w0 "$CSR_FILE")
kubectl apply -f - <<EOF
apiVersion: certificates.k8s.io/v1
kind: CertificateSigningRequest
metadata:
  name: ${CSR_NAME}
spec:
  request: ${CSR_B64}
  signerName: kubernetes.io/kube-apiserver-client
  usages:
    - client auth
  expirationSeconds: 31536000
EOF

# Approve and retrieve the signed certificate
kubectl certificate approve "$CSR_NAME"

# Wait for the certificate to be issued (up to 30s)
for i in $(seq 1 30); do
  CERT=$(kubectl get csr "$CSR_NAME" -o jsonpath='{.status.certificate}' 2>/dev/null || true)
  if [ -n "$CERT" ]; then
    break
  fi
  sleep 1
done

if [ -z "$CERT" ]; then
  echo "ERROR: certificate not issued after 30s"
  kubectl delete csr "$CSR_NAME" || true
  exit 1
fi

echo "$CERT" | base64 -d >"$CERT_FILE"

# Clean up the CSR resource
kubectl delete csr "$CSR_NAME"

# Clone repo and write the SOPS-encrypted cert
git clone --depth=1 --branch=devel \
  "https://x-access-token:${GITHUB_PAT}@github.com/agentydragon/ducktape.git" \
  /tmp/repo
cd /tmp/repo

cat >secrets/claude-web-k8s-cert.yaml <<EOF
client_cert: |
$(sed 's/^/  /' "$CERT_FILE")
client_key: |
$(sed 's/^/  /' "$KEY_FILE")
EOF

sops encrypt --in-place secrets/claude-web-k8s-cert.yaml

git config user.name "claude-cert-rotation"
git config user.email "noreply@allegedly.works"
git add secrets/claude-web-k8s-cert.yaml

if git diff --cached --quiet; then
  echo "No changes to commit"
else
  git commit -m "chore: rotate Claude web K8s client cert ($(date -I))"
  git push origin devel
fi

# Clean up sensitive files
rm -f "$KEY_FILE" "$CSR_FILE" "$CERT_FILE"
