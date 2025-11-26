You are optimizing a code critic prompt.

## Goal

Given your budget, produce the best critic prompt you can. **Your success metric is validation recall** - maximize the number of real issues caught on the validation split.

Build on existing results in `/artifacts/prompt_evals/` to accelerate improvement and conserve budget. Learn from what worked (and didn't work) in previous runs.

Precision is secondary (and may appear artificially low due to incomplete labeling).

## Target Agent Capabilities

The coding agent you're optimizing prompts for is a **GPT-5-level coding agent** with the following capabilities:

**Performance benchmarks:**
- **SWE-bench Verified**: 74.9% (real-world software engineering tasks - given a code repository and issue description, generate a patch to solve it)
- **Aider Polyglot**: 88% (code editing across multiple languages)
- **HumanEval**: ~90% (function synthesis from docstrings)
- **Low hallucination rate**: ~6x fewer hallucinations than o3 in long-form technical content

**Execution capabilities:**
- **Full code execution**: Can execute Python code and run arbitrary commands
- **Same Docker environment**: Has access to the same Docker image you're running in, including:
  - All installed analysis tools (ruff, mypy, vulture, jscpd, etc.)
  - Python environment with all available packages
  - Command-line utilities and tools
- **File system access**: Can read specimen code and run tools against it

**What this means for your prompts:**
- The agent can understand complex multi-step analysis procedures
- It can run static analysis tools and programmatically parse their outputs
- It has strong code understanding and can identify subtle issues
- You can prescribe sophisticated workflows combining multiple tools and reasoning steps
- The agent is highly capable but not perfect - clear structure and explicit guidance still matter

## Data Splits

**Important:** Train, validation, and test splits may contain specimens from different codebases, different files, and even different programming languages. Do not assume all specimens share the same structure, conventions, or language features. Your prompt must generalize across diverse codebases.

- **TRAIN**: A sample for debugging, experimentation, and deep analysis.
  - Full per-specimen metrics and artifacts available for detailed investigation
  - Read specimen code at `/specimens/train/{slug}/`
  - Read ground truth issues at `/specimen_defs/train/{slug}/` (manifest, issues/*.libsonnet, README.md)
  - Read transcripts at `/artifacts/prompt_evals/eval_<timestamp>/{train_specimen}/critic/events.jsonl`
  - Analyze where the critic missed issues or got confused by comparing reported issues to ground truth
  - **Important:** Train is for exploration only. Your goal is **validation recall**, not train recall.
  - **Avoid overfitting:** Don't optimize for patterns specific to train specimens (file names, directory structure, coding style). Validation may be completely different codebases.

- **VALID**: Your target metric. Only aggregate metrics provided to prevent overfitting.
  - No per-specimen breakdown available
  - **This is what you're optimizing for:** maximize valid_recall
  - Validation specimens may be from entirely different projects/languages than train

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

## Approach Guidance

**Budget management:**
- You have limited budget - spend it wisely
- Explore existing results in `/artifacts/prompt_evals/` first to learn from past runs
- Use cheap tools (eval_file, eval_specimen) for experimentation
- Run expensive eval_split only when you have a promising candidate

**Learning from past work:**
- Check `/artifacts/prompt_evals/eval_<timestamp>/` directories for previous runs
- Compare validation metrics across runs to find the best baseline
- Read the best prompt from `prompt.txt` and understand what made it effective
- Analyze failure patterns from train results to identify improvement opportunities

**Iteration strategy:**
- Write prompts to `/workspace/` (e.g., `/workspace/prompts/v1.txt`)
- Test hypotheses cheaply on train specimens first
- Verify improvements on validation before considering them successful
- Avoid overfitting to train specifics - generalization to validation is what matters

**Metrics interpretation:**
- **Validation recall** is your optimization target
- Train recall is for debugging only, not the goal
- Precision may be misleadingly low due to incomplete labeling
- Unknown detections might be real issues that weren't labeled

## Output Format

The critic prompt you generate will be passed to a harness that enforces structured output.
Do not prescribe JSON schemas in your prompt.
Focus on analysis strategy, search patterns, and guardrails.
