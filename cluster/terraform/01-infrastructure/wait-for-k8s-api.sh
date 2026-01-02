#!/bin/bash
# Wait for Kubernetes API to become ready
# Accesses API via first control plane node IP (not VIP) to avoid circular dependency
# VIP requires Cilium L2 announcements, so we can't wait on VIP before deploying Cilium

set -euo pipefail

K8S_SERVER="${K8S_SERVER:?K8S_SERVER environment variable must be set}"
KUBECONFIG="${KUBECONFIG:?KUBECONFIG environment variable must be set}"

echo "Waiting for Kubernetes API to be ready (via $K8S_SERVER)..."

for i in $(seq 1 60); do
  if kubectl --server="$K8S_SERVER" get nodes --request-timeout=10s >/dev/null 2>&1 && \
     kubectl --server="$K8S_SERVER" get serviceaccount default -n default --request-timeout=10s >/dev/null 2>&1 && \
     kubectl --server="$K8S_SERVER" auth can-i create pods --request-timeout=10s >/dev/null 2>&1; then
    echo "Kubernetes API is fully ready for workloads!"
    exit 0
  fi
  echo "Attempt $i/60: Waiting for API readiness..."
  sleep 10
done

echo "Kubernetes API failed to become ready after 10 minutes"
exit 1
