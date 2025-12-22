# Agent Infrastructure Tables

Shared tables used by all agent types.

## agent_runs

!psql -c "\d+ agent_runs"

## events

!psql -c "\d+ events"

## RLS Context

All agents use `current_agent_run_id()` to get their run ID:

```sql
SELECT current_agent_run_id();  -- Returns UUID from username
```

RLS policies filter writes by this function. See `docs/rls_mechanism.md` for details.
