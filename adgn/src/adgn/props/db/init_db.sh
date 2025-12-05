#!/bin/bash
# Setup script for properties evaluation PostgreSQL databases
#
# Creates TWO separate databases:
# - eval_results: Production database (DO NOT DROP/RECREATE)
# - eval_results_test: Test database (tests can freely drop/recreate)
#
# Creates database users and grants necessary permissions.
# Run this after starting the postgres container via docker-compose.
#
# Usage: ./init_db.sh

set -e

CONTAINER="props-postgres"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Setting up production and test databases..."

# Create databases (ignore errors if they already exist)
docker exec "$CONTAINER" createdb -U postgres eval_results 2>/dev/null || echo "Database eval_results already exists"
docker exec "$CONTAINER" createdb -U postgres eval_results_test 2>/dev/null || echo "Database eval_results_test already exists"

# Create users
echo ""
echo "Creating database users..."
docker exec -i "$CONTAINER" psql -U postgres < "$SCRIPT_DIR/create_users.sql"

# Setup production database
echo ""
echo "Setting up PRODUCTION database (eval_results)..."
docker exec -i "$CONTAINER" psql -U postgres -d eval_results \
    -v dbname=eval_results < "$SCRIPT_DIR/grant_permissions.sql"

# Setup test database
echo ""
echo "Setting up TEST database (eval_results_test)..."
docker exec -i "$CONTAINER" psql -U postgres -d eval_results_test \
    -v dbname=eval_results_test < "$SCRIPT_DIR/grant_permissions.sql"

cat <<'EOF'

✓ Database setup complete!

=== PRODUCTION DATABASE ===
Database: eval_results
Host:     localhost:5433
Admin:    postgres / props_admin_pass
Agent:    agent_user / agent_password_changeme

=== TEST DATABASE ===
Database: eval_results_test
Host:     localhost:5433
Admin:    postgres / props_admin_pass
Agent:    agent_user / agent_password_changeme

NOTE: When using devenv shell, these environment variables are automatically set:
  PROPS_DB_HOST=localhost
  PROPS_DB_PORT=5433
  PROPS_DB_ADMIN_USER=postgres
  PROPS_DB_ADMIN_PASSWORD=props_admin_pass
  PROPS_DB_AGENT_USER=agent_user
  PROPS_DB_AGENT_PASSWORD=agent_password_changeme
  PROPS_DB_NAME=eval_results

Tests construct their own DatabaseConfig with per-test database names.

EOF
