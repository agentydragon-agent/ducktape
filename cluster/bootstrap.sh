#!/bin/bash
# LAYERED TALOS CLUSTER BOOTSTRAP SCRIPT
# This is the ONLY supported way to bootstrap the cluster
#
# Multi-layer deployment with persistent auth separation:
# Layer 0: Persistent Auth (CSI tokens, sealed secrets keypair)
# Layer 1: Infrastructure (VMs, Talos, CNI, networking)
# Layer 2: Services (Deploy via GitOps - Flux handles DNS/SSO automatically)

set -e

# Fix pre-commit/pip compatibility with Nix environment
export PIP_USER=false
export PRE_COMMIT_USE_UV=1

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TERRAFORM_DIR="${SCRIPT_DIR}/terraform"

# Timestamp function for all output
log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

# Parse command line arguments
START_FROM_LAYER=""
HELP=false

while [[ $# -gt 0 ]]; do
  case $1 in
    --start-from)
      START_FROM_LAYER="$2"
      shift 2
      ;;
    --help | -h)
      HELP=true
      shift
      ;;
    *)
      echo "❌ Unknown option: $1"
      echo "Usage: $0 [--start-from infrastructure|services] [--help]"
      exit 1
      ;;
  esac
done

if [ "$HELP" = true ]; then
  echo "🚀 Layered Talos Cluster Bootstrap"
  echo ""
  echo "Usage: $0 [OPTIONS]"
  echo ""
  echo "Options:"
  echo "  --start-from LAYER    Skip earlier layers, start from: infrastructure|services"
  echo "  --help, -h           Show this help message"
  echo ""
  echo "Layers:"
  echo "  0. persistent-auth    CSI tokens, sealed secrets (persistent across VM lifecycle)"
  echo "  1. infrastructure     VMs, Talos, CNI, networking (ephemeral)"
  echo "  2. services          GitOps applications (Flux handles DNS/SSO automatically)"
  echo ""
  echo "Examples:"
  echo "  $0                                    # Full bootstrap"
  echo "  $0 --start-from infrastructure       # Skip persistent auth, rebuild VMs"
  echo "  $0 --start-from services             # Skip infra, redeploy services"
  exit 0
fi

log "🚀 Starting layered Talos cluster bootstrap..."
log "📂 Terraform directory: ${TERRAFORM_DIR}"
if [ -n "$START_FROM_LAYER" ]; then
  log "⏩ Starting from layer: $START_FROM_LAYER"
fi

# Phase 0: Preflight Validation
echo ""
log "🔍 Phase 0: Preflight Validation"
echo "=================================="

# Check git working tree is clean (only cluster subtree - monorepo may have other changes)
if ! git diff-index --quiet HEAD -- cluster/; then
  echo "❌ FATAL: Git working tree is not clean in cluster/"
  echo "Please commit or stash your cluster changes before running bootstrap"
  exit 1
fi

# Run pre-commit validation from repo root (unified config)
# Only validate cluster files to avoid failures from unrelated packages
log "🔍 Running pre-commit validation on cluster files..."
REPO_ROOT="$(git rev-parse --show-toplevel)"
if ! (cd "$REPO_ROOT" && git ls-files -- cluster/ | xargs pre-commit run --files); then
  log "❌ FATAL: Pre-commit validation failed"
  exit 1
fi

# Validate each layer's terraform configuration
for layer in "00-persistent-auth" "01-infrastructure" "02-services"; do
  log "🔍 Validating terraform layer: ${layer}..."
  cd "${TERRAFORM_DIR}/${layer}"
  if ! tofu validate; then
    log "❌ FATAL: Terraform configuration is invalid in layer ${layer}"
    exit 1
  fi
done

# Phase 0.5: Persistent Auth Layer (if needed)
if [ "$START_FROM_LAYER" != "infrastructure" ] && [ "$START_FROM_LAYER" != "services" ] && [ "$START_FROM_LAYER" != "configuration" ]; then
  echo ""
  log "⚡ Layer 0: Persistent Auth Setup"
  echo "================================"

  cd "${TERRAFORM_DIR}/00-persistent-auth"

  # Check if persistent auth already exists
  if [ -f "terraform.tfstate" ] && tofu show -json | jq -e '.values.root_module.resources | length > 0' >/dev/null 2>&1; then
    log "ℹ️  Persistent auth layer already exists - skipping deployment"
    echo "    Use 'cd terraform/00-persistent-auth && tofu destroy' to reset auth"
  else
    log "🚀 Deploying persistent auth layer..."
    echo "     📋 CSI-TOKENS → SEALED-SECRETS-KEYPAIR → GIT-COMMIT"

    if ! tofu apply -auto-approve; then
      log "❌ FATAL: Persistent auth deployment failed"
      exit 1
    fi

    log "✅ Persistent auth layer ready"
  fi
fi

# Phase 1: Infrastructure Layer
if [ "$START_FROM_LAYER" != "services" ]; then
  echo ""
  log "⚡ Layer 1: Infrastructure Deployment"
  echo "===================================="

  cd "${TERRAFORM_DIR}/01-infrastructure"
  log "🚀 Deploying infrastructure layer..."
  echo "     📋 PVE-AUTH → VMs → TALOS → CILIUM → SEALED-SECRETS"

  if ! tofu apply -auto-approve; then
    log "❌ FATAL: Infrastructure deployment failed"
    exit 1
  fi

  # Verify infrastructure readiness
  log "🔍 Verifying infrastructure readiness..."
  KUBECONFIG_PATH="${TERRAFORM_DIR}/01-infrastructure/kubeconfig"
  export KUBECONFIG="$KUBECONFIG_PATH"

  # Terraform waits for nodes to be Ready via kubernetes_nodes data source
  # Just verify cluster is accessible
  log "⏳ Verifying cluster access..."
  kubectl cluster-info
  kubectl get nodes

  echo "✅ Infrastructure layer ready"
fi

# Phase 2: Services Layer
echo ""
log "⚡ Layer 2: Services Deployment"
echo "=============================="

# Ensure kubeconfig is available for services layer
if [ -z "$KUBECONFIG" ]; then
  KUBECONFIG_PATH="${TERRAFORM_DIR}/01-infrastructure/kubeconfig"
  export KUBECONFIG="$KUBECONFIG_PATH"
fi

cd "${TERRAFORM_DIR}/02-services"
log "🚀 Deploying services layer..."
echo "     📋 GITOPS → AUTHENTIK → POWERDNS → HARBOR → GITEA → MATRIX"

if ! tofu apply -auto-approve; then
  log "❌ FATAL: Services deployment failed"
  exit 1
fi

# Wait for critical services to be ready
log "⏳ Waiting for services to be ready..."

# Wait for Authentik
log "⏳ Waiting for Authentik deployment..."
timeout 300 bash -c 'until kubectl get deployment authentik -n authentik-system 2>/dev/null; do sleep 10; done'
kubectl wait --for=condition=available deployment/authentik -n authentik-system --timeout=600s

# Wait for PowerDNS
log "⏳ Waiting for PowerDNS deployment..."
timeout 300 bash -c 'until kubectl get deployment powerdns -n powerdns-system 2>/dev/null; do sleep 10; done'
kubectl wait --for=condition=available deployment/powerdns -n powerdns-system --timeout=600s

# Wait for PowerDNS API to be responsive
log "⏳ Waiting for PowerDNS API to be ready..."
CLUSTER_VIP="10.2.3.1" # TODO: Get from terraform output
timeout 300 bash -c "until curl -sf http://${CLUSTER_VIP}:8081/api/v1/servers; do sleep 5; done"

log "✅ Services layer ready"

echo ""
log "🎉 Cluster bootstrap completed!"
echo "📊 Bootstrap phases:"
echo "   ✅ Phase 0: Persistent auth (CSI tokens, sealed secrets keypair)"
echo "   ✅ Phase 1: Infrastructure (VMs, Talos, Cilium)"
echo "   ✅ Phase 2: Services (Flux, Vault, Authentik, applications)"
echo ""
echo "📋 Post-bootstrap automation (via Flux/GitOps):"
echo "   • DNS: PowerDNS Operator (zone) + external-dns (records from Ingresses)"
echo "   • SSO: tofu-controller applies terraform/authentik-blueprint/ configurations"
echo "   • Gitea: Automated token generation + OAuth config via Jobs"
echo ""
echo "🔗 Access cluster: export KUBECONFIG='${KUBECONFIG_PATH}'"
