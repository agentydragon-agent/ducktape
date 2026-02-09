#!/bin/bash
set -euo pipefail

# Podman infrastructure startup script for props e2e testing.
#
# Detects gVisor (Claude Code on the Web) vs native environments and adjusts:
# - gVisor: --network=host, --annotation run.oci.keep_original_groups=1
# - Native: --network=host (simplified; bridge networks optional)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE_DIR="$SCRIPT_DIR/.devenv/state"
PASSWORD_FILE="$STATE_DIR/pg_password"

# Detect gVisor (Claude Code on the Web) by kernel version.
# gVisor always reports kernel 4.4.0; real Linux kernels are 5.x+.
if [[ "$(uname -r)" == "4.4.0" ]]; then
  IS_GVISOR=true
else
  IS_GVISOR=false
fi

# Build common podman flags.
# gVisor requires the keep_original_groups annotation to bypass
# /proc/self/setgroups which is unavailable in the sandbox.
PODMAN_EXTRA_FLAGS=("--network=host")
if $IS_GVISOR; then
  PODMAN_EXTRA_FLAGS+=("--annotation" "run.oci.keep_original_groups=1")
fi

echo "=== Props Infrastructure Startup ==="
echo "Environment: $(if $IS_GVISOR; then echo "gVisor (Claude Code on the Web)"; else echo "native"; fi)"

# Generate PostgreSQL password if not exists
mkdir -p "$STATE_DIR"
if [[ ! -f "$PASSWORD_FILE" ]]; then
  echo "Generating PostgreSQL password..."
  openssl rand -base64 24 >"$PASSWORD_FILE"
  chmod 600 "$PASSWORD_FILE"
fi
PG_PASSWORD=$(cat "$PASSWORD_FILE")
echo "PostgreSQL password loaded from $PASSWORD_FILE"

# Stop any existing containers
echo "Cleaning up existing containers..."
podman rm -f props-postgres props-registry props-registry-proxy 2>/dev/null || true

# Start PostgreSQL (port 5433)
echo "Starting PostgreSQL on 127.0.0.1:5433..."
podman run -d --rm \
  --replace \
  "${PODMAN_EXTRA_FLAGS[@]}" \
  --name props-postgres \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD="$PG_PASSWORD" \
  -e POSTGRES_DB=eval_results \
  -v props_eval_results_data:/var/lib/postgresql/data \
  docker.io/library/postgres:16 \
  postgres -c max_connections=200 -p 5433

# Wait for PostgreSQL
echo "Waiting for PostgreSQL to be ready..."
export PGPASSWORD="$PG_PASSWORD"
for i in {1..30}; do
  if psql -h 127.0.0.1 -p 5433 -U postgres -d postgres -c '\q' 2>/dev/null; then
    echo "PostgreSQL is ready"
    break
  fi
  if [ $i -eq 30 ]; then
    echo "ERROR: PostgreSQL failed to start within 30 seconds"
    exit 1
  fi
  sleep 1
done

# Start OCI Registry (port 5050)
echo "Starting OCI Registry on 127.0.0.1:5050..."
podman run -d --rm \
  --replace \
  "${PODMAN_EXTRA_FLAGS[@]}" \
  --name props-registry \
  -e REGISTRY_HTTP_ADDR=:5050 \
  -v props_registry_data:/var/lib/registry \
  docker.io/library/registry:2

# Wait for Registry
echo "Waiting for OCI Registry to be ready..."
for i in {1..30}; do
  if curl -sf http://127.0.0.1:5050/v2/ >/dev/null 2>&1; then
    echo "OCI Registry is ready"
    break
  fi
  if [ $i -eq 30 ]; then
    echo "ERROR: Registry failed to start within 30 seconds"
    exit 1
  fi
  sleep 1
done

echo ""
echo "=== Infrastructure Ready ==="
echo "PostgreSQL:      127.0.0.1:5433 (user: postgres, password in $PASSWORD_FILE)"
echo "OCI Registry:    127.0.0.1:5050 (direct access)"
echo ""
echo "Registry proxy is now provided by the backend (start separately)."
echo ""
echo "Environment variables to set:"
echo "  export PGHOST=127.0.0.1"
echo "  export PGPORT=5433"
echo "  export PGUSER=postgres"
echo "  export PGPASSWORD=\$(cat $PASSWORD_FILE)"
echo "  export PGDATABASE=eval_results"
echo "  export ADGN_PROPS_SPECIMENS_ROOT=/home/user/specimens"
echo ""
echo "To stop: podman stop props-postgres props-registry"
echo "To view logs: podman logs <container-name>"
echo ""
