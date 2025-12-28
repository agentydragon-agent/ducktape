# Persistent Grader + Ground Truth CRUD Plan

## Overview

Replace ephemeral one-shot graders with persistent "grader daemons" (one per snapshot) that wake when drift is detected and reconcile grading decisions. Move ground truth source of truth from git YAML to PostgreSQL with REST API.

## Token Economics Analysis (Justifying 1 Grader Per Snapshot)

**Observed from real grader run (crush/2025-08-30-internal_db):**

Raw API token data per turn:
| Turn | Input Tokens | Cached Tokens | Cache % | What Happened |
|------|--------------|---------------|---------|---------------|
| 1 | 13,940 | 2,688 | 19% | Initial context load |
| 2 | 14,230 | 13,952 | 98% | Listed resources |
| 3 | 20,578 | 14,208 | 69% | Loaded TPs (+6K new) |
| 4 | 22,112 | 20,608 | 93% | Loaded FPs (+2K new) |
| 5+ | ~22-24K | ~22K | ~93% | Steady state |

**Context breakdown:**
| Component | Est. Tokens | Reuse Potential |
|-----------|-------------|-----------------|
| System prompt | ~3,500 | Same for all graders |
| Ground truth (TPs) | ~6,000 | Same within snapshot (compressed from 103K chars) |
| Ground truth (FPs) | ~2,000 | Same within snapshot |
| Critique content | ~400-1,000 | Per-critique (unique) |
| Conversation history | ~2-3K/turn | Accumulates |

**Key insight:** After GT is loaded (turn 3-4), cache hit rate is 93%+. The ~14K "stable prefix" (system + GT) is cached and reused. Each new grading operation only pays for incremental context growth.

**Cost comparison (10 critiques to grade):**

| Scope | Input Tokens | Why |
|-------|--------------|-----|
| 1/critique (current) | ~380K | Each grader loads GT fresh |
| 1/snapshot (proposed) | ~100K | GT loaded once, reused via cache |

**GT change scenario (add 1 TP, regrade 10 critiques):**
- Current: 10 new graders × 35K = 350K tokens
- Proposed: 1 daemon wakes, incrementally adds decisions = ~60K tokens

**Recommendation:** 1 grader per snapshot saves ~75% tokens through GT caching.

---

## Phase 1: Database Backup Infrastructure ✅ COMPLETE

Implemented in devenv.nix (`pg_backup` process) and CLI (`props db backup/restore/list-backups`).

---

## Phase 2: Ground Truth CRUD API

### 2.1 REST Endpoints

New file: `backend/src/props_backend/routes/ground_truth.py`

**Read Endpoints (✅ Done):**
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/gt/snapshots` | List all snapshots with TP/FP counts ✅ |
| GET | `/api/gt/snapshots/{slug}` | Get snapshot with all TPs and FPs ✅ |

**Write Endpoints (Pending):**
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/gt/snapshots/{slug}/tps` | Create TP |
| PUT | `/api/gt/snapshots/{slug}/tps/{tp_id}` | Update rationale |
| DELETE | `/api/gt/snapshots/{slug}/tps/{tp_id}` | Delete (cascades) |
| POST | `/api/gt/snapshots/{slug}/tps/{tp_id}/occurrences` | Add occurrence |
| DELETE | `/api/gt/snapshots/{slug}/tps/{tp_id}/occurrences/{occ_id}` | Remove occurrence |
| (mirror for FPs) | | |

### 2.2 Content Addressability

- `tp_id`/`fp_id`: User-provided OR auto-generated from location hash
- `occurrence_id`: Hash of sorted file:line_ranges
- CHECK constraints: `tp_id ~ '^[a-z0-9_-]{1,64}$'`
- **Trigger sets:** Always explicit. No auto-inference for single-file TPs.

### 2.3 Bidirectional YAML Sync

**YAML and DB are kept side-by-side** (not one replacing the other):

**YAML → DB (existing):**
- `props db sync` loads ground truth from specimens YAML into database
- Used to seed DB from authoritative YAML files

**DB → YAML (new):**
- `props gt export <snapshot_slug>` exports DB ground truth back to YAML
- Allows editing via REST API, then exporting back to specimens repo
- Preserves round-trip capability

**Workflow options:**
1. Edit YAML manually → sync to DB
2. Edit via REST API → export to YAML → commit to git

### 2.4 Database Changes (Migration)

**Design decisions:**

1. **No `gt_version` counter needed.** Drift = missing edges (self-evident from drift view). pg_notify sufficient for daemon wake-up.

2. **No immutability triggers.** UPDATEs are allowed for minor wording fixes to rationales. For semantic changes that affect grading meaning, users should DELETE + INSERT (cascade deletes old grading decisions). UI will show warnings about editing graded content.

3. **IDs are user-provided, not content-addressable.** Simpler model - users choose stable IDs. Same ID can be reused after delete since cascade clears old decisions.

```sql
-- pg_notify for grader daemon wake-up (fires on GT changes)
CREATE FUNCTION notify_gt_changed() RETURNS TRIGGER AS $$
BEGIN
    PERFORM pg_notify('grading_pending', json_build_object(
        'event', TG_OP || '_' || TG_TABLE_NAME,
        'snapshot_slug', COALESCE(NEW.snapshot_slug, OLD.snapshot_slug)
    )::text);
    RETURN COALESCE(NEW, OLD);
END;
$$ LANGUAGE plpgsql;

-- Notify on INSERT/DELETE only (updates are minor wording fixes, no re-grade needed)
CREATE TRIGGER trg_notify_tp AFTER INSERT OR DELETE
ON true_positives FOR EACH ROW EXECUTE FUNCTION notify_gt_changed();

CREATE TRIGGER trg_notify_fp AFTER INSERT OR DELETE
ON false_positives FOR EACH ROW EXECUTE FUNCTION notify_gt_changed();
```

---

## Phase 3: Bipartite Graph Model + Drift Detection

### 3.1 Core Model: Bipartite Graph with Cascade Deletes

**Invariants:**
1. **User-provided IDs:** `tp_id`, `fp_id`, `occurrence_id` are user-chosen stable identifiers (not content-addressable)
2. **Updates allowed:** Minor wording fixes to rationales permitted; for semantic changes, users should DELETE + INSERT
3. **Cascade delete:** Deleting a TP/FP occurrence cascades to delete its grading edges (clears old decisions)
4. **Complete coverage:** Every (critique_issue, GT_occurrence) pair must have an explicit grading edge

**Grading edges table (replaces grading_decisions):**

Follow existing pattern: one table with nullable TP/FP columns, CHECK constraint for exactly-one.

```sql
CREATE TABLE grading_edges (
    id SERIAL PRIMARY KEY,
    critique_issue_id UUID NOT NULL REFERENCES reported_issues(id) ON DELETE CASCADE,

    -- TP target (nullable)
    tp_id VARCHAR,
    tp_occurrence_id VARCHAR,
    -- FP target (nullable)
    fp_id VARCHAR,
    fp_occurrence_id VARCHAR,

    -- For TPs: credit 0.0-1.0 (how well critique matches; 0.0 = no match)
    -- For FPs: anti-credit (penalty for triggering FP)
    credit FLOAT NOT NULL,
    rationale TEXT NOT NULL,
    grader_run_id UUID NOT NULL REFERENCES agent_runs(agent_run_id) ON DELETE CASCADE,
    created_at TIMESTAMP DEFAULT now(),

    -- Exactly one of TP or FP must be set (same pattern as grading_decisions)
    CHECK (
        (tp_id IS NOT NULL AND tp_occurrence_id IS NOT NULL AND fp_id IS NULL AND fp_occurrence_id IS NULL) OR
        (fp_id IS NOT NULL AND fp_occurrence_id IS NOT NULL AND tp_id IS NULL AND tp_occurrence_id IS NULL)
    ),

    -- FKs with cascade (nullable FKs work fine)
    FOREIGN KEY (tp_id, tp_occurrence_id)
        REFERENCES true_positive_occurrences(tp_id, occurrence_id) ON DELETE CASCADE,
    FOREIGN KEY (fp_id, fp_occurrence_id)
        REFERENCES false_positive_occurrences(fp_id, occurrence_id) ON DELETE CASCADE,

    -- Prevent duplicate edges for same (issue, occurrence) pair
    UNIQUE (critique_issue_id, tp_id, tp_occurrence_id),
    UNIQUE (critique_issue_id, fp_id, fp_occurrence_id)
);
```

**Same pattern as grading_decisions:** nullable columns for TP/FP targets, CHECK constraint enforces exactly-one.

**No explicit "none" type:** Pairs with no semantic match still get a TP edge with `credit=0.0`. The grader can use brief rationales like "No match" for these.

### 3.2 Sparse Graph via `only_matchable_from_files`

Most GT occurrences are file-local (dead code, local style issues). Only cross-cutting issues need full coverage.

**Add to TP/FP occurrences:**

```sql
-- Points to file_sets table (reuses existing infrastructure)
ALTER TABLE true_positive_occurrences
ADD COLUMN only_matchable_from_files_hash TEXT
REFERENCES file_sets(files_hash) ON DELETE SET NULL;

ALTER TABLE false_positive_occurrences
ADD COLUMN only_matchable_from_files_hash TEXT
REFERENCES file_sets(files_hash) ON DELETE SET NULL;

-- NULL = cross-cutting (any critique issue can match)
-- non-NULL = only critique issues reporting on those files can match
```

**Edge matchability constraint:** A trigger validates edges using the shared `matchable_occurrences()` function (see section 3.5).

### 3.3 Drift View

See section 3.5 for the `matchable_occurrences()` function and drift view implementation.

The drift view shows missing edges: pairs (critique_issue, gt_occurrence) where matching is allowed but no edge exists yet.

### 3.4 Why This Model Works

- **Add new TP occurrence:** New pairs needed for matching critiques → drift appears
- **Delete TP occurrence:** Cascade deletes edges → no stale references, metrics auto-update
- **New critique completes:** New pairs needed for matching GT occurrences → drift appears
- **No staleness tracking:** Cascade deletes = automatic consistency; updates assumed to be minor wording fixes
- **Sparse graph:** `only_matchable_from_files` reduces edge count by ~80% for file-local issues

### 3.5 Matchable Occurrences Function (Shared Core)

The core question "which GT occurrences are matchable from these files?" is needed by:
1. **Drift view** — to compute expected edges
2. **Estimation** — to predict grader workload
3. **Edge validation trigger** — to enforce matchability constraint

Extract as a single table-returning function used by all three:

```sql
-- Index for efficient file-local lookups (needed by function)
CREATE INDEX idx_file_set_members_file_path
ON file_set_members(snapshot_slug, file_path);

-- Core shared function: returns matchable GT occurrences for given files
CREATE FUNCTION matchable_occurrences(
    p_snapshot_slug VARCHAR,
    p_files VARCHAR[]
) RETURNS TABLE (
    tp_id VARCHAR,
    tp_occurrence_id VARCHAR,
    fp_id VARCHAR,
    fp_occurrence_id VARCHAR
) AS $$
    -- TPs: cross-cutting (NULL) or file overlap
    SELECT tpo.tp_id, tpo.occurrence_id, NULL::VARCHAR, NULL::VARCHAR
    FROM true_positive_occurrences tpo
    WHERE tpo.snapshot_slug = p_snapshot_slug
      AND (
          tpo.only_matchable_from_files_hash IS NULL
          OR EXISTS (
              SELECT 1 FROM file_set_members fsm
              WHERE fsm.snapshot_slug = tpo.snapshot_slug
                AND fsm.files_hash = tpo.only_matchable_from_files_hash
                AND fsm.file_path = ANY(p_files)
          )
      )
    UNION ALL
    -- FPs: cross-cutting (NULL) or file overlap
    SELECT NULL, NULL, fpo.fp_id, fpo.occurrence_id
    FROM false_positive_occurrences fpo
    WHERE fpo.snapshot_slug = p_snapshot_slug
      AND (
          fpo.only_matchable_from_files_hash IS NULL
          OR EXISTS (
              SELECT 1 FROM file_set_members fsm
              WHERE fsm.snapshot_slug = fpo.snapshot_slug
                AND fsm.files_hash = fpo.only_matchable_from_files_hash
                AND fsm.file_path = ANY(p_files)
          )
      )
$$ LANGUAGE SQL STABLE;
```

**Drift view uses the function:**

```sql
CREATE VIEW grading_pending AS
WITH critique_issues AS (
    SELECT
        ri.id AS critique_issue_id,
        (ar.type_config->'example'->>'snapshot_slug') AS snapshot_slug,
        array_agg(DISTINCT rio.file_path) AS reported_files
    FROM reported_issues ri
    JOIN agent_runs ar ON ar.agent_run_id = ri.agent_run_id
    LEFT JOIN reported_issue_occurrences rio ON rio.issue_id = ri.id
    WHERE ar.type_config->>'agent_type' = 'critic'
      AND ar.status = 'completed'
    GROUP BY ri.id, ar.type_config
)
-- Missing TP edges
SELECT ci.critique_issue_id, mo.tp_id, mo.tp_occurrence_id, mo.fp_id, mo.fp_occurrence_id
FROM critique_issues ci
CROSS JOIN LATERAL matchable_occurrences(ci.snapshot_slug, ci.reported_files) mo
LEFT JOIN grading_edges ge
    ON ge.critique_issue_id = ci.critique_issue_id
   AND ((ge.tp_id = mo.tp_id AND ge.tp_occurrence_id = mo.tp_occurrence_id)
        OR (ge.fp_id = mo.fp_id AND ge.fp_occurrence_id = mo.fp_occurrence_id))
WHERE ge.id IS NULL;
```

**Estimation is just COUNT:**

```sql
-- How many edges would this critique need?
SELECT COUNT(*) FROM matchable_occurrences('snapshot-slug', ARRAY['src/foo.py']);

-- Per-file distribution
SELECT sf.relative_path,
       (SELECT COUNT(*) FROM matchable_occurrences(sf.snapshot_slug, ARRAY[sf.relative_path])) AS edge_count
FROM snapshot_files sf
WHERE sf.snapshot_slug = 'ducktape/2025-11-26-00'
ORDER BY edge_count DESC;
```

**Edge validation trigger uses the function:**

```sql
CREATE FUNCTION check_edge_matchability() RETURNS TRIGGER AS $$
DECLARE
    critique_files VARCHAR[];
    is_matchable BOOLEAN;
BEGIN
    -- Get files the critique reports on
    SELECT array_agg(DISTINCT rio.file_path) INTO critique_files
    FROM reported_issue_occurrences rio
    WHERE rio.issue_id = NEW.critique_issue_id;

    -- Check if this GT occurrence is matchable from those files
    SELECT EXISTS (
        SELECT 1 FROM matchable_occurrences(
            (SELECT snapshot_slug FROM reported_issues ri
             JOIN agent_runs ar ON ar.agent_run_id = ri.agent_run_id
             WHERE ri.id = NEW.critique_issue_id),
            critique_files
        ) mo
        WHERE (mo.tp_id = NEW.tp_id AND mo.tp_occurrence_id = NEW.tp_occurrence_id)
           OR (mo.fp_id = NEW.fp_id AND mo.fp_occurrence_id = NEW.fp_occurrence_id)
    ) INTO is_matchable;

    IF NOT is_matchable THEN
        RAISE EXCEPTION 'Edge not allowed: GT occurrence not matchable from critique files';
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
```

**Before `only_matchable_from_files` is populated:** All occurrences have NULL → all matchable → 100-300 edges per critique.

**After population:** File-local occurrences filtered → 5-20 edges typical.

### 3.6 Documentation Updates Required

This model change requires significant documentation updates:

**In props repository:**
- `docs/db/ground_truth.md.j2` — Add `only_matchable_from_files` field explanation
- `docs/db/grading.md.j2` — Explain bipartite graph model, sparse matching
- `docs/agents/grader.md.j2` — Update grader workflow for edge-based grading
- `docs/writing_agent_definitions.md.j2` — Update for new grading semantics

**In specimens repository:**
- Update issue YAML schema to include `only_matchable_from_files`
- Add examples showing file-local vs cross-cutting issues
- Document the distinction from `expect_caught_from`
- Migration guide for existing issues (default: NULL = cross-cutting)

---

## Phase 4: Unified Grading Model (Edges + Drift Detection)

### 4.1 Unified Write Model

**Both existing per-critique graders and future daemons write to the same `grading_edges` table.**

This means:
- Single storage model, no parallel tables
- Same CLI commands work for both use cases
- Drift view works regardless of who fills edges
- Smooth migration path

### 4.2 CLI Changes for Graders

Update `cli/cmd_grader_agent.py` to write to `grading_edges`:

```bash
# Grader CLI commands (unified for per-critique and daemon)
# Pattern: <verb> <resource> [args...]

# Read one item
props grader-agent show issue <issue-id>       # Critique issue (description, files, occurrences)
props grader-agent show gt <tp|fp>/<id>/<occ>  # GT occurrence (rationale, files, lines)

# List multiple items
props grader-agent list issues [--critique <run-id>]  # Critique issues
props grader-agent list gt                            # All GT for snapshot
props grader-agent list critiques                     # Critique runs (daemon only)
props grader-agent list pending [filters...]          # What still needs grading

# Write grading edges
props grader-agent match <issue-id> "rationale" <occ:credit>...
props grader-agent fill <issue-id> <expected-count> "rationale"

# Finalize (per-critique only)
props grader-agent submit "summary"

# list pending filters (combinable):
#   (no args)                    → all pending in scope
#   --critique <run-id>          → filter to one critique run (daemon only)
#   --issue <issue-id>           → filter to one issue
#   --gt tp/<id>/<occ>           → filter to one GT occurrence
```

**Auto-detection via type_config:**

The CLI checks `current_agent_type_config()` to determine mode:
- **Per-critique**: Has `critic_run_id` → commands implicitly scoped to that run
- **Daemon**: Has `snapshot_slug` only → `get-drift` returns all drift for snapshot

```python
def get_grader_mode() -> tuple[Literal["per_critique", "daemon"], str]:
    """Returns (mode, scope_id) based on type_config."""
    config = current_agent_type_config()
    if "critic_run_id" in config:
        return ("per_critique", config["critic_run_id"])
    else:
        return ("daemon", config["snapshot_slug"])
```

**Command behavior by mode:**

| Command | Per-critique | Daemon |
|---------|-------------|--------|
| `get-drift` | Drift for one critic run | All drift for snapshot |
| `get-drift <issue-id>` | Filter to issue (must be in scope) | Filter to issue |
| `set-matches` | issue must be from graded run | issue can be from any critique in snapshot |
| `fill-remaining` | Same | Same |
| `submit` | Finalize and exit | Error: daemons don't submit |

**Lifecycle:**
- **Per-critique grader**: Grades one critic run, calls `submit`, exits. Finite task.
- **Snapshot daemon**: Forever-living. Works until drift=0, then sleeps. Woken by pg_notify when GT changes. No `submit` - loops on drift detection.

**Example: Per-critique grader session**

```
$ props grader-agent list pending
Missing 3 edges for 1 issue:
  input-001: tp/security-issue/occ-0, tp/dead-code/occ-0, fp/dup-pattern/occ-0

$ # Inspect the issue and GT to make decisions
$ props grader-agent show issue input-001
Issue: input-001
Description: "Potential SQL injection vulnerability"
Files: src/db.py:42-45

$ props grader-agent show gt tp/security-issue/occ-0
TP: security-issue/occ-0
Rationale: "SQL query built with string concatenation..."
Files: src/db.py:42-45

$ # Set matches
$ props grader-agent match input-001 "Security issue matched, others not relevant" \
    tp/security-issue/occ-0:1.0 \
    tp/dead-code/occ-0:0 \
    fp/dup-pattern/occ-0:0
Matched 3 edges. input-001: done.

$ props grader-agent list pending
No pending work.

$ props grader-agent submit "Graded 1 issue: 1 TP match (security-issue)"
Grading submitted successfully.
```

**Example: Snapshot daemon session**

```
$ props grader-agent list pending
Missing 94 edges across 3 critique runs, 24 issues:

  Critique run: abc123 (critic v1.2, 2024-01-15)
    issue-001: tp/security-issue/occ-0, tp/dead-code/occ-0 (2 missing)
    issue-002: tp/security-issue/occ-0, ... (5 missing)
    issue-003: ... (4 missing)

  Critique run: def456 (critic v1.3, 2024-01-16)
    issue-001: tp/security-issue/occ-0, tp/dead-code/occ-0 (2 missing)
    issue-002: ... (3 missing)
    ...

  Critique run: ghi789 (critic v1.3, 2024-01-17)
    ...

$ # Work through one critique's issues
$ props grader-agent list pending --issue abc123:issue-001
Missing 2 edges:
  tp/security-issue/occ-0
  tp/dead-code/occ-0

$ props grader-agent match abc123:issue-001 "Security matched, dead-code not" \
    tp/security-issue/occ-0:1.0 \
    tp/dead-code/occ-0:0
Matched 2 edges. abc123:issue-001: done.

$ props grader-agent list pending --issue abc123:issue-002
Missing 5 edges:
  tp/security-issue/occ-0
  tp/another-issue/occ-0
  ...

$ # After reviewing, confident remaining 3 are not matches
$ props grader-agent match abc123:issue-002 "Security and another matched" \
    tp/security-issue/occ-0:0.8 \
    tp/another-issue/occ-0:1.0
Matched 2 edges. abc123:issue-002: 3 to fill.

$ # Feedback shows 3 to fill - that's the count for fill command
$ props grader-agent fill abc123:issue-002 3 "Reviewed, no matches"
Filled 3 edges. abc123:issue-002: done.

$ # ... work through all critique runs ...

$ props grader-agent list pending
No pending work.

$ # Daemon sleeps here, woken by pg_notify when GT changes
# [blocking wait for pg_notify('grading_pending', ...)]

$ # GT changed - new TP added
$ props grader-agent list pending
Missing 24 edges across 3 critique runs, 24 issues:
  ...

$ # Filter to just the new TP - see which issues need grading against it
$ props grader-agent list pending --gt tp/new-issue/occ-0
Missing 24 edges for tp/new-issue/occ-0:
  abc123:issue-001, abc123:issue-002, abc123:issue-003, ...
  def456:issue-001, def456:issue-002, ...
  ghi789:issue-001, ...

$ # Bulk-grade: this new TP doesn't match any existing critique issues
$ props grader-agent match abc123:issue-001 "New TP not relevant" tp/new-issue/occ-0:0
$ props grader-agent match abc123:issue-002 "New TP not relevant" tp/new-issue/occ-0:0
$ # ... or script it:
$ for issue in $(props grader-agent list pending --gt tp/new-issue/occ-0 --format ids); do
>   props grader-agent match $issue "New TP not relevant to this issue" tp/new-issue/occ-0:0
> done

$ props grader-agent list pending
No pending work.
```

**Edge types:**
- **TP edges**: `credit` is 0.0-1.0 (how well the issue matches this TP occurrence)
- **FP edges**: `credit` for FPs (0 = not triggered, >0 = incorrectly triggered)
- **No "none" type**: Pairs with no match get `credit=0.0` edges

**Usage examples:**

```bash
# Single match with rationale
props grader-agent set-matches input-001 "Exact match on security issue" \
    tp/security-issue/occ-0:1.0

# Multiple matches, one rationale covers all
props grader-agent set-matches input-001 "Security issue matched, others reviewed - no match" \
    tp/security-issue/occ-0:1.0 \
    tp/dead-code/occ-0:0 \
    tp/other-issue/occ-0:0

# After reviewing all, fill remaining with checksum safety
props grader-agent fill-remaining input-001 5 "Reviewed, no matches"
# ^ Fails if actual missing != 5 (catches GT drift)
```

The CLI helpers:
1. Validate issue_id and gt_occ_id exist and are in scope (RLS-enforced)
2. Check matchability constraint (sparse graph)
3. Insert/update edge in `grading_edges`
4. Return confirmation

### 4.3 Drift-Gated Grader Loop

Graders query pending work to know what remains:

```bash
# Grader's main loop
while true; do
    pending=$(props grader-agent list pending --format json)
    if [ "$pending" = "[]" ]; then
        echo "No pending work, done"
        break
    fi
    # Process each missing edge...
done
```

The `list pending` command queries the `grading_pending` view filtered to the grader's scope (RLS-enforced).

### 4.4 Agent Documentation Updates

Update `docs/agents/grader.md.j2` to explain:

1. **The edges model** - each (critique_issue, gt_occurrence) pair needs an edge
2. **Drift detection** - query `grading_pending` view to see missing edges
3. **Schema reference** - include `{{ describe_relation("grading_edges") }}`
4. **CLI usage** - document the grade-tp, grade-fp, grade-no-match commands
5. **Sparse matching** - explain `only_matchable_from_files` constraint

Example docs section:
```markdown
## Grading Edges Model

Your job is to fill in missing edges in the grading graph. Each edge represents
your judgment about whether a critique issue matches a ground truth occurrence.

{{ describe_relation("grading_edges") }}

## Checking Your Work

Query the drift view to see what edges are missing:
\`\`\`sql
SELECT * FROM grading_pending WHERE critique_issue_id IN (SELECT id FROM reported_issues WHERE agent_run_id = '<critic_run>');
\`\`\`

When this returns empty, you're done.
```

### 4.5 RLS Policies for Edges

**RLS helper functions** (already exist in schema):
- `current_agent_run_id()` — Extracts agent run UUID from current DB username
- `current_agent_type()` — Returns agent type from current run's type_config
- `current_graded_agent_run_id()` — For graders: returns the critic run being graded (from type_config)

```sql
-- Grader writes edges for issues in their graded critique
CREATE POLICY grader_writes_edges ON grading_edges FOR INSERT WITH CHECK (
    current_agent_type() = 'grader'
    AND EXISTS (
        SELECT 1 FROM reported_issues ri
        WHERE ri.id = grading_edges.critique_issue_id
          AND ri.agent_run_id = current_graded_agent_run_id()
    )
);

-- Grader reads edges they created
CREATE POLICY grader_reads_own_edges ON grading_edges FOR SELECT USING (
    grader_run_id = current_agent_run_id()
);
```

### 4.6 Future: Snapshot Grader Daemon

Once the unified model is working, adding persistent daemons is straightforward:

- Same `grading_edges` table
- Same CLI commands - all take explicit `<critique-issue-id>` (no implicit context)
- Broader RLS scope (all critiques for a snapshot, not just one)
- pg_notify wake-up mechanism
- Context compaction for long-running sessions

**CLI uniformity:** Both per-critique graders and snapshot daemons use the same CLI. The only difference is RLS scope:
- Per-critique grader: `get-drift` returns missing edges for one critic run
- Snapshot daemon: `get-drift` returns missing edges for entire snapshot

This is deferred until the unified model is proven with existing graders.

---

## Phase 5: Clustering Removal ✅ COMPLETE

Removed via migration 20251227000003. Deleted all code, CLI, docs, and database tables.

---

## Phase 6: Documentation Updates

### Agent-Facing Docs

| File | Change |
|------|--------|
| `docs/database_access.md` | Add Grader Daemon section, remove Clustering |
| `docs/agents/grader.md.j2` | Update for daemon mode (continuous reconciliation) |
| `docs/db/grading.md.j2` | Add drift detection, staleness concepts |

### Developer Docs

| File | Change |
|------|--------|
| `props/AGENTS.md` | Update architecture overview |
| `backend/AGENTS.md` | Add GT CRUD endpoints |
| `core/AGENTS.md` | Update agent types |

---

## Implementation Order

### Phase A: Infrastructure ✅ COMPLETE

- ✅ Backup infrastructure (devenv `pg_backup` process + `props db backup/restore/list-backups` CLI)
- ✅ Remove clustering (code, CLI, docs, database migration 20251227000003)

### Phase B: Schema + YAML Extension

#### B.1 YAML Schema (props repo)

**File:** `db/sync/_yaml_models.py`
- Add `only_matchable_from_files: list[str] | None` to `YAMLOccurrence`
- Pydantic validator: reject `[]` (must be `null` or `[file1, ...]`)

#### B.2 DB Migration

**New migration:** Add column with composite FK (enforces same snapshot)
```sql
ALTER TABLE true_positive_occurrences
ADD COLUMN only_matchable_from_files_hash TEXT;

ALTER TABLE true_positive_occurrences
ADD CONSTRAINT fk_tp_occ_matchable_files
  FOREIGN KEY (snapshot_slug, only_matchable_from_files_hash)
  REFERENCES file_sets(snapshot_slug, files_hash) ON DELETE SET NULL;

ALTER TABLE false_positive_occurrences
ADD COLUMN only_matchable_from_files_hash TEXT;

ALTER TABLE false_positive_occurrences
ADD CONSTRAINT fk_fp_occ_matchable_files
  FOREIGN KEY (snapshot_slug, only_matchable_from_files_hash)
  REFERENCES file_sets(snapshot_slug, files_hash) ON DELETE SET NULL;
```

#### B.3 Sync Code

**File:** `db/sync/sync.py` (or loader)
- When `only_matchable_from_files` is non-null:
  1. Compute hash from sorted file list
  2. Insert into `file_sets` + `file_set_members` if not exists
  3. Set FK on occurrence row

#### B.4 Domain Models

**Files:** `models/true_positive.py`, `models/false_positive.py`
- Add `only_matchable_from_files: frozenset[Path] | None` to occurrence models

#### B.5 User Action (specimens repo)

- Edit YAMLs to add `only_matchable_from_files` where appropriate
- NULL = cross-cutting, non-null = file-local

#### B.6 Final Sync

- Run `props db sync` to populate DB with complete data

### Phase C: GT CRUD + Bidirectional Sync

6. **GT schema migration** — Add grading_edges table, pg_notify triggers, `matchable_occurrences()` function (shared by drift view, estimation, validation trigger), `grading_pending` view, `idx_file_set_members_file_path` index
7. **GT Read API** ✅ — `GET /api/gt/snapshots`, `GET /api/gt/snapshots/{slug}` (list/detail)
8. **GT Browser Frontend** ✅ — `SnapshotsList.svelte`, `SnapshotDetail.svelte`, nav integration
9. **DB → YAML export** ✅ — `props gt export` command for exporting back to YAML
10. **GT Write API** — POST/PUT/DELETE endpoints for CRUD operations

### Phase D: Unified Grading Model (Migrate Existing Graders)

Migrate existing per-critique graders to use edges + drift detection:

11. **Grader CLI rewrite** — Update `cli/cmd_grader_agent.py`:
    - `props grader-agent get-drift` — Query missing edges for grader's scope
    - `props grader-agent assign <issue-id> tp <occ-id> <credit> "rationale"` — Insert TP edge
    - `props grader-agent assign <issue-id> fp <occ-id> <anti-credit> "rationale"` — Insert FP edge
    - `props grader-agent list-missing <issue-id>` — List GT occurrences needing edges
12. **Grader persistence update** — `grader/persistence.py` writes to `grading_edges`
13. **RLS policies for edges** — Grader can write edges for issues in their graded critique
14. **Recall views migration** — Update views to read from `grading_edges`
15. **Grader agent docs** — Update `docs/agents/grader.md.j2`:
    - Explain edges model with `{{ describe_relation("grading_edges") }}`
    - Document drift-gated loop pattern
    - CLI command reference
    - Sparse matching explanation

### Phase E: Documentation

16. **Documentation updates** — All agent-facing docs, specimens repo docs

### Phase F: Snapshot Grader Daemon (Future)

Deferred until unified model proven with existing graders:

17. **SnapshotGraderDaemonTypeConfig** — New type with snapshot-wide scope
18. **Broader RLS** — Daemon sees all critiques for snapshot
19. **pg_notify listener** — Wake daemon on GT changes
20. **Context compaction** — Handle long-running sessions

**Note:** Existing GRADER writes to same `grading_edges` table as future daemons.

---

## Critical Files

| File | Purpose | Status |
|------|---------|--------|
| `props/devenv.nix` | Backup process | ✅ Done |
| `props/core/src/props_core/cli/cmd_db.py` | Backup CLI commands | ✅ Done |
| `props/core/src/props_core/db/sync/_yaml_models.py` | YAML input parsing | ✅ Updated (only_matchable_from_files) |
| `props/core/src/props_core/db/sync/sync.py` | YAML → DB sync | ✅ Updated (only_matchable_from_files) |
| `props/core/src/props_core/models/true_positive.py` | Domain models | ✅ Updated (only_matchable_from_files) |
| `props/core/src/props_core/db/models.py` | ORM models | Partial (only_matchable_from_files ✅, grading_edges pending) |
| `props/core/src/props_core/cli/cmd_gt.py` | GT export CLI | ✅ Done |
| `props/core/src/props_core/db/sync/export.py` | DB → YAML export | ✅ Done |
| `props/backend/src/props_backend/routes/ground_truth.py` | GT Read API | ✅ Done (list snapshots, get detail) |
| `props/frontend/src/components/SnapshotsList.svelte` | Snapshots table view | ✅ Done |
| `props/frontend/src/components/SnapshotDetail.svelte` | Snapshot issues view | ✅ Done |
| `props/core/src/props_core/db/migrations/versions/` | Schema changes | ✅ 20251227000004 (only_matchable_from_files) |
| `props/core/src/props_core/cli/cmd_grader.py` | Grader CLI (grade-tp, get-drift, etc.) | Pending (rewrite for edges) |
| `props/core/src/props_core/grader/persistence.py` | Grader writes to grading_edges | Pending |
| `props/core/src/props_core/docs/agents/grader.md.j2` | Grader agent docs (edges model, drift) | Pending |
| `props/core/src/props_core/docs/db/grading.md.j2` | Grading schema docs | Pending |
