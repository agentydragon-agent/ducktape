-- Privileges for the `api` schema that PostgREST serves (its views are created by
-- finance/plaid/db/migrations/versions/0006_api_schema.py) and for the role it connects as.
-- CNPG declares the roles and their memberships (Cluster.spec.managed.roles) but no object
-- privileges, hence this script. Everything here runs as the database owner, like the migration.
--
-- Callers do not get grants of their own: each is a member of plaid_api_reader, so a new caller is
-- one more managed role and no SQL.
--
-- The schema is created here too, as the migration does, so the order of the two does not matter:
-- the GRANT covers views that exist by now and the default privileges cover any created later.
CREATE SCHEMA IF NOT EXISTS api;
GRANT USAGE ON SCHEMA api TO plaid_api_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA api TO plaid_api_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA api GRANT SELECT ON TABLES TO plaid_api_reader;
GRANT CONNECT ON DATABASE plaidmcp TO plaid_postgrest;
