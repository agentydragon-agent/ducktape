#!/usr/bin/env bash
# Clone agentydragon/crush at a specific commit and checkout detached HEAD
# Usage: ./clone_crush_at_commit.sh [DEST_DIR]
# Env overrides: REPO_URL, COMMIT_SHA
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/agentydragon/crush.git}"
COMMIT_SHA="${COMMIT_SHA:-a2a1ffa00943aa373f688ac05b667083ac3230b1}"
DEST_DIR="${1:-./work/crush-${COMMIT_SHA}}"

# Ensure destination directory is suitable
if [[ -e "${DEST_DIR}" ]]; then
  if [[ -d "${DEST_DIR}" && -z "$(ls -A "${DEST_DIR}" 2>/dev/null || true)" ]]; then
    : # empty directory is fine
  else
    echo "Destination '${DEST_DIR}' exists and is not an empty directory; aborting." >&2
    exit 1
  fi
fi

# Efficient clone then fetch the exact commit
# --no-checkout avoids checking out default branch; --filter=blob:none keeps it fast
git clone --no-checkout --filter=blob:none "${REPO_URL}" "${DEST_DIR}"
cd "${DEST_DIR}"
# Fetch the specific commit in case it's not on the default branch tip
git fetch origin "${COMMIT_SHA}" --depth=1
# Checkout the exact commit (detached HEAD)
git checkout --detach "${COMMIT_SHA}"
# Initialize submodules if present (best-effort shallow)
if [[ -f .gitmodules ]]; then
  git submodule update --init --recursive --depth=1 || true
fi

echo "Checked out ${REPO_URL}@${COMMIT_SHA} into ${DEST_DIR}"