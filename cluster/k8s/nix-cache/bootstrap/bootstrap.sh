#!/bin/sh
# Idempotently ensure required Attic caches exist.
#
# Mints an ephemeral admin JWT (5-minute validity) signed with the same
# HS256 secret the attic server uses (mounted via env var
# ATTIC_SERVER_TOKEN_HS256_SECRET_BASE64), logs in to the in-cluster attic
# server, then for each cache: skips if already present, otherwise
# `attic cache create`.
#
# Public keys are NOT extracted by this script — fetch them from the
# unauthenticated endpoint after the cache exists:
#   curl https://cache.allegedly.works/<cache>/nix-cache-info
# Paste the resulting `Trusted-Public-Key:` value into
# nix/nixos/modules/attic-substituter.nix `trusted-public-keys`.
#
# TODO: nice-to-have — auto-fetch the pubkey post-creation and push it
# back into nix/nixos/modules/attic-substituter.nix via the
# github-secrets-sync-pat PAT (same mechanism the rotator uses for SOPS
# files). Today we just paste it once per cluster lifetime; the pubkey
# only changes on full cluster rebuild, so the manual step is rare.
#
# To re-run after editing this script, the
# `kustomize.toolkit.fluxcd.io/force: enabled` annotation on the Job tells
# Flux to delete-and-recreate it on next reconcile.

set -eu

SERVER="${ATTIC_SERVER_URL:-http://attic.nix-cache.svc.cluster.local:8080}"
# Space-separated list of caches to ensure exist (POSIX sh — busybox in
# the upstream attic image has no bash, hence no arrays).
CACHES="gaffer"

echo "[bootstrap] minting 5-minute admin JWT..."
ADMIN_JWT=$(atticadm make-token \
  --sub bootstrap-admin \
  --validity '5 minutes' \
  --pull '*' --push '*' --create-cache '*')

echo "[bootstrap] logging in to $SERVER..."
attic login bootstrap "$SERVER" "$ADMIN_JWT"

for CACHE in $CACHES; do
  if attic cache info "$CACHE" >/dev/null 2>&1; then
    echo "[bootstrap] cache $CACHE: already exists"
  else
    echo "[bootstrap] cache $CACHE: creating"
    attic cache create "$CACHE"
  fi
  echo "[bootstrap] cache $CACHE: info:"
  attic cache info "$CACHE"
done

echo "[bootstrap] done."
