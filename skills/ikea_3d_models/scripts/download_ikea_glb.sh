#!/usr/bin/env bash
# Download an IKEA product's 3D model (GLB) by item number. No cookies needed.
#
# Usage: download_ikea_glb.sh <itemNumber> [out.glb] [market] [lang]
#   itemNumber  8-digit IKEA item number (from search_ikea.py)
#   out.glb     output path (default: <itemNumber>.glb)
#   market/lang locale segment of the URL (default: us / en)
#
# The "rotera" static model URL is fully public -- the only IKEA endpoint that
# needs a session cookie is the metadata JSON, which this skill does not use
# (dimensions come from search_ikea.py or the model's own bounding box).
set -euo pipefail

ITEM="${1:?usage: download_ikea_glb.sh <itemNumber> [out.glb] [market] [lang]}"
OUT="${2:-${ITEM}.glb}"
MARKET="${3:-us}"
LANG="${4:-en}"

URL="https://web-api.ikea.com/${MARKET}/${LANG}/rotera/static/models/${ITEM}-mini.glb"

code=$(curl -s -o /dev/null -w '%{http_code}' "$URL")
if [ "$code" != "200" ]; then
  echo "no 3D model for item $ITEM (HTTP $code at $URL)" >&2
  echo "  404 = discontinued or never scanned; try another color variant" >&2
  exit 1
fi

curl -fSL -o "$OUT" "$URL"
echo "$OUT"
