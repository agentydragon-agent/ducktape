-- Clustering Agent SQL Examples
-- Run via: psql -c "SQL_QUERY_HERE"

--------------------------------------------------------------------------------
-- 1. GET YOUR RUN INFO
--------------------------------------------------------------------------------

-- Current user's run_id (extracted from username)
SELECT current_agent_run_id();

-- Your run details
SELECT * FROM agent_runs WHERE agent_run_id = current_agent_run_id();

-- Get your snapshot slug
SELECT type_config->'example'->>'snapshot_slug' AS snapshot_slug
FROM agent_runs
WHERE agent_run_id = current_agent_run_id();

--------------------------------------------------------------------------------
-- 2. DISCOVER UNKNOWNS
--------------------------------------------------------------------------------

-- Get grader runs for your snapshot
SELECT ar.agent_run_id
FROM agent_runs ar
WHERE ar.type_config->>'agent_type' = 'grader'
  AND EXISTS (
    SELECT 1 FROM agent_runs critic
    WHERE critic.agent_run_id::text = ar.type_config->>'graded_agent_run_id'
      AND critic.type_config->'example'->>'snapshot_slug' = (
        SELECT type_config->'example'->>'snapshot_slug' FROM agent_runs WHERE agent_run_id = current_agent_run_id()
      )
  );

-- Get unknown issues from grading decisions (not yet assigned)
SELECT
    gd.agent_run_id AS grader_run_id,
    gd.input_issue_id AS unknown_id
FROM grading_decisions gd
WHERE gd.target_tp_id IS NULL  -- Unknown (not matched to TP)
  AND NOT EXISTS (
      SELECT 1 FROM unknown_assignments ua
      WHERE ua.grader_run_id = gd.agent_run_id
        AND ua.unknown_id = gd.input_issue_id
        AND ua.cancelled_at IS NULL
  );

--------------------------------------------------------------------------------
-- 3. CREATE CLUSTERS
--------------------------------------------------------------------------------

-- Create a new cluster
INSERT INTO unknown_clusters (agent_run_id, cluster_name, description)
VALUES (
    current_agent_run_id(),
    'unused-test-imports',
    'Unused imports in test files that should be removed'
);

-- List all clusters for current run
SELECT * FROM unknown_clusters ORDER BY cluster_name;

--------------------------------------------------------------------------------
-- 4. ASSIGN UNKNOWNS
--------------------------------------------------------------------------------

-- Assign unknown to a cluster
INSERT INTO unknown_assignments (agent_run_id, grader_run_id, unknown_id, cluster_id, rationale)
VALUES (
    current_agent_run_id(),
    'a1b2c3d4-...'::uuid,  -- Replace with actual grader_run_id
    'input-issue-5',       -- Replace with actual unknown_id
    (SELECT id FROM unknown_clusters WHERE cluster_name = 'unused-test-imports' AND agent_run_id = current_agent_run_id()),
    'Unused import of typing.cast in test_utils.py:15, same pattern as other test file imports'
);

-- Map to existing true positive
INSERT INTO unknown_assignments (agent_run_id, grader_run_id, unknown_id, mapped_tp_id, rationale)
VALUES (
    current_agent_run_id(),
    'a1b2c3d4-...'::uuid,
    'input-issue-7',
    'dead-code-unused-helper',  -- Existing TP ID
    'This is the same dead code issue as TP dead-code-unused-helper (unused _format_date helper)'
);

--------------------------------------------------------------------------------
-- 5. CHECK PROGRESS
--------------------------------------------------------------------------------

-- Count assigned vs total
SELECT
    (SELECT COUNT(*) FROM unknown_assignments WHERE agent_run_id = current_agent_run_id() AND cancelled_at IS NULL) AS assigned;

-- Get active assignments
SELECT * FROM unknown_assignments
WHERE cancelled_at IS NULL
ORDER BY created_at;

--------------------------------------------------------------------------------
-- 6. CORRECT MISTAKES
--------------------------------------------------------------------------------

-- Cancel an assignment
UPDATE unknown_assignments
SET cancelled_at = NOW(), cancellation_reason = 'Wrong cluster, should be in validation-duplicates'
WHERE id = 42;

-- Then create a new assignment (UNIQUE constraint allows it after cancellation)

--------------------------------------------------------------------------------
-- 7. REFERENCE DATA LOOKUPS
--------------------------------------------------------------------------------

-- Check TP definition before mapping
SELECT * FROM true_positives WHERE snapshot_slug = 'ducktape/2025-11-26-00' AND tp_id = 'dead-code-unused-helper';

-- Check FP definition before mapping
SELECT * FROM false_positives WHERE snapshot_slug = 'ducktape/2025-11-26-00' AND fp_id = 'visual-consistency-duplication';
