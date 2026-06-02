#!/bin/sh
# Ensure the Forgejo `props` service user exists with the SOPS-managed password.
# The props backend's registry proxy authenticates as this user to push/pull the
# agent images under git.allegedly.works/props/*. Idempotent (safe to re-run).
set -eu
API="http://forgejo-http.forgejo.svc:3000/api/v1"

body="{\"username\":\"props\",\"email\":\"props@allegedly.works\",\"password\":\"${PROPS_PASSWORD}\",\"must_change_password\":false,\"visibility\":\"private\"}"
code=$(curl -sS -o /tmp/resp -w '%{http_code}' -X POST "${API}/admin/users" \
  -u "${ADMIN_USERNAME}:${ADMIN_PASSWORD}" -H 'Content-Type: application/json' -d "${body}")

case "${code}" in
  201)
    echo "created Forgejo user 'props'"
    ;;
  422 | 409)
    echo "Forgejo user 'props' already exists; syncing password"
    curl -sS -f -X PATCH "${API}/admin/users/props" \
      -u "${ADMIN_USERNAME}:${ADMIN_PASSWORD}" -H 'Content-Type: application/json' \
      -d "{\"login_name\":\"props\",\"source_id\":0,\"password\":\"${PROPS_PASSWORD}\",\"must_change_password\":false}"
    echo "password synced"
    ;;
  *)
    echo "unexpected HTTP ${code} creating user:"
    cat /tmp/resp
    exit 1
    ;;
esac
