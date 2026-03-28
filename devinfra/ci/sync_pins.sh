#!/usr/bin/env bash
# Sync npins/sources.json with the latest GitHub Release for each package.
#
# For each pinned package, finds the latest release tag, compares the URL
# against the current pin, and updates if stale. Produces at most one commit
# regardless of how many packages changed.
#
# Expects: Nix with flakes enabled, gh CLI authenticated.
set -euo pipefail

REPO="agentydragon/ducktape"
BASE="https://github.com/$REPO/releases/download"

# Package → artifact filename (tag is <pkg>-<sha>, discovered dynamically).
declare -A artifacts=(
  ["claude-hooks"]="claude_hooks-0.1.0-py3-none-any.whl"
  ["ducktape"]="ducktape-0.1.0-py3-none-any.whl"
  ["gterm-theme"]="gterm_theme-0.1.0-py3-none-any.whl"
  ["bbapi"]="bbapi"
  ["skills"]="skills.tar"
)

# Fetch all recent release tags once (avoids per-package API calls).
all_tags=$(gh release list --limit 200 --json tagName --jq '.[].tagName' \
  --exclude-drafts --exclude-pre-releases -R "$REPO")

updated=()

for pkg in "${!artifacts[@]}"; do
  artifact="${artifacts[$pkg]}"

  # Find the latest release tag for this package (tags are sorted newest-first).
  tag=$(echo "$all_tags" | grep "^${pkg}-" | head -1 || true)

  if [[ -z "$tag" ]]; then
    echo "$pkg: no release found, skipping"
    continue
  fi

  url="$BASE/$tag/$artifact"
  current_url=$(jq -r ".pins[\"$pkg\"].url" npins/sources.json)

  if [[ "$url" == "$current_url" ]]; then
    echo "$pkg: up to date ($tag)"
    continue
  fi

  echo "$pkg: updating to $tag"
  fetch=$(jq -r ".pins[\"$pkg\"].fetch" npins/sources.json)
  if [[ "$fetch" == "unpack" ]]; then
    hash=$(nix-prefetch-url --unpack "$url" 2>/dev/null)
  else
    hash=$(nix-prefetch-url "$url" 2>/dev/null)
  fi
  sri=$(nix hash convert --to sri "sha256:$hash")
  jq --arg url "$url" --arg hash "$sri" \
    ".pins[\"$pkg\"].url = \$url | .pins[\"$pkg\"].hash = \$hash" \
    npins/sources.json >npins/sources.json.tmp && mv npins/sources.json.tmp npins/sources.json
  echo "$pkg: $sri"
  updated+=("$pkg")
done

if [[ ${#updated[@]} -eq 0 ]]; then
  echo "All pins up to date"
else
  echo "Updated: ${updated[*]}"
fi
