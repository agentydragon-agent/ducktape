#!/bin/bash
set -e

SECRET_NAME="activitywatch-authkey"
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

echo "Looking up activitywatch user ID..."
# --user takes a numeric ID, not a name
USER_ID=$(kubectl exec deployment/headscale -n "$NAMESPACE" -- \
  headscale users list -o json | jq -r '.[] | select(.name == "activitywatch") | .id')

if [ -z "$USER_ID" ]; then
  echo "ERROR: Could not find activitywatch user"
  exit 1
fi
echo "Found activitywatch user ID: $USER_ID"

echo "Creating pre-auth key for activitywatch..."
# TODO: Move pre-auth key back to Terraform after upstream provider fix:
# https://github.com/awlsring/terraform-provider-headscale/pull/28
AUTHKEY=$(kubectl exec deployment/headscale -n "$NAMESPACE" -- \
  headscale preauthkeys create \
  --user "$USER_ID" \
  --reusable \
  --expiration 8760h \
  --tags tag:service)

# Strip whitespace
AUTHKEY=$(echo "$AUTHKEY" | tr -d '[:space:]')

if [ -z "$AUTHKEY" ]; then
  echo "ERROR: Could not create pre-auth key"
  exit 1
fi

# Validate key format (hskey-auth-{prefix}-{secret}, at least 40 chars)
if [ ${#AUTHKEY} -lt 40 ]; then
  echo "ERROR: Key too short (${#AUTHKEY} chars), expected at least 40"
  echo "Key prefix: ${AUTHKEY:0:20}..."
  exit 1
fi

echo "Pre-auth key created (first 20 chars): ${AUTHKEY:0:20}..."

# Create secret with Reflector annotations to copy to activitywatch namespace
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: Secret
metadata:
  name: $SECRET_NAME
  namespace: $NAMESPACE
  annotations:
    reflector.v1.k8s.emberstack.com/reflection-allowed: "true"
    reflector.v1.k8s.emberstack.com/reflection-allowed-namespaces: "activitywatch"
    reflector.v1.k8s.emberstack.com/reflection-auto-enabled: "true"
    reflector.v1.k8s.emberstack.com/reflection-auto-namespaces: "activitywatch"
  labels:
    app.kubernetes.io/name: activitywatch
    app.kubernetes.io/component: authkey
type: Opaque
stringData:
  TS_AUTHKEY: "$AUTHKEY"
EOF

echo "Secret $SECRET_NAME created with Reflector annotations."
