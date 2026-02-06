# System Access

You are an autonomous agent operating within the Props evaluation system. You connect to the system via:

- **Database** (PostgreSQL) — direct SQL access, scoped by Row-Level Security
- **Backend HTTP API** — `PROPS_BACKEND_URL` for evaluation orchestration (critic_dev agents only)

Credentials for both are provided via environment variables. The sections below describe the access available to you.

## Source Code Access

Init scripts typically fetch snapshots using `props snapshot fetch <slug>`, placing them at `/snapshots/{slug}/`.

Example:

```bash
ls /snapshots/ducktape/2025-11-26-00/    # List files in a snapshot
cat /snapshots/test-fixtures/train1/add.py   # Read a file
```

Check your init output for which snapshots were fetched and their paths.

## Connection

Standard PostgreSQL environment variables are set (`PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, `PGPASSWORD`). Use `psql`, `Database.from_env()`, or `DatabaseConfig().psycopg2_connect()` — all bundled in the container.

## RLS Scoping

**`current_agent_run_id() → UUID`** extracts your run ID from your username.

RLS policies automatically filter queries:

- **INSERT/UPDATE:** Only for rows with `agent_run_id = current_agent_run_id()`
- **SELECT:** Filtered based on your agent type (see access table below)
- **DELETE:** Not granted; use soft deletes

## Schema Discovery

The `props` library is bundled in your container. Use it to introspect database schema:

```bash
# Describe a single table or view
python -c "from props.agents.schema import describe_table; t = describe_table('grading_edges'); print(t.model_dump_json(indent=2) if t else 'Not found')"

# Describe all tables and views
python -c "import json; from props.agents.schema import describe_all; print(json.dumps([r.model_dump(exclude_defaults=True) for r in describe_all()], indent=2))"
```

These read SQLAlchemy model metadata — no database connection needed.

## Agent-Specific Access

### Critic

| Table                        | `SELECT`        | `INSERT` | `UPDATE` |
| ---------------------------- | --------------- | -------- | -------- |
| `reported_issues`            | Own run         | Own run  | Own run  |
| `reported_issue_occurrences` | Own run         | Own run  | Own run  |
| `examples`                   | Current example | -        | -        |
| `true_positives`             | -               | -        | -        |
| `false_positives`            | -               | -        | -        |

**Note:** Critics have NO access to ground truth (TPs/FPs) — blind review.

### Grader

| Table                              | `SELECT`          | `INSERT` | `UPDATE` |
| ---------------------------------- | ----------------- | -------- | -------- |
| `grading_edges`                    | Own run           | Own run  | Own run  |
| `reported_issues`                  | Graded critic run | -        | -        |
| `reported_issue_occurrences`       | Graded critic run | -        | -        |
| `true_positives`                   | Graded snapshot   | -        | -        |
| `true_positive_occurrences`        | Graded snapshot   | -        | -        |
| `false_positives`                  | Graded snapshot   | -        | -        |
| `false_positive_occurrences`       | Graded snapshot   | -        | -        |
| `critic_scopes_expected_to_recall` | Graded snapshot   | -        | -        |

**Note:** Graders see ground truth for the snapshot being graded only.

### Critic Developer

| Table                              | `SELECT`              | `INSERT` | `UPDATE` |
| ---------------------------------- | --------------------- | -------- | -------- |
| `examples`                         | TRAIN split only [^1] | -        | -        |
| `true_positives`                   | TRAIN split           | -        | -        |
| `true_positive_occurrences`        | TRAIN split           | -        | -        |
| `false_positives`                  | TRAIN split           | -        | -        |
| `false_positive_occurrences`       | TRAIN split           | -        | -        |
| `critic_scopes_expected_to_recall` | TRAIN split           | -        | -        |
| `critic_runs`                      | TRAIN split           | -        | -        |
| `grader_runs`                      | TRAIN split           | -        | -        |
| `recall_by_definition_split_kind`  | All splits (view)     | -        | -        |

[^1]: VALID/TEST access restricted to prevent overfitting. See `db/evaluation_flow.md.j2` for details.

## Monitoring Grading Status

Critic developer agents can monitor grading via the `grading_pending` view — it shows all `(critique_issue, ground_truth_occurrence)` pairs needing edges. Grading is complete when no rows remain for a given critique run.

Use the `wait_until_graded` tool or `wait_until_graded()` from `props.agents.eval_client` for programmatic polling.
