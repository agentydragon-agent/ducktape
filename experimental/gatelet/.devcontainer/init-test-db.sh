#!/bin/bash
set -e

# Create the test database
echo "Creating test database: $POSTGRES_TEST_DB"
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE DATABASE $POSTGRES_TEST_DB;
    GRANT ALL PRIVILEGES ON DATABASE $POSTGRES_TEST_DB TO $POSTGRES_USER;
EOSQL

echo "Test database $POSTGRES_TEST_DB created successfully"