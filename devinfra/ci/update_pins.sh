#!/usr/bin/env bash
# Update artifact pins in npins/sources.json and push Nix packages to attic.
#
# Usage: update_pins.sh <short_sha> <changed_pkgs...>
# Expects: ATTIC_TOKEN env var, Nix with flakes enabled.
set -euo pipefail

SHA="$1"
shift
BASE="https://github.com/agentydragon/ducktape/releases/download"

declare -A urls=(
  ["claude-hooks"]="$BASE/claude-hooks-$SHA/claude_hooks-0.1.0-py3-none-any.whl"
  ["ducktape"]="$BASE/ducktape-$SHA/ducktape-0.1.0-py3-none-any.whl"
  ["gterm-theme"]="$BASE/gterm-theme-$SHA/gterm_theme-0.1.0-py3-none-any.whl"
  ["bbapi"]="$BASE/bbapi-$SHA/bbapi"
  ["skills"]="$BASE/skills-$SHA/skills.tar"
)

store_paths=()
for pkg in "$@"; do
  url="${urls[$pkg]}"
  fetch=$(jq -r ".pins[\"$pkg\"].fetch" npins/sources.json)
  if [ "$fetch" = "unpack" ]; then
    hash=$(nix-prefetch-url --unpack "$url" 2>/dev/null)
  else
    hash=$(nix-prefetch-url "$url" 2>/dev/null)
  fi
  sri=$(nix hash convert --to sri "sha256:$hash")
  jq --arg url "$url" --arg hash "$sri" \
    ".pins[\"$pkg\"].url = \$url | .pins[\"$pkg\"].hash = \$hash" \
    npins/sources.json >npins/sources.json.tmp && mv npins/sources.json.tmp npins/sources.json
  echo "$pkg: $sri"
  store_paths+=($(nix build --no-link --print-out-paths ".#packages.x86_64-linux.$pkg"))
done

# web-session bundles claude-hooks + bbapi + gh; push so web_setup.sh is a cache hit.
store_paths+=($(nix build --no-link --print-out-paths ".#packages.x86_64-linux.web-session"))

attic login main https://cache.allegedly.works "$ATTIC_TOKEN"
attic push main "${store_paths[@]}"
