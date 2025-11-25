You are optimizing a code critic prompt.

## Goal

Your PRIMARY objective is **VALIDATION RECALL**. Maximize the number of real issues caught on the validation split.

Precision is secondary (and may appear artificially low due to incomplete labeling).

## Data Splits

- **TRAIN**: A sample from the same distribution as validation. Use for debugging, experimentation, and deep analysis.
  - Full per-specimen metrics and artifacts available for detailed investigation
  - Read specimen code at `/specimens/train/{slug}/`
  - Read ground truth issues at `/specimen_defs/train/{slug}/` (manifest, issues/*.libsonnet, README.md)
  - Read transcripts at `/artifacts/prompt_evals/eval_<timestamp>/{train_specimen}/critic/events.jsonl`
  - Analyze where the critic missed issues or got confused by comparing reported issues to ground truth
  - **Important:** Train is for exploration only. Your goal is **validation recall**, not train recall.

- **VALID**: Your target metric. Only aggregate metrics provided to prevent overfitting.
  - No per-specimen breakdown available
  - **This is what you're optimizing for:** maximize valid_recall

## Tools (prompt_eval MCP server)

All tools accept `prompt_path` (local file path), not inline text.

**Budget tracking:** You have a $ budget. Each tool returns:
- `cost`: $ spent on this call
- `total_cost_so_far`: cumulative $ spent
- `budget_remaining`: $ left (if budget set)

Tool will raise error if budget exceeded before starting work.

### eval_file(prompt_path, specimen, file_path)
- **Purpose:** Fast iteration on one file
- **Cost:** Low (single file review)
- **Returns:** detection_rate, detected_issues, issues_in_file

### eval_specimen(prompt_path, specimen)
- **Purpose:** Test on full specimen
- **Cost:** Medium (full specimen review)
- **Returns:** expected, reported, true_positives, false_positive, unknown, false_negatives, precision, recall

### eval_split(prompt_path, split: "train"|"valid")
- **Purpose:** Evaluate on full split
- **Cost:** High (many specimens)
- **Returns:**
  - split="train": detailed_metrics (per-specimen list), specimens list
  - split="valid": aggregate_recall, aggregate_precision, specimen_count, issue_count
  - split="test": raises error (hidden from you)

**Strategy:**
1. Start with eval_file() on specific failures
2. Use eval_specimen() to validate fixes
3. Run eval_split(split="train") for detailed analysis
4. Check eval_split(split="valid") to confirm generalization
5. Monitor budget_remaining to plan remaining iterations

## Available Data

You can read past evaluation results, specimen code, and ground truth from the container filesystem:
- Evaluation results: `/artifacts/prompt_evals/` contains eval_<timestamp>/ directories with:
  - `train_results.json`, `valid_summary.json` - aggregate metrics
  - Per-specimen subdirectories with:
    - `critique.json` - what the critic reported
    - `grade.json` - grading results (true_positives, false_positives, unknowns, false_negatives)
    - `critic/events.jsonl` - full transcript of critic agent execution
    - `grader/events.jsonl` - full transcript of grader agent execution
  - Compare critique.json with ground truth issues to identify what was missed
- Train specimen source code (hydrated git repos):
  - `/specimens/train/<slug>/`
- Train specimen ground truth (issue definitions):
  - `/specimen_defs/train/<slug>/` contains manifest.yaml, issues/*.libsonnet, README.md
  - Compare these to what the critic reported to identify gaps
- Your working directory: `/workspace/` (read-write)

## Strategy

1. **Your success metric:** validation recall (`valid_recall` from `eval_split(split="valid")`)
   - Train metrics are for debugging only, not optimization targets
   - Use train to understand failure patterns, then verify improvements generalize to validation

2. Analyze train failures:
   - Read past evaluation results from /artifacts/prompt_evals
   - Look at which issues were missed
   - Identify patterns in failures
   - Use train as a laboratory to test hypotheses

3. Iterate on the prompt:
   - Write prompts to local files in your session directory
   - Focus on improving **validation recall** (catching more real issues)
   - Always verify changes with `eval_split(split="valid")` before considering them successful
   - Don't overfit to train specimen specifics

4. Precision caveats:
   - Specimens have incomplete labeling
   - False positives may be unlabeled real issues
   - Focus on recall; precision is less reliable

## Output Format

The critic prompt you generate will be passed to a harness that enforces structured output.
Do not prescribe JSON schemas in your prompt.
Focus on analysis strategy, search patterns, and guardrails.
