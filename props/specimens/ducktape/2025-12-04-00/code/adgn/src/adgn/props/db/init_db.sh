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
Admin:    postgresql://admin_user:admin_password_changeme@localhost:5433/eval_results
Agent:    postgresql://agent_user:agent_password_changeme@localhost:5433/eval_results

=== TEST DATABASE ===
Database: eval_results_test
Admin:    postgresql://admin_user:admin_password_changeme@localhost:5433/eval_results_test
Agent:    postgresql://agent_user:agent_password_changeme@localhost:5433/eval_results_test

Environment variables for tests:
export PROPS_TEST_DB_URL='postgresql://admin_user:admin_password_changeme@localhost:5433/eval_results_test'
export PROPS_TEST_AGENT_DB_URL='postgresql://agent_user:agent_password_changeme@localhost:5433/eval_results_test'

Environment variables for production:
export PROPS_DB_URL='postgresql://admin_user:admin_password_changeme@localhost:5433/eval_results'
export PROPS_AGENT_DB_URL='postgresql://agent_user:agent_password_changeme@localhost:5433/eval_results'

EOF
