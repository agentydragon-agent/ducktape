#!/usr/bin/env bash
# Extract and prepare kernel modules from an Alpine linux-virt .apk.
# Gunzips .ko.gz modules, fixes dependency files, and repacks as a tar.
# Usage: extract_modules.sh <apk-file> <output-tar>
set -euo pipefail

APK="$1"
OUTPUT="$2"

TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

tar --warning=no-unknown-keyword -xzf "$APK" -C "$TMPDIR" lib/modules/

find "$TMPDIR/lib/modules/" -name '*.ko.gz' -exec gunzip {} \;
find "$TMPDIR/lib/modules/" -name 'modules.dep' -exec sed -i 's/\.ko\.gz/.ko/g' {} \;
find "$TMPDIR/lib/modules/" -name 'modules.alias' -exec sed -i 's/\.ko\.gz/.ko/g' {} \;
find "$TMPDIR/lib/modules/" -name '*.bin' -delete

tar -cf "$OUTPUT" -C "$TMPDIR" lib/modules/
