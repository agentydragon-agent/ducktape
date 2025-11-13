#!/bin/sh
set -e

echo "Installing required packages..."
apt-get update && apt-get install -y postgresql-client curl

echo "=========================================="
echo "STEP 1: Setting Harbor admin password"
echo "=========================================="

# Check if admin user exists
ADMIN_EXISTS=$(psql -h harbor-database -U postgres -d registry -t -c "SELECT COUNT(*) FROM harbor_user WHERE username = 'admin';" | xargs)

if [ "$ADMIN_EXISTS" -eq 0 ]; then
  echo "Admin user doesn't exist yet, Harbor will create it with our password"
else
  # Get existing salt or generate new one
  EXISTING_SALT=$(psql -h harbor-database -U postgres -d registry -t -c "SELECT salt FROM harbor_user WHERE username = 'admin';" | xargs)
  
  if [ -z "$EXISTING_SALT" ]; then
    SALT=$(head -c 24 /dev/urandom | base64 | tr -d '/+' | cut -c1-32)
    echo "Generated new salt"
  else
    SALT="$EXISTING_SALT"
    echo "Using existing salt"
  fi
  
  # Calculate PBKDF2-SHA256 hash (Harbor's algorithm)
  SALTED_HASH=$(python3 -c 'import hashlib; import binascii; salt="'"$SALT"'"; password="'"$HARBOR_ADMIN_PASSWORD"'"; hash_bytes=hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 4096, 16); print(binascii.hexlify(hash_bytes).decode())')
  
  # Update admin password in database
  psql -h harbor-database -U postgres -d registry -c "
    UPDATE harbor_user 
    SET password = '$SALTED_HASH', salt = '$SALT', password_version = 'sha256'
    WHERE username = 'admin';
  "
  echo "✅ Admin password updated in database"
fi

echo "=========================================="
echo "STEP 2: Waiting for Harbor API to be ready"
echo "=========================================="

for i in $(seq 1 60); do
  if curl -f -s http://harbor-core:80/api/v2.0/ping >/dev/null; then
    echo "✅ Harbor API is ready"
    break
  fi
  echo "Waiting for Harbor API... ($i/60)"
  sleep 5
done

echo "=========================================="
echo "STEP 3: Verifying admin authentication"
echo "=========================================="

if curl -u admin:${HARBOR_ADMIN_PASSWORD} -f -s http://harbor-core:80/api/v2.0/users/current >/dev/null; then
  echo "✅ Admin authentication successful"
else
  echo "❌ Admin authentication failed!"
  echo "Debugging info:"
  psql -h harbor-database -U postgres -d registry -c "SELECT username, LENGTH(password) as pwd_len, LENGTH(salt) as salt_len, password_version FROM harbor_user WHERE username = 'admin';"
  exit 1
fi

echo "=========================================="
echo "STEP 4: Configuring Harbor OIDC settings"
echo "=========================================="

echo "Updating OIDC configuration via API..."
if curl -X PUT \
  -H "Content-Type: application/json" \
  -u admin:${HARBOR_ADMIN_PASSWORD} \
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
  --fail-with-body \
  http://harbor-core:80/api/v2.0/configurations; then
  echo "✅ OIDC configuration updated successfully"
else
  echo "❌ Failed to update OIDC configuration"
  exit 1
fi

echo "=========================================="
echo "STEP 5: Verifying OIDC configuration"
echo "=========================================="

# Verify the configuration was applied
CURRENT_MODE=$(curl -s -u admin:${HARBOR_ADMIN_PASSWORD} http://harbor-core:80/api/v2.0/configurations | python3 -c "import sys, json; print(json.load(sys.stdin).get('auth_mode', {}).get('value', 'unknown'))")

if [ "$CURRENT_MODE" = "oidc_auth" ]; then
  echo "✅ OIDC authentication mode is active"
else
  echo "❌ Authentication mode is '$CURRENT_MODE', expected 'oidc_auth'"
  exit 1
fi

# Check database to ensure secret was stored (encrypted)
STORED_SECRET=$(psql -h harbor-database -U postgres -d registry -t -c "SELECT v FROM properties WHERE k = 'oidc_client_secret';" | xargs)
if [ -n "$STORED_SECRET" ]; then
  echo "✅ OIDC client secret is stored in database"
  if echo "$STORED_SECRET" | grep -q "^<enc-v1>"; then
    echo "✅ Secret is properly encrypted"
  else
    echo "⚠️  Warning: Secret may not be encrypted"
  fi
else
  echo "❌ OIDC client secret not found in database"
  exit 1
fi

echo "=========================================="
echo "✅ Harbor configuration completed successfully!"
echo "=========================================="