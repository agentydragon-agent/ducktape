#!/bin/bash
set -e

SECRET_NAME="headscale-api-key"
NAMESPACE="headscale"

# Idempotent: skip if secret already exists
if kubectl get secret "$SECRET_NAME" -n "$NAMESPACE" >/dev/null 2>&1; then
  echo "Secret $SECRET_NAME already exists, skipping (idempotent)."
  exit 0
fi

echo "Waiting for headscale to be healthy..."
until kubectl exec deployment/headscale -n "$NAMESPACE" -- headscale health >/dev/null 2>&1; do
  echo "Headscale not ready, waiting..."
  sleep 5
done
echo "Headscale is healthy."

echo "Creating API key..."
API_KEY_JSON=$(kubectl exec deployment/headscale -n "$NAMESPACE" -- \
  headscale apikeys create --expiration 87600h --output json)

# v0.28 outputs a plain JSON string, not an object
API_KEY=$(echo "$API_KEY_JSON" | jq -r 'if type == "string" then . elif type == "object" then (.apiKey // .key // empty) else empty end')

if [ -z "$API_KEY" ]; then
  echo "ERROR: Could not extract API key from response"
  echo "Response: $API_KEY_JSON"
  exit 1
fi

echo "API key created (first 8 chars): ${API_KEY:0:8}..."

# Create secret with Reflector annotations to copy to flux-system
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: Secret
metadata:
  name: $SECRET_NAME
  namespace: $NAMESPACE
  annotations:
    reflector.v1.k8s.emberstack.com/reflection-allowed: "true"
    reflector.v1.k8s.emberstack.com/reflection-allowed-namespaces: "flux-system"
    reflector.v1.k8s.emberstack.com/reflection-auto-enabled: "true"
    reflector.v1.k8s.emberstack.com/reflection-auto-namespaces: "flux-system"
  labels:
    app.kubernetes.io/name: headscale
    app.kubernetes.io/component: api-key
type: Opaque
stringData:
  headscale_api_key: "$API_KEY"
EOF

echo "Secret $SECRET_NAME created with Reflector annotations."
