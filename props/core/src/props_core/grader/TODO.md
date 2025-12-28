# Grader TODOs

## RLS-Secured Database Access (DONE)

**Completed:** Grader now uses unified `TempUserManager` with `agent_{uuid}` pattern.

- Username pattern: `agent_{agent_run_id}` (unified for all agent types)
- Grants `agent_base` role to temporary users
- RLS policies use `current_agent_run_id()` and `current_agent_type()` for scoping

**Related files:**
- `src/adgn/props/db/temp_user_manager.py` - Unified user manager

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
- Store unknowns in separate table with foreign keys to agent runs
- Add clustering table for grouped unknowns (similar to existing clustering schema)
- Add human labeling table for decisions
- Track ground truth provenance (which issues came from human labeling vs original authoring)

---

## Related Work

See also:
- `src/adgn/props/db/temp_user_manager.py` - Unified user manager for all agent types
- `src/adgn/props/clustering/` - Clustering infrastructure
- `src/adgn/props/db/migrations/versions/*_clustering*.py` - Clustering schema migrations
