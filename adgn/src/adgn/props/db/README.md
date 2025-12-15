# Properties Evaluation Database

PostgreSQL-based storage for properties evaluation results.

## Database Separation: Production vs Test

We maintain **TWO separate databases** to ensure tests never affect production data:

### Production Database: `eval_results`
- **Purpose**: Real evaluation results, persistent storage
- **DO NOT DROP/RECREATE**: Contains valuable data
- **Connection**: Uses individual environment variables for database configuration

### Test Database: `eval_results_test`
- **Purpose**: Integration tests only
- **FREELY DROP/RECREATE**: Tests use drop_tables() in fixture
- **Connection**: Uses individual environment variables for test database configuration

## Setup

1. **Start PostgreSQL container**:
   ```bash
   cd adgn
   devenv up
   ```

   This starts the PostgreSQL container in the background (managed by devenv).

2. **Initialize database**:
   ```bash
   # Create database, schema, RLS policies, and sync specimens
   adgn-properties db recreate --yes
   ```

   This automatically:
   - Creates the `eval_results` database
   - Runs Alembic migrations to create schema
   - Applies RLS policies (temporary agent users created on-demand per task)
   - Syncs specimen data from the specimens repository

   For incremental updates (without dropping tables):
   ```bash
   adgn-properties sync
   ```

## Database Users

### postgres (admin)
- **Full access**: Create/drop tables, write data, read all data
- **Purpose**: Migrations, data loading, test setup
- **Bypasses RLS**: Can see all splits (train/valid/test)
- **Connection**: Via PGUSER/PGPASSWORD environment variables

### Temporary Agent Users (per-task)
- **Read-only**: SELECT only (no INSERT/UPDATE/DELETE)
- **RLS-restricted**: Task-specific data isolation (e.g., TRAIN-only for prompt optimizer)
- **Purpose**: Enforce data isolation for agent tasks (prevents overfitting to validation data)
- **Lifecycle**: Created on-demand, automatically cleaned up on task completion
- **Examples**: `prompt_optimizer_agent_{uuid}`, `clustering_agent_{uuid}`
- **Implementation**: See `TempUserManager` subclasses in `db/temp_user_manager.py`

## Running Tests

```bash
# Run integration tests (these will drop/recreate tables in test database)
pytest tests/props/db/test_db_integration.py -v
```

**Important**: Tests use `drop_tables()` + `create_tables()` in the fixture, which **only affects eval_results_test**. Production data is never touched.
