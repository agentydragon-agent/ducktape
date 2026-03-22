#!/usr/bin/env bash
# CI script to build and push a base image, then update MODULE.bazel digest.
#
# Usage (in GitHub Actions):
#   ./ci_build_base.sh devinfra/rbe_image ghcr.io/agentydragon/rbe-worker-base
#
# This script:
# 1. Builds the Dockerfile in the given context directory
# 2. Pushes to the given registry
# 3. Extracts the digest
# 4. Prints the oci.pull() snippet for MODULE.bazel
#
# The CI workflow should then open a PR updating MODULE.bazel with the new digest.

set -euo pipefail

CONTEXT_DIR="${1:?Usage: $0 <context-dir> <registry/image>}"
REGISTRY_IMAGE="${2:?Usage: $0 <context-dir> <registry/image>}"
TAG="${3:-latest}"

echo "=== Building image from ${CONTEXT_DIR} ==="
docker build \
    --platform linux/amd64 \
    --no-cache \
    -t "${REGISTRY_IMAGE}:${TAG}" \
    "${CONTEXT_DIR}"

echo "=== Pushing to ${REGISTRY_IMAGE}:${TAG} ==="
docker push "${REGISTRY_IMAGE}:${TAG}"

echo "=== Extracting digest ==="
DIGEST=$(docker inspect --format='{{index .RepoDigests 0}}' "${REGISTRY_IMAGE}:${TAG}" | cut -d@ -f2)

echo ""
echo "=== Update MODULE.bazel with this digest ==="
echo ""
echo "oci.pull("
echo "    name = \"$(basename "${REGISTRY_IMAGE}" | tr '-' '_')\","
echo "    digest = \"${DIGEST}\","
echo "    image = \"${REGISTRY_IMAGE}\","
echo "    platforms = [\"linux/amd64\"],"
echo "    tag = \"${TAG}\","
echo ")"
echo ""
echo "Digest: ${DIGEST}"
