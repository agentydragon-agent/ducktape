#!/usr/bin/env bash
# Convert a (Draco-compressed) glb into a binary STL mesh.
#
# Usage: glb_to_stl.sh <input.glb> [out.stl] [obj_name]
#   input.glb   the downloaded IKEA model (Draco-compressed)
#   out.stl     output path (default: input with .glb -> .stl)
#   obj_name    name written into the STL header (default: basename)
#
# Import the STL into FreeCAD (File -> Import) or any mesh tool yourself.
#
# Two steps, because IKEA GLBs use KHR_draco_mesh_compression and the STL
# writer reads only uncompressed buffers:
#   1. decode Draco -> plain glb   (gltf-transform, a JS tool)
#   2. parse + scale m->mm -> STL  (glb_to_stl.py, pure Python 3, stdlib only)
set -euo pipefail

IN="${1:?usage: glb_to_stl.sh <input.glb> [out.stl] [obj_name]}"
OUT="${2:-${IN%.glb}.stl}"
OBJ_NAME="${3:-$(basename "${OUT%.stl}")}"
HERE="$(cd "$(dirname "$0")" && pwd)"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
DEC="$TMP/decoded.glb"

# Step 1: decode Draco. Prefer a globally installed gltf-transform; fall back to
# npx, then pnpm dlx. `copy` round-trips the document, decoding Draco on read
# and writing an uncompressed glb (it does not re-apply compression).
decode() {
  if command -v gltf-transform >/dev/null 2>&1; then
    gltf-transform copy "$1" "$2"
  elif command -v npx >/dev/null 2>&1 && npx --version >/dev/null 2>&1; then
    npx -y @gltf-transform/cli copy "$1" "$2"
  else
    pnpm dlx @gltf-transform/cli copy "$1" "$2"
  fi
}
decode "$IN" "$DEC"

# Step 2: build the STL.
GLB_IN="$DEC" STL_OUT="$OUT" OBJ_NAME="$OBJ_NAME" \
  python3 "$HERE/glb_to_stl.py"

echo "wrote $OUT"
