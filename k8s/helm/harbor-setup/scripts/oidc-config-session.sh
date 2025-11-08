#!/bin/bash
set -e

echo "Harbor OIDC Configuration Script with Session-based Authentication"
echo "=================================================================="

echo "Waiting for Harbor to be ready..."

# Wait for Harbor core to be ready
for i in $(seq 1 60); do
  if curl -f -s http://harbor-core:80/api/v2.0/ping >/dev/null; then
    echo "Harbor is ready"
    break
  fi
  echo "Waiting for Harbor... ($i/60)"
  sleep 10
done

echo "Getting CSRF token from Harbor..."

# First, get CSRF token by making a GET request
COOKIE_JAR=$(mktemp)
HEADERS_FILE=$(mktemp)

curl -X GET \
  -c "$COOKIE_JAR" \
  -D "$HEADERS_FILE" \
  -s \
  http://harbor-core:80/c/login >/dev/null

CSRF_TOKEN=$(grep -i "X-Harbor-CSRF-Token" "$HEADERS_FILE" | cut -d: -f2 | tr -d ' \r\n' || true)

echo "CSRF token obtained: ${CSRF_TOKEN:0:10}..."

if [ -z "$CSRF_TOKEN" ]; then
  echo "Failed to get CSRF token"
  exit 1
fi

echo "Logging into Harbor with CSRF token..."

# Login to Harbor to create session (required for system-level API access)
LOGIN_RESPONSE=$(curl -X POST \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -H "X-Harbor-CSRF-Token: $CSRF_TOKEN" \
  -d "principal=admin&password=${HARBOR_ADMIN_PASSWORD}" \
  -b "$COOKIE_JAR" \
  -c "$COOKIE_JAR" \
  -w "%{http_code}" \
  -s \
  http://harbor-core:80/c/login)

echo "Login response code: $LOGIN_RESPONSE"

if [ "$LOGIN_RESPONSE" != "200" ]; then
  echo "Login failed with status: $LOGIN_RESPONSE"
  exit 1
fi

echo "Login successful, cookie saved. Configuring Harbor OIDC settings with session authentication..."

# Configure OIDC settings using session cookie (provides proper RBAC authorization)
CONFIG_RESPONSE=$(curl -X PUT -H "Content-Type: application/json" \
  -b "$COOKIE_JAR" \
  -w "%{http_code}" \
  -s \
  -d '{
    "auth_mode": "oidc_auth",
    "oidc_name": "Authentik",
    "oidc_endpoint": "https://auth.k3s.agentydragon.com/application/o/harbor/",
    "oidc_client_id": "harbor",
    "oidc_client_secret": "'$HARBOR_CLIENT_SECRET'",
    "oidc_groups_claim": "groups",
    "oidc_admin_group": "harbor-admins",
    "oidc_scope": "openid,profile,email,groups",
    "oidc_user_claim": "preferred_username",
    "oidc_verify_cert": true,
    "oidc_auto_onboard": true
  }' \
  http://harbor-core:80/api/v2.0/configurations)

echo "Configuration response code: $CONFIG_RESPONSE"

if [ "$CONFIG_RESPONSE" = "200" ]; then
  echo "Harbor OIDC configuration completed successfully!"
else
  echo "Configuration failed with status: $CONFIG_RESPONSE"
  exit 1
fi

# Cleanup
rm -f "$COOKIE_JAR" "$HEADERS_FILE"