#!/usr/bin/env bash
# Build a reproducible Talos nocloud disk image via the official imager container.
# Usage: build_talos_image.sh <imager-tarball> <profile-yaml> <output-qcow2>
set -euo pipefail

TARBALL="$1"
PROFILE="$2"
OUTPUT="$3"

# Load the pinned imager image into Docker.
docker load -i "$TARBALL" >&2

# Build the disk image. Capture output to a log — only show on failure.
# SOURCE_DATE_EPOCH + DETERMINISTIC_SEED ensure byte-identical output.
TALOS_OUT=$(mktemp -d)
LOG=$(mktemp)
trap 'rm -rf "$TALOS_OUT" "$LOG"' EXIT

if ! docker run --rm \
  -e SOURCE_DATE_EPOCH=1700000000 \
  -e DETERMINISTIC_SEED=1 \
  -v "$TALOS_OUT:/out" \
  -i siderolabs/imager:build \
  - <"$PROFILE" >"$LOG" 2>&1; then
  cat "$LOG" >&2
  exit 1
fi

mv "$TALOS_OUT/nocloud-amd64.qcow2" "$OUTPUT"
