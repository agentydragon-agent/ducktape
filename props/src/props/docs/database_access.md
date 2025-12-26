# Database and File System Access

Your container has direct PostgreSQL access via environment variables, scoped by Row-Level Security.

## Source Code Access

Init scripts typically fetch snapshots using `props snapshot fetch <slug>`, placing them at `/snapshots/{slug}/`.

Example:
```bash
ls /snapshots/ducktape/2025-11-26-00/    # List files in a snapshot
cat /snapshots/test-fixtures/test-trivial/add.py   # Read a file
```

Check your init output for which snapshots were fetched and their paths.

## Connection

Standard PostgreSQL environment variables are set:
- `PGHOST`, `PGPORT`, `PGDATABASE` — Connection details
- `PGUSER` — Your temporary username (pattern: `agent_{run_id}`)
- `PGPASSWORD` — Your temporary password

Connect with psql (uses PG* vars automatically):
```bash
psql -c "SELECT current_agent_run_id()"
```

Python:
```python
import os, psycopg2
conn = psycopg2.connect(
    host=os.environ["PGHOST"], port=os.environ["PGPORT"],
    dbname=os.environ["PGDATABASE"], user=os.environ["PGUSER"],
    password=os.environ["PGPASSWORD"],
)
```

## RLS Scoping

**`current_agent_run_id() → UUID`** extracts your run ID from your username.

RLS policies automatically filter queries:
- **INSERT/UPDATE:** Only for rows with `agent_run_id = current_agent_run_id()`
- **SELECT:** Filtered based on your agent type (see access table below)
- **DELETE:** Not granted; use soft deletes

## Schema Discovery

```bash
psql -c "\dt"                          # List tables
psql -c "\d+ reported_issues"          # Describe table (columns, types, constraints)
psql -c "\dv"                          # List views
psql -c "\df current_*"                # List functions
```

Run `\d+ table_name` before writing queries to understand the schema.

## Agent-Specific Access

### Critic

| Table | SELECT | INSERT | UPDATE |
|-------|--------|--------|--------|
| reported_issues | Own run | Own run | Own run |
| reported_issue_occurrences | Own run | Own run | Own run |
| examples | Current example | - | - |
| true_positives | - | - | - |
| false_positives | - | - | - |

**Note:** Critics have NO access to ground truth (TPs/FPs) — blind review.

### Grader

| Table | SELECT | INSERT | UPDATE |
|-------|--------|--------|--------|
| grading_decisions | Own run | Own run | Own run |
| reported_issues | Graded critic run | - | - |
| reported_issue_occurrences | Graded critic run | - | - |
| true_positives | Graded snapshot | - | - |
| false_positives | Graded snapshot | - | - |

**Note:** Graders see ground truth for the snapshot being graded only.

### Prompt Optimizer / Improvement

| Table | SELECT | INSERT | UPDATE |
|-------|--------|--------|--------|
| examples | TRAIN split only* | - | - |
| true_positives | TRAIN split | - | - |
| false_positives | TRAIN split | - | - |
| critic_runs | TRAIN split | - | - |
| grader_runs | TRAIN split | - | - |
| recall_by_definition_split_kind | All splits (view) | - | - |

*VALID/TEST access restricted to prevent overfitting. See `db/evaluation_flow.md.j2` for details.

### Clustering

| Table | SELECT | INSERT | UPDATE |
|-------|--------|--------|--------|
| unknown_clusters | Own run | Own run | Own run |
| unknown_assignments | Own run | Own run | Own run |
| true_positives | All | - | - |
| false_positives | All | - | - |
| snapshots | All | - | - |
| events | All | - | - |

**Note:** Clustering agent can create clusters and assign unknowns within its own run. Sees all ground truth to identify novel unknowns.
