#!/usr/bin/env bash
# Build a Talos nocloud disk image with Nebula extension via the official imager.
# Uses --network=host so the imager can pull the Nebula extension from ghcr.io.
# Usage: build_talos_nebula_image.sh <imager-tarball> <profile-yaml> <output-qcow2>
set -euo pipefail

TARBALL="$1"
PROFILE="$2"
OUTPUT="$3"

docker load -i "$TARBALL" >&2

TALOS_OUT=$(mktemp -d)
LOG=$(mktemp)
trap 'rm -rf "$TALOS_OUT" "$LOG"' EXIT

if ! docker run --rm \
  --network=host \
  -e SOURCE_DATE_EPOCH=1700000000 \
  -e DETERMINISTIC_SEED=1 \
  -v "$TALOS_OUT:/out" \
  -i siderolabs/imager:build \
  - <"$PROFILE" >"$LOG" 2>&1; then
  cat "$LOG" >&2
  exit 1
fi

mv "$TALOS_OUT/nocloud-amd64.qcow2" "$OUTPUT"
