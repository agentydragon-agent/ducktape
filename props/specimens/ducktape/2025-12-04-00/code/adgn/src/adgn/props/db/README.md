# Properties Evaluation Database

PostgreSQL-based storage for properties evaluation results.

## Database Separation: Production vs Test

We maintain **TWO separate databases** to ensure tests never affect production data:

### Production Database: `eval_results`
- **Purpose**: Real evaluation results, persistent storage
- **DO NOT DROP/RECREATE**: Contains valuable data
- **Admin access**: `PROPS_DB_URL`
- **Agent access**: `PROPS_AGENT_DB_URL`

```bash
export PROPS_DB_URL='postgresql://admin_user:admin_password_changeme@localhost:5433/eval_results'
export PROPS_AGENT_DB_URL='postgresql://agent_user:agent_password_changeme@localhost:5433/eval_results'
```

### Test Database: `eval_results_test`
- **Purpose**: Integration tests only
- **FREELY DROP/RECREATE**: Tests use drop_tables() in fixture
- **Admin access**: `PROPS_TEST_DB_URL`
- **Agent access**: `PROPS_TEST_AGENT_DB_URL`

```bash
export PROPS_TEST_DB_URL='postgresql://admin_user:admin_password_changeme@localhost:5433/eval_results_test'
export PROPS_TEST_AGENT_DB_URL='postgresql://agent_user:agent_password_changeme@localhost:5433/eval_results_test'
```

## Setup

1. **Start PostgreSQL container**:
   ```bash
   cd src/adgn/props
   docker compose up -d
   ```

2. **Create databases and users**:
   ```bash
   ./db/init_db.sh
   ```

   This creates:
   - Both databases (eval_results, eval_results_test)
   - Both users (admin_user, agent_user)
   - Grants appropriate permissions

3. **Initialize database schema**:
   ```bash
   # Set environment variable for production database
   export PROPS_DB_URL='postgresql://admin_user:admin_password_changeme@localhost:5433/eval_results'

   # Initialize tables, RLS policies, and sync specimens
   adgn-properties sync
   ```

   To drop and recreate everything (includes specimen sync, destructive):
   ```bash
   PROPS_DB_URL='postgresql://postgres:postgres@localhost:5433/eval_results' \
     adgn-properties db-recreate --yes
   ```

## Database Users

### admin_user
- **Full access**: Create/drop tables, write data, read all data
- **Purpose**: Migrations, data loading, test setup
- **Bypasses RLS**: Can see all splits (train/valid/test)

### agent_user
- **Read-only**: SELECT only (no INSERT/UPDATE/DELETE)
- **RLS-restricted**: Can only see train/valid splits (NOT test)
- **Purpose**: LLM agent queries during prompt optimization

## Running Tests

```bash
# Set test database URLs
export PROPS_TEST_DB_URL='postgresql://admin_user:admin_password_changeme@localhost:5433/eval_results_test'
export PROPS_TEST_AGENT_DB_URL='postgresql://agent_user:agent_password_changeme@localhost:5433/eval_results_test'

# Run integration tests (these will drop/recreate tables in test database)
pytest tests/props/db/test_db_integration.py -v
```

**Important**: Tests use `drop_tables()` + `create_tables()` in the fixture, which **only affects eval_results_test**. Production data is never touched.
