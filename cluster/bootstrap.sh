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
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

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

log "Starting cluster bootstrap. Terraform directory: ${TERRAFORM_DIR}"
if [ -n "$START_FROM_LAYER" ]; then
  log "⏩ Starting from layer: $START_FROM_LAYER"
fi

log "🔍 Phase 0: Preflight Validation"

# Get repo root first - must run git commands from there because cluster/.git is broken.
# Claude Code's sandbox creates phantom dotfiles including an empty .git file in cluster/
# which breaks git operations when run from within the cluster directory.
# See: https://github.com/anthropics/claude-code/issues/17258
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && git rev-parse --show-toplevel)"

# Check git working tree is clean (only cluster subtree - monorepo may have other changes)
if ! (cd "$REPO_ROOT" && git diff-index --quiet HEAD -- cluster/); then
  echo "❌ FATAL: Git working tree is not clean in cluster/"
  echo "Please commit or stash your cluster changes before running bootstrap"
  exit 1
fi

# Run pre-commit validation from repo root (unified config)
# Only validate cluster files to avoid failures from unrelated packages
log "🔍 Running pre-commit validation on cluster files..."
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
  log "⚡ Layer 0: Persistent Auth Setup"

  cd "${TERRAFORM_DIR}/00-persistent-auth"

  # Check if persistent auth already exists
  if [ -f "terraform.tfstate" ] && tofu show -json | jq -e '.values.root_module.resources | length > 0' >/dev/null 2>&1; then
    log "ℹ️  Persistent auth already exists - skipping ('cd terraform/00-persistent-auth && tofu destroy' to reset auth)"
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
  log "⚡ Layer 1: Infrastructure Deployment"

  cd "${TERRAFORM_DIR}/01-infrastructure"
  log "🚀 Deploying infrastructure layer... (PVE-AUTH → VMs → TALOS → CILIUM → SEALED-SECRETS)"

  if ! tofu apply -auto-approve; then
    log "❌ FATAL: Infrastructure deployment failed"
    exit 1
  fi

  log "🔍 Verifying infrastructure readiness..."
  KUBECONFIG_PATH="${TERRAFORM_DIR}/01-infrastructure/kubeconfig"
  export KUBECONFIG="$KUBECONFIG_PATH"

  # Terraform waits for nodes to be Ready via kubernetes_nodes data source
  # Just verify cluster is accessible
  log "⏳ Verifying cluster access..."
  kubectl cluster-info
  kubectl get nodes

  # Rolling restart Cilium to refresh BPF state for existing processes
  # API servers are static pods started before Cilium - their sockets were
  # created without BPF interception. Restarting Cilium forces re-attachment
  # of BPF programs to all processes, fixing ClusterIP routing for webhooks.
  log "⏳ Restarting Cilium to refresh BPF state for API servers..."
  kubectl rollout restart daemonset/cilium -n kube-system
  kubectl rollout status daemonset/cilium -n kube-system --timeout=300s
  log "✅ Cilium restarted, BPF state refreshed"

  echo "✅ Infrastructure layer ready"
fi

log "⚡ Layer 2: Services"

# Ensure kubeconfig is available for services layer
if [ -z "$KUBECONFIG" ]; then
  KUBECONFIG_PATH="${TERRAFORM_DIR}/01-infrastructure/kubeconfig"
  export KUBECONFIG="$KUBECONFIG_PATH"
fi

cd "${TERRAFORM_DIR}/02-services"
log "🚀 Deploying services layer... (GITOPS → AUTHENTIK → POWERDNS → HARBOR → GITEA → MATRIX)"

if ! tofu apply -auto-approve; then
  log "❌ FATAL: Services deployment failed"
  exit 1
fi

log "⏳ Waiting for Authentik and PowerDNS..."
kubectl wait --for=condition=available deployment/authentik -n authentik-system --timeout=600s &
kubectl wait --for=condition=available deployment/powerdns -n powerdns-system --timeout=600s &
wait

log "✅ Services layer ready"

log "🎉 Cluster bootstrap completed!"
echo ""
echo "📋 Post-bootstrap automation (via Flux/GitOps):"
echo "   • DNS: PowerDNS Operator (zone) + external-dns (records from Ingresses)"
echo "   • SSO: tofu-controller applies terraform/authentik-blueprint/ configurations"
echo "   • Gitea: Automated token generation + OAuth config via Jobs"
echo ""
echo "🔗 Access cluster: export KUBECONFIG='${KUBECONFIG_PATH}'"
