#!/usr/bin/env bash
# BB Release step: build dist, create GitHub releases for changed artifacts,
# dispatch GHA release.yml to update pins.
#
# Expects: GH_RELEASE_PAT env var, bazel-bin/ populated by prior build step.
set -euo pipefail

export GH_TOKEN="$GH_RELEASE_PAT"
mkdir -p dist
cp bazel-bin/claude_hooks-*.whl dist/
cp bazel-bin/ducktape-*.whl dist/
cp bazel-bin/gterm_theme/gterm_theme-*.whl dist/
cp bazel-bin/skills/all_skills_tar.tar dist/skills.tar
cp bazel-bin/devinfra/buildbuddy_cli/bbapi_/bbapi dist/

SHORT_SHA=$(git rev-parse --short HEAD)

# SRI hash of a file, matching the format sources.json stores.
sri_hash() { echo "sha256-$(openssl dgst -sha256 -binary "$1" | base64 | tr -d '\n')"; }

# Hash currently pinned in sources.json for a package (empty if absent).
pinned_hash() { python3 -c "import json,sys;d=json.load(open('npins/sources.json'));print(d.get('pins',{}).get(sys.argv[1],{}).get('hash',''))" "$1"; }

changed=()

# Create a release only when the built artifact differs from the current pin.
maybe_release() {
  local pkg="$1" tag="$2" title="$3" body="$4" file="$5"
  local new_hash old_hash
  new_hash=$(sri_hash "$file")
  old_hash=$(pinned_hash "$pkg")
  if [ "$new_hash" = "$old_hash" ]; then
    echo "$pkg: unchanged, skipping"
    return
  fi
  echo "$pkg: content changed, creating release $tag"
  gh release create "$tag" --title "$title" --notes "$body" --latest=false "$file"
  changed+=("$pkg")
}

maybe_release "claude-hooks" "claude-hooks-$SHORT_SHA" \
  "claude-hooks ($SHORT_SHA)" "claude-hooks wheel for Claude Code integration." \
  dist/claude_hooks-*.whl
maybe_release "ducktape" "ducktape-$SHORT_SHA" \
  "ducktape ($SHORT_SHA)" "ducktape wheel containing CLI tools." \
  dist/ducktape-*.whl
maybe_release "gterm-theme" "gterm-theme-$SHORT_SHA" \
  "gterm-theme ($SHORT_SHA)" "gterm-theme wheel (GNOME Terminal theme follower)." \
  dist/gterm_theme-*.whl
maybe_release "skills" "skills-$SHORT_SHA" \
  "skills ($SHORT_SHA)" "Skills tarball for AI agent deployment." \
  dist/skills.tar
maybe_release "bbapi" "bbapi-$SHORT_SHA" \
  "bbapi ($SHORT_SHA)" "bbapi — BuildBuddy API CLI (Linux x86_64)." \
  dist/bbapi

if [ ${#changed[@]} -eq 0 ]; then
  echo "No artifacts changed, skipping release"
  exit 0
fi

BRANCH=$(git rev-parse --abbrev-ref HEAD)
gh workflow run release.yml \
  --ref "$BRANCH" \
  --field short_sha="$SHORT_SHA" \
  --field "changed=${changed[*]}"
