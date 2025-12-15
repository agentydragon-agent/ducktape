# Grader TODOs

## RLS-Secured Database Access (Like Clustering)

**Current state:** Grader uses admin database credentials and ground truth is passed via MCP resources.

**Desired state:** Grader gets isolated PostgreSQL credentials with RLS policies that:
- Allow reading only the specific critique being graded
- Allow reading only the relevant ground truth (TPs/FPs) for that critique's snapshot
- Allow writing only grading results associated with its grader run
- Prevent accidental access to other critiques, snapshots, or runs

**Implementation approach:**
1. Create `GraderUserManager` similar to `ClusteringUserManager` or `PromptOptimizerUserManager`
   - Username pattern: `grader_agent_{grader_run_id}` or similar
   - Create temporary user on grader run start
   - Drop user on grader run completion

2. Add RLS policies for grader access:
   ```sql
   -- Function to extract grader run ID from username
   CREATE FUNCTION current_grader_run_id() RETURNS uuid AS $$
     SELECT uuid(regexp_replace(current_user, 'grader_agent_', ''));
   $$ LANGUAGE SQL STABLE;

   -- Policy: Graders can only read their assigned critique
   CREATE POLICY grader_read_critique ON critiques
     FOR SELECT TO grader_users
     USING (id = (SELECT critique_id FROM grader_runs WHERE id = current_grader_run_id()));

   -- Policy: Graders can only read ground truth for their critique's snapshot
   CREATE POLICY grader_read_true_positives ON true_positives
     FOR SELECT TO grader_users
     USING (snapshot_slug = (
       SELECT c.snapshot_slug FROM critiques c
       JOIN grader_runs gr ON gr.critique_id = c.id
       WHERE gr.id = current_grader_run_id()
     ));

   -- Similar policies for false_positives, snapshots, etc.

   -- Policy: Graders can only write their own grading results
   CREATE POLICY grader_write_results ON grader_runs
     FOR UPDATE TO grader_users
     USING (id = current_grader_run_id())
     WITH CHECK (id = current_grader_run_id());
   ```

3. Pass RLS-scoped credentials to grader container (not admin credentials)
   - Similar to how clustering passes scoped credentials
   - Ground truth would still be available via resources (now backed by RLS-restricted queries)

**Benefits:**
- Defense in depth: grader can't accidentally access wrong data
- Audit trail: database logs show which grader accessed what
- Consistent with other agent patterns (clustering, prompt optimizer)
- No code changes needed in grader logic (just credential swap + RLS setup)

**Related files:**
- `src/adgn/props/db/clustering_user_manager.py` - Reference implementation
- `src/adgn/props/db/prompt_optimizer_user_manager.py` - Another reference
- `src/adgn/props/db/temp_user_manager.py` - Base class

---

## N-to-M Matching with Credit Assignment

**Current state:** Grading stores per-occurrence results with matched_by (list of input issue IDs + credits).

**Improvements needed:**

### 1. Validation Constraints
Currently validation happens in `GraderSubmitServer.submit_result()` but could be enforced at database level:

**Credit constraints:**
- For each TP occurrence: `SUM(credit for all matches) <= 1.0`
- For each input issue: Can contribute to multiple TPs (no constraint)
- Currently validated in Python; could add CHECK constraints or triggers

**Completeness constraints:**
- Every catchable TP occurrence must have a result (currently validated)
- Every input issue must be either:
  - Matched to at least one TP (with nonzero credit), OR
  - Listed as an unknown
- No overlaps: an input issue cannot be both matched AND unknown (currently validated)

### 2. Unknown Issues Workflow

**Current state:** Unknowns are stored in `GraderSuccess.unknowns` as a list with rationales.

**Desired workflow:**
1. **Grader identifies unknowns:** Input critique issues that don't match any canonical TP or FP
   - Current: stored per grader run
   - Each unknown has `input_id` + `rationale` explaining why it doesn't match

2. **Cross-critique clustering:** After multiple grader runs, cluster unknowns across critiques
   - Similar to existing clustering infrastructure
   - Group unknowns that represent the same underlying issue
   - Example: Multiple critics found "missing error handling" but phrased differently

3. **Human labeling workflow:**
   - Present clustered unknowns to human reviewer
   - Reviewer decides for each cluster:
     - Add as new canonical TP (was genuinely missed in original ground truth)
     - Add as new canonical FP (is actually acceptable pattern)
     - Mark as noise/invalid (critic hallucinated or misunderstood)
   - Update ground truth accordingly

4. **Re-grading:** After ground truth updates, optionally re-grade affected critiques
   - Previous unknowns might now match new canonical issues
   - Recall metrics would improve retroactively

**Implementation considerations:**
- Store unknowns in separate table with foreign keys to grader runs
- Add clustering table for grouped unknowns (similar to existing clustering schema)
- Add human labeling table for decisions
- Track ground truth provenance (which issues came from human labeling vs original authoring)

**Database schema additions needed:**
```sql
-- Unknowns table (extract from JSONB to first-class rows)
CREATE TABLE grader_unknowns (
  id uuid PRIMARY KEY,
  grader_run_id uuid REFERENCES grader_runs(id),
  input_issue_id text NOT NULL,  -- InputIssueID from critique
  rationale text NOT NULL,
  -- Could add: embedding vector for similarity search
);

-- Clustered unknowns (cross-run grouping)
CREATE TABLE unknown_clusters (
  id uuid PRIMARY KEY,
  representative_unknown_id uuid REFERENCES grader_unknowns(id),
  created_at timestamptz DEFAULT now(),
);

CREATE TABLE unknown_cluster_members (
  cluster_id uuid REFERENCES unknown_clusters(id),
  unknown_id uuid REFERENCES grader_unknowns(id),
  similarity_score float,  -- How strongly this unknown matches the cluster
  PRIMARY KEY (cluster_id, unknown_id)
);

-- Human labeling decisions
CREATE TABLE unknown_labeling_decisions (
  id uuid PRIMARY KEY,
  cluster_id uuid REFERENCES unknown_clusters(id),
  decision text NOT NULL CHECK (decision IN ('new_tp', 'new_fp', 'noise')),
  rationale text,
  labeled_by text,  -- User who made the decision
  labeled_at timestamptz DEFAULT now(),
  -- If new_tp or new_fp, link to the created ground truth item
  created_tp_id text,  -- References true_positives.tp_id
  created_fp_id text,  -- References false_positives.fp_id
);
```

**UI considerations:**
- Labeling interface for reviewing clustered unknowns
- Display context: show original code, critique rationale, similar canonical issues
- Batch operations: label entire cluster at once
- Track labeling progress: which clusters need review

---

## Related Work

See also:
- `src/adgn/props/db/clustering_user_manager.py` - RLS pattern for isolated agents
- `src/adgn/props/noop_classifier/` - Clustering infrastructure (might be reusable)
- `src/adgn/props/db/migrations/versions/*_clustering*.py` - Clustering schema migrations
