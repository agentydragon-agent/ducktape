#!/bin/bash
# Run alejandra on Nix files
# Usage: run_alejandra.sh <alejandra_binary> [--check] <files...>
set -euo pipefail

ALEJANDRA="$1"
shift

# Pass remaining args (including optional --check and files) to alejandra
exec "$ALEJANDRA" "$@"
