#!/usr/bin/env bash
# Terraform/OpenTofu validation wrapper with tfmirror.dev network mirror
# This script sets up tfmirror.dev as a network mirror and runs tofu validate
#
# Usage: tofu_validate.sh <tofu_binary> <module_directory>
# - tofu_binary: path to tofu binary (from Bazel toolchain)
# - module_directory: path to terraform module to validate
set -euo pipefail

TOFU_BIN_ARG="${1:?Usage: tofu_validate.sh <tofu_binary> <module_directory>}"
MODULE_DIR="${2:?Usage: tofu_validate.sh <tofu_binary> <module_directory>}"

# Resolve tofu binary to absolute path before changing directories
# In Bazel runfiles, paths are relative to the runfiles directory
TOFU_BIN="$(cd "$(dirname "$TOFU_BIN_ARG")" && pwd)/$(basename "$TOFU_BIN_ARG")"

# Verify tofu binary exists
if [[ ! -x "$TOFU_BIN" ]]; then
  echo "Error: tofu binary not found or not executable: $TOFU_BIN" >&2
  exit 1
fi

# Create a temporary .tofurc with tfmirror.dev as network mirror
TOFU_CONFIG="$(mktemp)"
cat >"$TOFU_CONFIG" <<'EOF'
provider_installation {
  network_mirror {
    url = "https://tfmirror.dev/"
  }
}
EOF

# Export the config file location
export TF_CLI_CONFIG_FILE="$TOFU_CONFIG"

# Cleanup on exit
cleanup() {
  rm -f "$TOFU_CONFIG"
}
trap cleanup EXIT

# Change to module directory
cd "$MODULE_DIR"

# Run tofu init with minimal output (skip backend, no interactive prompts)
echo "Initializing terraform in $MODULE_DIR..."
"$TOFU_BIN" init -backend=false -input=false -no-color

# Run validation
echo "Validating terraform configuration..."
"$TOFU_BIN" validate -no-color

echo "Validation successful!"
