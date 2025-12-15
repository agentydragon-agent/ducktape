# Clustering Database Schema

## Overview

The clustering subsystem uses **Row-Level Security (RLS)** to isolate data access per clustering run. Each agent runs as a temporary PostgreSQL user whose username encodes the run_id, enabling automatic query scoping without application-layer filtering.

## Tables

### `clustering_runs`

Top-level execution record for clustering tasks. Each row represents one agent session that processes unknown issues from grader runs.

**Columns:**
- `id` (INTEGER, PRIMARY KEY, AUTO-INCREMENT) — Unique run identifier
- `snapshot_slug` (STRING, NOT NULL, FK → snapshots.slug ON DELETE CASCADE) — Which snapshot this run analyzes
- `status` (STRING, NOT NULL, DEFAULT 'in_progress') — Current state: `in_progress`, `completed`, or `abandoned`
- `transcript_id` (STRING, NULLABLE) — Agent transcript ID for debugging/audit
- `started_at` (TIMESTAMP, NOT NULL, DEFAULT now()) — When the run began
- `completed_at` (TIMESTAMP, NULLABLE) — When the run finished (NULL if still running)

**Constraints:**
- CHECK: `status IN ('in_progress', 'completed', 'abandoned')`

**Indexes:**
- `ix_clustering_runs_snapshot_slug` on `snapshot_slug`
- `ix_clustering_runs_status` on `status`

**Relationships:**
- One-to-many with `unknown_clusters` (cascade delete)
- One-to-many with `unknown_assignments` (cascade delete)

**RLS Policies:**
- **clustering_user**: `FOR ALL TO PUBLIC USING (current_user ~ '^clustering_run_[0-9]+_agent$' AND id = current_clustering_run_id())`
  - Temporary users matching the pattern can only see/modify their own run

---

### `unknown_clusters`

Named groups of equivalent unknown issues. Each cluster has a kebab-case name (e.g., `missing-error-handling`) and a description explaining what issues belong to it.

**Columns:**
- `id` (INTEGER, PRIMARY KEY, AUTO-INCREMENT) — Unique cluster identifier
- `clustering_run_id` (INTEGER, NOT NULL, FK → clustering_runs.id ON DELETE CASCADE) — Which run created this cluster
- `cluster_name` (STRING, NOT NULL) — Kebab-case identifier (e.g., `duplicate-validation-logic`)
- `description` (TEXT, NOT NULL) — Human-readable explanation of what this cluster represents
- `created_at` (TIMESTAMP, NOT NULL, DEFAULT now()) — When the cluster was created

**Constraints:**
- UNIQUE (`clustering_run_id`, `cluster_name`) — Cluster names must be unique within a run

**Indexes:**
- `ix_unknown_clusters_clustering_run_id` on `clustering_run_id`

**Relationships:**
- Many-to-one with `clustering_runs`
- One-to-many with `unknown_assignments` (cascade delete)

**RLS Policies:**
- **clustering_user**: `FOR ALL TO PUBLIC USING (current_user ~ '^clustering_run_[0-9]+_agent$' AND clustering_run_id = current_clustering_run_id())`

---

### `unknown_assignments`

Assigns unknown issues (from grader runs) to either:
1. A new cluster (`cluster_id`)
2. An existing true positive (`mapped_tp_id`)
3. An existing false positive (`mapped_fp_id`)

**Exactly one** of these three targets must be set (enforced by CHECK constraint).

**Unknown Issue Identity:**
- Composite key: `(grader_run_id, unknown_id)`
- `unknown_id` is a string identifier from the grader output (e.g., `"input-issue-0"`)

**Columns:**
- `id` (INTEGER, PRIMARY KEY, AUTO-INCREMENT) — Unique assignment identifier
- `clustering_run_id` (INTEGER, NOT NULL, FK → clustering_runs.id ON DELETE CASCADE) — Which run created this assignment
- `grader_run_id` (UUID, NOT NULL, FK → grader_runs.id ON DELETE CASCADE) — Source grader run
- `unknown_id` (STRING, NOT NULL) — Issue identifier within the grader run
- `cluster_id` (INTEGER, NULLABLE, FK → unknown_clusters.id ON DELETE CASCADE) — Target cluster (if assigning to new cluster)
- `mapped_tp_id` (STRING, NULLABLE) — Target TP ID (if mapping to existing true positive, no FK enforcement)
- `mapped_fp_id` (STRING, NULLABLE) — Target FP ID (if mapping to existing false positive, no FK enforcement)
- `rationale` (TEXT, NOT NULL) — Explanation for this assignment decision
- `created_at` (TIMESTAMP, NOT NULL, DEFAULT now()) — When the assignment was created
- `cancelled_at` (TIMESTAMP, NULLABLE) — Soft delete timestamp (NULL = active)
- `cancellation_reason` (TEXT, NULLABLE) — Why this assignment was cancelled

**Constraints:**
- UNIQUE (`clustering_run_id`, `grader_run_id`, `unknown_id`, `cancelled_at`) — Allows re-assignment after cancellation
- CHECK (exactly one target): `(cluster_id IS NOT NULL AND mapped_tp_id IS NULL AND mapped_fp_id IS NULL) OR (cluster_id IS NULL AND mapped_tp_id IS NOT NULL AND mapped_fp_id IS NULL) OR (cluster_id IS NULL AND mapped_tp_id IS NULL AND mapped_fp_id IS NOT NULL)`

**Note on TP/FP references:**
- `mapped_tp_id` and `mapped_fp_id` reference `true_positives.tp_id` and `false_positives.fp_id` respectively
- These are NOT enforced as foreign keys (would require composite FK with `snapshot_slug`)
- Application layer ensures referential integrity

**Indexes:**
- `ix_unknown_assignments_clustering_run_id` on `clustering_run_id`
- `ix_unknown_assignments_grader_run_id` on `grader_run_id`
- `ix_unknown_assignments_grader_unknown` on `(grader_run_id, unknown_id)`
- Partial index `ix_unknown_assignments_active` on `(clustering_run_id, grader_run_id, unknown_id)` WHERE `cancelled_at IS NULL`
- Partial index `ix_unknown_assignments_cluster_active` on `cluster_id` WHERE `cancelled_at IS NULL`

**Relationships:**
- Many-to-one with `clustering_runs`
- Many-to-one with `unknown_clusters` (nullable)
- Many-to-one with `grader_runs`

**RLS Policies:**
- **clustering_user**: `FOR ALL TO PUBLIC USING (current_user ~ '^clustering_run_agent$' AND clustering_run_id = current_clustering_run_id())`

**Soft Delete Workflow:**
1. To cancel an assignment: UPDATE `cancelled_at = now()`, `cancellation_reason = '...'`
2. To create a replacement: INSERT new row (UNIQUE constraint allows it after cancellation)
3. Queries should filter `WHERE cancelled_at IS NULL` to get active assignments only

---

## RLS Mechanism

### Username Pattern

Temporary clustering users follow the pattern:
```
clustering_run_{run_id}_agent
```

Example: `clustering_run_42_agent` for run ID 42

### RLS Helper Function

**`current_clustering_run_id() → INTEGER`**

Extracts the run_id from the current username using regex pattern matching:
```sql
SUBSTRING(current_user FROM 'clustering_run_([0-9]+)_agent')
```

Returns:
- The run_id as an integer if the username matches the pattern
- NULL if the username doesn't match (e.g., for admin users)

**Important:** As of migration `20251214000002`, this function no longer has an `EXCEPTION WHEN OTHERS` handler that was silently swallowing errors.

### RLS Policy Logic

**For clustering tables (`clustering_runs`, `unknown_clusters`, `unknown_assignments`):**
- Temporary users (matching `^clustering_run_[0-9]+_agent$`) can only see/modify rows where the clustering_run_id matches their encoded run_id
- This provides automatic query scoping without application-layer filtering

**For reference tables (read-only access):**
- Temporary users can SELECT from: `snapshots`, `true_positives`, `false_positives`, `critiques`, `critic_runs`, `grader_runs`, `events`
- No INSERT/UPDATE/DELETE permissions on reference tables

### User Management

Temporary users are created/destroyed via `ClusteringUserManager`:
```python
async with ClusteringUserManager(admin_config, run_id) as credentials:
    # User exists during this context
    # Username: f"clustering_run_{run_id}_agent"
    # Password: randomly generated
    pass
# User is dropped here
```

---

## Query Examples

### Get all clusters for current run
```sql
-- As clustering_run_42_agent:
SELECT * FROM unknown_clusters ORDER BY cluster_name;
-- Returns only clusters where clustering_run_id = 42
```

### Get active assignments for current run
```sql
-- As clustering_run_42_agent:
SELECT * FROM unknown_assignments
WHERE cancelled_at IS NULL
ORDER BY created_at;
-- Returns only assignments where clustering_run_id = 42 and not cancelled
```

### Create a new cluster
```sql
-- As clustering_run_42_agent:
INSERT INTO unknown_clusters (clustering_run_id, cluster_name, description)
VALUES (42, 'missing-null-checks', 'Functions that dont validate nullable parameters');
-- RLS enforces clustering_run_id = 42
```

### Assign an unknown to a cluster
```sql
-- As clustering_run_42_agent:
INSERT INTO unknown_assignments (
    clustering_run_id, grader_run_id, unknown_id,
    cluster_id, rationale
)
VALUES (
    42,
    'a1b2c3d4-...'::uuid,
    'input-issue-5',
    (SELECT id FROM unknown_clusters WHERE cluster_name = 'missing-null-checks'),
    'Same pattern: parameter used without null check'
);
```

### Cancel an assignment
```sql
-- As clustering_run_42_agent:
UPDATE unknown_assignments
SET cancelled_at = now(),
    cancellation_reason = 'Reassigning to different cluster after review'
WHERE grader_run_id = 'a1b2c3d4-...'::uuid
  AND unknown_id = 'input-issue-5'
  AND cancelled_at IS NULL;
```

### Get unknown issues from a grader run (for processing)
```sql
-- As clustering_run_42_agent (needs reference table access):
SELECT
    gr.id AS grader_run_id,
    jsonb_array_elements(gr.output -> 'unknowns') AS unknown_issue
FROM grader_runs gr
WHERE gr.snapshot_slug = 'ducktape/2025-11-26-00'
  AND NOT EXISTS (
      SELECT 1 FROM unknown_assignments ua
      WHERE ua.grader_run_id = gr.id
        AND ua.unknown_id = (unknown_issue->>'id')
        AND ua.cancelled_at IS NULL
  );
-- Returns unknowns that haven't been assigned yet
```

---

## Validation Rules

### Cluster Names
- Must be kebab-case (enforced by application layer)
- Must be unique within a clustering_run_id (enforced by UNIQUE constraint)
- Examples: `missing-error-handling`, `duplicate-validation`, `unused-imports`

### Assignment Targets
- Exactly one of (`cluster_id`, `mapped_tp_id`, `mapped_fp_id`) must be NOT NULL
- Enforced by CHECK constraint `unknown_assignments_exactly_one_target_check`

### Soft Delete
- Cancelled assignments have non-NULL `cancelled_at` timestamp
- UNIQUE constraint on `(clustering_run_id, grader_run_id, unknown_id, cancelled_at)` allows re-assignment
- Include `cancelled_at` in the unique key so multiple cancelled assignments can coexist with one active

### Status Values
- `clustering_runs.status` must be one of: `in_progress`, `completed`, `abandoned`
- Enforced by CHECK constraint `clustering_runs_status_check`

---

## Integration Points

### Agent Bootstrap
The agent receives this documentation via `read_package_file_call()` at startup, eliminating the need to query schema metadata.

### Completion Detection
The agent checks if all unknowns from target grader runs have been assigned (active, non-cancelled). When complete, it updates `clustering_runs.status = 'completed'` and sets `completed_at`.

### Audit Trail
- All operations are logged via the standard `events` table (transcript_id links to clustering_runs.transcript_id)
- Soft deletes preserve assignment history
- `rationale` fields document decision reasoning

---

## Performance Considerations

### Indexes
- Primary lookups: by `clustering_run_id` (most common filter due to RLS)
- Unknown identity: composite index on `(grader_run_id, unknown_id)`
- Active assignments: partial indexes for `WHERE cancelled_at IS NULL` queries

### RLS Overhead
- `current_clustering_run_id()` is marked `STABLE` (computed once per statement)
- Username pattern matching via regex is fast (single-digit microseconds)
- Policies add minimal overhead to queries (simple integer equality checks)

---

## Migration History

- `20251214000000_initial_schema_squashed.py` — Created all three tables, RLS function, policies
- `20251214000002_fix_current_clustering_run_id_function.py` — Removed broken EXCEPTION handler from RLS function
