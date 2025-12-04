# Props Run Management: Implementation Plan

## Remaining Work 🎯

### High Priority

1. **Convert lint_issue to proper run structure**
   - Currently: Writes to `logs/mini_codex/lint_issue/run_{ts}_{pid}/events.jsonl`
   - Should: Follow 3-file pattern in runs/ structure
   - Target: `runs/lint_issue/specimen:{slug}/{issue_id}/{timestamp}/` with input.json (IssueCore+Occurrence), output.json (LintSubmitPayload), events.jsonl
   - Structure: issue_id as path component under specimen scope
   - Note: snapshot exec is just a Docker shell command (no agent, no outputs needed)

### Eval Harness

2. **Implement _load_samples() in eval_harness.py**
   - Current: Returns empty list with TODO comment - no evaluation cases defined
   - Should: Populate with actual IssueEvalSpec instances from git-tracked spec files
   - Specs/test cases stay in git (not database)
   - Needs:
     - Select representative specimens and issues for evaluation
     - Define expectations per occurrence (anchor windows, rationale rubrics, findings matchers)
     - Create IssueEvalSpec instances with OccurrenceCase objects
   - Example structure: For specimen "ducktape/2025-11-20-adgn" + issue "dead-code", define 3-5 cases with different code patterns and expected ranges
   - Benefits: Enables automated quality checks on linter output

### Medium Priority

3. **Mypy cleanup in other modules**
  - `bundles/build_bundle.py`: typing issues with pygit2
  - `cli_app/main.py`, `specimens/registry.py`: `_jsonnet` stubs
  - These are pre-existing, not blocking current work

4. **Test coverage improvements**
   - Tests for lint_issue structure conformance
   - Tests for eval harness when samples are added

## Path Construction Audit

All places that construct paths in the props codebase, classified by action needed:

### 🔧 NEEDS FIXING - Path Antipatterns

1. **lint_issue.py lines 462-463**
   - `Path.cwd() / "logs" / "mini_codex" / "lint_issue"`
   - Action: 🔧 Convert to proper run structure (Task #1)
   - Target: Use LintIssueRun manager → `runs/lint_issue/specimen:{slug}/{issue_id}/{timestamp}/`

2. **agent_runner.py lines 48-49**
   - `Path.cwd() / "logs" / "mini_codex" / "agent_runner"`
   - Action: ✅ Keep as-is (utility function for ad-hoc prompt testing, not formal runs)

### ✅ CORRECT - Non-Runs Path Construction

3. **cluster_unknowns.py line 190**
   - `out_root / "clusters.json"`
   - Action: ✅ Keep as-is (cluster output structure is defined by RunsContext)

4. **specimens/registry.py** (multiple lines)
    - Specimen manifest and source path resolution
    - Action: ✅ Keep as-is (specimen registry, not runs management)

5. **bundles/build_bundle.py** (multiple lines)
    - Bundle creation paths
    - Action: ✅ Keep as-is (build tooling, not runs management)

6. **cli_app/main.py lines 229, 670**
    - `Path(tempfile.gettempdir()) / "adgn_codex_prompts"`
    - Action: ✅ Keep as-is (temporary prompt storage for debugging)

7. **cli_app/main.py lines 294, 354, 360, 375, 379, 534, 551**
    - Various output files within run directories (results.json, prompt.txt, etc.)
    - Action: ✅ Keep as-is (writing artifacts within RunsContext-derived directories)

### Summary Statistics

- ✅ **Correct (Keep as-is)**: 6 locations
- 🔧 **Needs fixing**: 1 location
  - Task #1 (lint_issue conformance): lint_issue.py:462-463

### Future Enhancements

5. **Replace git subprocess calls with pygit2 API**
   - `specimens/registry.py`: `_create_archive_from_git()` uses subprocess calls
   - Should use pygit2 library directly for git operations
   - Benefits: Better error handling, no shell injection risk, cleaner code

6. **Refactor hierarchical slug extraction pattern**
   - Multiple functions extract slug from `manifest_path.parent.name` / `manifest_path.parent.parent.name`
   - Pattern: `repo_name = specimen_dir.parent.name; specimen_name = specimen_dir.name; slug = f"{repo_name}/{specimen_name}"`
   - Candidate for helper function to centralize and validate slug derivation

## Directory Structure

```
runs/
  cluster/                    # Cluster unknowns workflow
    YYYYMMDD_HHMMSS/
      {project}/{date}/       # Per-specimen cluster outputs
        clusters.json

  prompt_optimize/            # Prompt optimization sessions (nested by timestamp)
    YYYYMMDD_HHMMSS/

  lint_issue/                 # Lint issue runs (per specimen + issue + occurrence)
    specimen:{project}/{date}/
      {issue_id}/
        YYYYMMDDTHHMMSS/
          input.json          # IssueCore + Occurrence
          output.json         # LintSubmitPayload
          events.jsonl        # Agent transcript
```

### Key Principles

1. **Specimen slugs**: Always `{project}/{date}` (validated by Pydantic)
2. **Database for runs**: Critic and grader runs stored in database tables, not file paths
3. **File-based workflows**: Cluster, prompt optimization, and lint issue use file-based structure

## Key Files

- **`db/models.py`**: Database models for CriticRun, GraderRun, Critique, Specimen, etc.
- **`critic.py`**: Critic models (CriticScope, CriticInput, CriticOutput) and run_critic() function
- **`grader.py`**: Grader models (GraderInput, GraderOutput) and grade_critique_by_id() function
- **`cluster_unknowns.py`**: Discovery and clustering workflow
- **`prompt_optimizer.py`**: Prompt optimization workflow with MCP server
- **`runs_context.py`**: Timestamp helpers and remaining file-based path derivation
- **`splits.py`**: Specimen→split lookup

### Domain-Driven Reorganization (Completed)

**Models moved to domain homes:**
- `CriticScope`, `CriticInput`, `CriticOutput` → `critic.py`
- `GraderInput`, `GraderOutput` → `grader.py`
- Deleted `run_models.py` (models now live with their domain logic)

**Functions moved to domain homes:**
- `run_critic()` → `critic.py` (from run_managers.py)
- `run_grader()` → `grader.py` (from run_managers.py)
- `grade_critique_by_id()` → `grader.py` (from grade_runner.py)
- Deleted `run_managers.py` and `grade_runner.py`

**Database migration:**
- Critic/grader runs now stored in database tables (`critic_runs`, `grader_runs`, `critiques`, `events`)
- Removed file-based path management for critic/grader workflows
- `prompt_eval/server.py` merged into `prompt_optimizer.py` following domain-driven pattern
