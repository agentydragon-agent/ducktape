#!/usr/bin/env bash
# build_critic.sh — Build a custom critic image from a modified main.py
#
# Usage: ./build_critic.sh <path-to-custom-main.py> [variant-name]
#
# This script layers a custom main.py onto the base critic image using crane,
# computes the digest locally, pushes the image, and prints the digest.
#
# The resulting digest can be passed to:
#   start_critic(definition_id="sha256:...")
#
# Prerequisites:
#   - crane CLI available in PATH
#   - PROPS_REGISTRY_URL set (e.g., "registry:5000")
#   - PROPS_CRITIC_BASE_DIGEST set (base image digest, e.g., "sha256:abc...")
#
# Steps:
#   1. Export the base critic image to a tarball
#   2. Determine the runfiles path where main.py lives inside the image
#   3. Create a new OCI layer overlaying custom main.py at that path
#   4. Append the layer and push the image
#   5. Print the resulting digest
set -euo pipefail

CUSTOM_MAIN="${1:?Usage: build_critic.sh <path-to-custom-main.py> [variant-name]}"
VARIANT="${2:-custom}"

REGISTRY="${PROPS_REGISTRY_URL:?Set PROPS_REGISTRY_URL}"
BASE_DIGEST="${PROPS_CRITIC_BASE_DIGEST:?Set PROPS_CRITIC_BASE_DIGEST}"

WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT

BASE_REF="${REGISTRY}/critic@${BASE_DIGEST}"

# 1. Inspect the base image to find the main.py runfiles path
# The base critic image has main.py at a runfiles path like:
#   /app/<workspace>/props/agents/critic/main.py
# We find it via crane config's Entrypoint or by listing files.
MAIN_PY_PATH="props/agents/critic/main.py"
echo "Overlaying ${CUSTOM_MAIN} at ${MAIN_PY_PATH}" >&2

# 2. Create a tarball with the custom main.py at the correct path
mkdir -p "${WORK_DIR}/layer/${MAIN_PY_PATH%/*}"
cp "${CUSTOM_MAIN}" "${WORK_DIR}/layer/${MAIN_PY_PATH}"
tar -cf "${WORK_DIR}/layer.tar" -C "${WORK_DIR}/layer" .

# 3. Append the layer to the base image
crane mutate "${BASE_REF}" \
  --append "${WORK_DIR}/layer.tar" \
  --tag "${REGISTRY}/critic:${VARIANT}" \
  --output "${WORK_DIR}/image.tar"

# 4. Compute the digest from the local tarball
DIGEST="$(crane digest --tarball "${WORK_DIR}/image.tar")"

# 5. Push by digest
crane push "${WORK_DIR}/image.tar" "${REGISTRY}/critic:${VARIANT}"

echo "${DIGEST}"
