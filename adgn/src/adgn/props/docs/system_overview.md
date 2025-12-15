# System Overview: Props Training & Evaluation

This document explains the core architecture of the properties evaluation system for agents operating within the system.

## Critical Context: Subjective Dataset

**This dataset reflects ONE person's subjective code review preferences.**

The ground truth issues (true positives and false positives) were hand-labeled by a single individual based on their personal taste - NOT generic best practices, industry standards, or automated tool output. This is behavior-cloning training data.

**What this means for optimization:**
- The "right answer" is whatever this person would flag in their code review
- Their preferences may differ from your prior beliefs about code quality
- You must read the training data to understand their specific standards
- Query `true_positives` and `false_positives` tables to learn what they care about

**Learning strategy:** Don't assume you know what "good code" means. Study the labeled examples, read the rationales, internalize the subjective standards. The goal is to replicate THIS person's judgment, not to apply generic rules.

## Dataset Structure

### Snapshots

**Snapshot** = frozen code state at a specific commit + labeled ground truth issues (TPs and FPs)

- Example: `ducktape/2025-11-26-00` → commit `ab7e9d6...` with 58 known issues
- Each snapshot has:
  - Source reference (git commit or bundle path)
  - Associated TPs and FPs stored in the database
  - Source code hydrated on-demand from the source reference
- Immutable training data (like ImageNet labels)

**Your Access:** Only the specific training snapshots relevant to your task are mounted read-only at `/snapshots/<slug>/`
- Example: If working with `ducktape/2025-11-26-00`, you'll find source code at `/snapshots/ducktape/2025-11-26-00/`
- Not all training snapshots are mounted - only those for examples you're analyzing
- Access to validation/test snapshots depends on your agent's role and database permissions (see "Data Access Patterns" section below)

### Training Examples

**Training Example** = `(snapshot, targeted_files)` pair

- **Input:** Which files should the critic review?
- **Ground truth:** Which TPs are catchable + which FPs are relevant (computed from targeted_files)

**Example types:**
- **Single-file:** Review just `server.py` (easiest)
- **Multi-file:** Review `types.py` + `persist.py` (medium - check for duplication)
- **Full-snapshot:** Review ALL files with issues (hardest - comprehensive review)

**True Positive (TP):** Real issue that should be flagged (according to this person's judgment)
- Has `expect_caught_from`: minimal file sets needed to DETECT the issue
- Example: duplication in A+B → `expect_caught_from: [[A], [B]]` (seeing EITHER file should trigger search)
- **Detection Standard:** "If a competent reviewer sees these files and does a thorough review, would they reasonably catch this?"

**False Positive (FP):** Pattern that should explicitly NOT be flagged (even if it looks problematic)
- Example: Duplication for visual consistency in UI components - looks like it should be refactored, but this person considers it acceptable
- **Purpose:** Teach the critic to avoid flagging patterns this person accepts
- Query the `false_positives` table to learn which patterns should be ignored

### Splits

**Train split:** Used for prompt development and analysis
- Accessible ground truth (TPs, FPs, execution traces)
- Mix of single-file, multi-file, and full-snapshot examples
- Can inspect critic runs, grader results, tool call sequences

**Valid split:** Used for held-out evaluation
- Ground truth is NOT directly accessible to optimization agents
- **Example visibility depends on optimization mode:**
  - **Whole-Repo Mode**: ONLY full-snapshot examples; examples table is RLS-blocked (black-box validation, no filenames visible)
  - **Targeted Mode**: Both per-file and full-snapshot examples; examples table is accessible (filenames visible, but ground truth still hidden)
- Can run evaluations and see metrics, but not inspect failures in detail (execution traces always hidden)

**Test split:** Final evaluation (rarely used during development)

### Optimization Modes

The prompt optimizer supports two terminal metric modes that control validation data access. Both modes require explicit selection via CLI flag.

**Whole-Repo Mode:**
- **Philosophy:** Black-box validation - agent only sees aggregate recall, no filenames
- **Trade-off:** More realistic generalization test, but harder to debug failures
- **Validation examples:** Only full-snapshot (comprehensive review)
- **Query method:** `get_validation_run_aggregates()` SECURITY DEFINER function (returns per-run results)
- **Data access:** Examples table is RLS-blocked for VALID split (no filenames visible)
- **Use case:** Final evaluation, measuring true generalization without risk of overfitting

**Targeted Mode:**
- **Philosophy:** White-box iteration - agent can see filenames and target specific files
- **Trade-off:** Easier to iterate on specific patterns, but risk of overfitting to validation
- **Validation examples:** Both per-file and full-snapshot (same as TRAIN split)
- **Query method:** `aggregated_recall_by_prompt` view (pre-aggregated stats with n_examples, UCB, LCB)
- **Data access:** Examples table is accessible for VALID split (filenames visible, ground truth still hidden)
- **Use case:** Rapid iteration, debugging specific patterns, earlier optimization stages
- **IMPORTANT:** Always check `n_examples >= 5` before trusting metrics (small samples = high variance)

**Key difference:** Whole-repo mode enforces stronger anti-overfitting guarantees by hiding validation example structure entirely. Targeted mode allows faster iteration but requires discipline to avoid overfitting.

## Database Schema

### Core Tables

**`examples`:**
- **Composite primary key:** `(snapshot_slug, files_hash)`
- **No `.id` or `.key` attribute** - use the tuple to identify examples
- Attributes: `snapshot_slug`, `files_hash`, `files` (list of file paths)
- Split information comes from the related `Snapshot` (via `snapshot_obj.split`)
- Query pattern: `.filter_by(snapshot_slug=slug, files_hash=hash)`

**`prompts`:**
- `prompt_sha256` (primary key) - content-addressed by SHA256 hash
- `prompt_text` - full prompt content

**`critic_runs`:**
- Links to: `prompt_sha256`, `snapshot_slug`, `critique_id`, `transcript_id`
- `output` - discriminated union: `DBCriticSuccess | DBCriticMaxTurnsExceeded | ...`
- `files`, `files_hash` - which files were reviewed

**`critiques`:**
- `id` (primary key)
- `snapshot_slug` - which snapshot was reviewed
- `payload` - the issues found (`DBCriticSubmitPayload`)

**`grader_runs`:**
- Links to: `critique_id`, `snapshot_slug`, `transcript_id`
- `output` - discriminated union: `DBGraderSuccess | DBGraderMaxTurnsExceeded`
- When successful, `output.occurrence_results` contains per-occurrence credits (found_credit 0.0-1.0 for each TP occurrence)
- For aggregate recall metrics, query database views: `aggregated_recall_by_prompt`, `aggregated_recall_by_example`

**`events`:**
- Tool call traces from agent execution
- Links to: `transcript_id`, `sequence_num`
- `event_type` - e.g., "tool_call", "function_call_output", "assistant_text", "reasoning"
- `payload` - structured event data (discriminated union: `EventType`)
- Reasoning summaries: Events with `event_type = "reasoning"` contain `payload.summary` (list of summary text items)

**`true_positives`, `false_positives`:**
- Ground truth issues for each snapshot
- Used by grader to compute recall

## Evaluation Flow

### 1. Critic Run

**What the critic sees:**
- Source code mounted at `/workspace` (read-only)
- System prompt with task description
- MCP tools for code analysis

**What the critic DOES NOT see:**
- Ground truth issues (TPs/FPs)
- Expected output or "answers"
- Grader feedback or metrics

**Critic's task:** Review code, report issues (upsert_issue + add_occurrence), and call submit when done

**Output:** A `Critique` object with a list of reported issues (only if submit was called)

### 2. Grader Run

**Input:** Critique from critic + ground truth from snapshot

**Process:**
1. Match reported issues to TPs (true positives)
2. Check for FPs (false positive triggers)
3. Compute metrics based on coverage

**Output:** `DBGraderSuccess` with:
- `occurrence_results` = per-occurrence credits (list of `{tp_id, occurrence_id, found_credit, matched_by, rationale}`)
- `unknowns` = input issues with novel aspects not matched to canonical issues
- `summary` = high-level observations

**Key change:** No single `recall` field - use occurrence-level data directly or query aggregate views.

### 3. Metrics

**Terminal Metric (what we ultimately optimize for):**
- **Full-snapshot runs on VALIDATION split**
- Total number of issues caught when critic reviews ALL files in a validation snapshot
- Expressed as recall: issues found / total issues (0.0-1.0)
- This tests comprehensive whole-codebase review ability on held-out data

**Training Metrics (for hill-climbing during optimization):**
- Per-file and multi-file examples on TRAIN split
- Easier to see "you missed this specific issue in this file"
- Enable faster iteration and targeted improvements
- Not the terminal goal - just intermediate training signal

**Computation:**
- Single-run recall: `sum(occ.found_credit for occ in occurrence_results) / len(occurrence_results)`
- Cross-run aggregates: Query `aggregated_recall_by_prompt` or `aggregated_recall_by_example` views
- Terminal metric: Query view with `WHERE split='valid' AND is_whole_snapshot=true`

**Weighting by occurrence (not by example):**
- Cross-run recall: For each occurrence, average its found_credit across runs; then sum those averages and divide by occurrence count
- Formula: `SUM(AVG(found_credit) per occurrence) / COUNT(occurrences)`
- Examples with more TP occurrences naturally weight more in the aggregate
- Example: If example A has 20 occurrences and example B has 5 occurrences, A has 4x the weight of B in aggregated metrics
- This measures "total issues found / total issues in dataset" rather than "average per-example recall"
- Within a single snapshot, different examples can have vastly different numbers of occurrences (e.g., 100 occurrences across 10 files vs 1 occurrence in 1 file)

**Failure cases count as zero-recall:** When a critic exceeds max_turns or context limits, no valid critique is produced. These failures count as zero-recall runs because the optimized prompt should make the critic perform well within resource constraints.

**Secondary metrics:**
- `LCB` (Lower Confidence Bound) = mean - σ/√n (penalizes variance)
- `Z%` = percentage of runs with zero recall (includes max_turns/context failures)
- `S%` = percentage of runs that hit max_turns without submitting
- `C%` = percentage of runs that exceeded context limits

## Critic Agent Architecture

### Container Environment

**Mounted paths:**
- `/workspace` - snapshot source code (read-only)
- `/tmp` - writable scratch space

**No network access** - isolated evaluation environment

**MCP Tools available:**
- `docker_exec` - run commands in container (rg, ruff, mypy, vulture, etc.)
- `critic_submit_upsert_issue` - create/update issue header
- `critic_submit_add_occurrence` - add code location for an issue
- `critic_submit_add_occurrence_files` - add multi-file occurrence
- `critic_submit_cancel_issue` - remove an issue
- `critic_submit_submit` - finalize critique

### Key Constraints

**Critic cannot see:**
- Ground truth issues
- Other critiques or grader feedback
- The database or any stored results

**Critic only sees:**
- The source code to review
- Its own system prompt
- Tool output from analysis commands

**This is intentional:** We're testing if the critic can identify issues from code alone, just like a human reviewer would.

## Data Access Patterns

### For Training Split

**Full access to everything:**
```python
# Get examples (must join with Snapshot to filter by split)
examples = session.query(Example).join(Snapshot).filter(Snapshot.split == "train").all()

# Get critic runs with grader results
critic_run = session.query(CriticRun).get(critic_run_id)
grader_run = session.query(GraderRun).filter_by(critique_id=critique_id).first()

# Access ground truth
tps = session.query(TruePositive).filter_by(snapshot_slug=slug).all()

# Read execution traces
events = session.query(Event).filter_by(transcript_id=transcript_id).order_by(Event.sequence_num).all()

# Filter for reasoning summaries
reasoning_events = session.query(Event).filter_by(
    transcript_id=transcript_id,
    event_type="reasoning"
).order_by(Event.sequence_num).all()
# Access summary text: reasoning_events[0].payload.summary (list of ReasoningSummaryItem)
```

### For Validation Split

**Access varies by optimization mode and agent role:**
- Some agents may have NO access to validation data
- Prompt optimizer agents have mode-specific access (see below)
- Access level is enforced via RLS policies based on agent credentials

**Whole-Repo Mode (default, black-box validation):**
```python
# Can run critic on validation whole-snapshot only
result = await run_critic_on_example(
    snapshot_slug="ducktape/2025-11-26-01",  # valid split
    files_hash=None,  # whole-snapshot required (RLS blocks per-file)
    prompt_sha256=prompt_hash,
    max_turns=30
)

# Query aggregate metrics via SECURITY DEFINER function
from sqlalchemy import text
results = session.execute(text("""
    SELECT * FROM get_validation_run_aggregates()
    WHERE prompt_sha256 = :hash
"""), {"hash": prompt_hash})

# CANNOT see examples table (RLS blocked)
# CANNOT inspect ground truth, execution traces, or failure patterns
```

**Targeted Mode (allows per-file validation iteration):**
```python
# Can see example filenames
examples = session.query(Example).join(Snapshot).filter(Snapshot.split == "valid").all()

# Can run both per-file and whole-snapshot evaluations
result = await run_critic_on_example(
    snapshot_slug="ducktape/2025-11-26-01",
    files_hash=example.files_hash,  # per-file allowed
    prompt_sha256=prompt_hash,
    max_turns=30
)

# Query aggregate metrics via views
results = session.execute(text("""
    SELECT recall, n_examples, ucb, lcb
    FROM aggregated_recall_by_prompt
    WHERE prompt_sha256 = :hash AND split = 'valid'
"""), {"hash": prompt_hash})

# Can see filenames but CANNOT inspect ground truth or execution traces
# Always check n_examples >= 5 for reliability; use UCB/LCB for uncertainty
```

## Common Pitfalls

### 1. Example Identity

❌ **Wrong:** `example.id` or `example.key` (doesn't exist)
✅ **Right:** `(example.snapshot_slug, example.files_hash)`

### 2. Output Access

❌ **Wrong:** `critic_run.output.get("tag")` (discriminated union, not dict)
✅ **Right:** `critic_run.output.tag` and `isinstance(critic_run.output, DBCriticSuccess)`

### 3. Validation Inspection

❌ **Wrong:** Reading validation ground truth or execution traces
✅ **Right:** Only run evaluations and see metrics (recall)

### 4. Critic Knowledge

❌ **Wrong:** Assuming critic sees ground truth or properties
✅ **Right:** Critic only sees source code and system prompt
