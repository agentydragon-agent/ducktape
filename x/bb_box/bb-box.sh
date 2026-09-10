#!/usr/bin/env bash
# Wrapper around bb box/execute for spinning up persistent VMs with custom sizing.
#
# Usage: bb-box.sh [flags] [name]
#   --cpus N        CPU cores (e.g., 2, 4, 8)
#   --mem SIZE      Memory (e.g., 4GB, 8GB)
#   --disk SIZE     Disk (e.g., 10GB, 20GB)
#   --image IMAGE   Container image (default: ubuntu 22.04)
#   --grace DURATION  Grace period after disconnect (default/max: 5m)
#   --idle DURATION   Idle timeout (default/max: 5m)
#   name            Runner recycling key (omit for ephemeral VM)

set -euo pipefail

CPUS=""
MEM=""
DISK=""
IMAGE=""
GRACE="5m"
IDLE="5m"
NAME=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --cpus)
      CPUS="$2"
      shift 2
      ;;
    --mem)
      MEM="$2"
      shift 2
      ;;
    --disk)
      DISK="$2"
      shift 2
      ;;
    --image)
      IMAGE="$2"
      shift 2
      ;;
    --grace)
      GRACE="$2"
      shift 2
      ;;
    --idle)
      IDLE="$2"
      shift 2
      ;;
    --help | -h)
      sed -n '3,12p' "$0"
      exit 0
      ;;
    -*)
      echo "Unknown flag: $1" >&2
      exit 1
      ;;
    *)
      NAME="$1"
      shift
      ;;
  esac
done

# If no custom sizing requested, delegate to bb box create (simpler, handles
# WireGuard setup and BES polling automatically).
if [[ -z "$CPUS" && -z "$MEM" && -z "$DISK" ]]; then
  args=(box create)
  [[ -n "$IMAGE" ]] && args+=(--image "$IMAGE")
  args+=(--grace_period "$GRACE" --idle_timeout "$IDLE")
  [[ -n "$NAME" ]] && args+=("$NAME")
  exec bb "${args[@]}"
fi

# Custom sizing: use bb execute with explicit exec properties, running
# bb ssh-server inside the executor.
if [[ -z "$NAME" ]]; then
  NAME="bb-box-$(date +%s)"
  echo "No name given; using ephemeral key: $NAME"
fi

props=(
  --exec_properties=workload-isolation-type=firecracker
  --exec_properties=network=external
  --exec_properties=DockerUser=buildbuddy
  --exec_properties=recycle-runner=true
  --exec_properties="runner-recycling-key=$NAME"
)

if [[ -n "$IMAGE" ]]; then
  # Ensure docker:// prefix
  [[ "$IMAGE" != docker://* ]] && IMAGE="docker://$IMAGE"
  props+=(--exec_properties="container-image=$IMAGE")
else
  props+=(--exec_properties="container-image=docker://ubuntu:22.04")
fi

[[ -n "$CPUS" ]] && props+=(--exec_properties="EstimatedCPU=$CPUS")
[[ -n "$MEM" ]] && props+=(--exec_properties="EstimatedMemory=$MEM")
[[ -n "$DISK" ]] && props+=(--exec_properties="EstimatedFreeDiskBytes=$DISK")

echo "Starting VM with recycling key: $NAME"
echo "Connect with: bb ssh $NAME"
echo ""

exec bb execute \
  --remote_timeout=24h \
  "${props[@]}" \
  -- bb ssh-server \
  --grace_period="$GRACE" \
  --idle_timeout="$IDLE" \
  "$NAME"
