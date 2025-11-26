You are optimizing a code critic prompt.

## Goal and Evaluation Setup

**Your ultimate goal: maximize recall on a hidden test set of unseen specimens.**

You are optimizing a prompt to catch code quality issues. The evaluation setup has three splits:

- **TRAIN**: For exploration and debugging. Use this to understand failure modes and test hypotheses. Train recall is NOT your goal.
- **VALID**: Your proxy metric. Use this to estimate how well your prompt generalizes. **Optimize for validation recall.**
- **TEST**: Hidden from you. No queries allowed. This is the real evaluation set where your prompt will be finally judged.

**The challenge:** You must find a prompt that generalizes from train to valid to test. The splits may contain completely different codebases, languages, and issue types. Your prompt must capture general principles, not specimen-specific patterns.

**Success metric hierarchy:**
1. **Primary**: Test recall (hidden from you - validation is your proxy)
2. **Proxy**: Validation recall (what you optimize for)
3. **Debugging**: Train recall (for understanding, not the goal)
4. **Secondary**: Precision (may appear low due to incomplete labeling)

Build on existing results in `/artifacts/prompt_evals/` to accelerate improvement and conserve budget. Learn from what worked (and didn't work) in previous runs.

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

## Prompt Engineering Best Practices

Based on official guidelines from OpenAI (GPT-5) and Anthropic (Claude), follow these principles:

### Core Principles

**1. Be Specific About Goals, Minimal About Means**
- Define the outcome precisely (what you want)
- Let the model choose how to get there (unless you have specific constraints)
- Bad: "Check the code"
- Good: "Identify dead code that is never called, considering entry points from tests, main functions, and public APIs"

**2. Optimize for Signal, Not Volume**
- Context has diminishing marginal returns
- Find the smallest set of high-value information that maximizes desired outcomes
- GPT-5-Codex uses ~40% fewer tokens than standard GPT-5 prompts
- Less is often better than more

**3. Eliminate Contradictions**
- Contradictory instructions waste reasoning tokens on reconciliation
- Test for ambiguities: If a human can't definitively resolve a conflict, neither can the agent
- Be consistent about priorities (recall > precision)

**4. Structure for Scannability**
- Use Markdown headers or XML tags to organize sections
- Typical structure: Goal → Method → Output Format → Constraints
- Makes long prompts easier for the model to navigate

### Workflow Design

**5. Prescribe Multi-Step Exploration**
- Bad: "Find issues" (agent jumps to conclusions)
- Good: "First, run static analysis tools. Then, read flagged files. Finally, synthesize findings."
- Exploration → Analysis → Synthesis pattern consistently outperforms one-shot approaches

**6. Provide Concrete Examples**
- Use diverse, canonical examples (not exhaustive edge cases)
- Examples are "pictures worth a thousand words" for LLMs
- Show both positive and negative examples when possible

**7. Define Clear Success Criteria**
- What counts as an issue vs. a style preference?
- When should the agent report vs. skip?
- Provide explicit decision criteria

### Avoiding Common Pitfalls

**8. Don't Overfit to Surface Patterns**
- Avoid specimen-specific cues (file names, directory structure)
- Focus on generalizable code quality principles
- Your validation set may be completely different projects/languages

**9. Don't Request Preambles for Code Tasks**
- GPT-5-Codex terminates prematurely if asked for preambles
- Get straight to analysis

**10. Balance Eagerness**
- Too eager: Wastes budget on exhaustive searches
- Too passive: Misses issues by stopping early
- Calibrate: "Explore systematically but terminate when confident"

### References

- GPT-5 Prompting Guide: https://cookbook.openai.com/examples/gpt-5/gpt-5_prompting_guide
- GPT-5-Codex Guide: https://cookbook.openai.com/examples/gpt-5-codex_prompting_guide
- Anthropic Context Engineering: https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
- Claude Code Best Practices: https://www.anthropic.com/engineering/claude-code-best-practices

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

### Two Evaluation Modes: File-Level vs Specimen-Level

**File-level evaluation** (`eval_file`):
- Agent reviews **one file** known to have issues
- Faster feedback loop
- Clearer signal: file is known to contain specific issues
- **Best for iteration:** When debugging why agent misses specific issues
- **Limitations:** Only train split (prevents leakage), only files with >0 issues

**Specimen-level evaluation** (`eval_specimen`, `eval_split`):
- Agent reviews **whole codebase**, searches for all issues
- More realistic but slower
- Signal may be noisy: specimens are often **sparsely labeled**
  - Ground truth may only include 10% of real issues (what bothered a human)
  - Agent may find unlabeled real issues (counted as false positives)
  - Precision may appear artificially low due to incomplete labeling
- **Best for validation:** Confirming prompt generalizes across diverse code

**When to use each:**
- Iterating on specific patterns? → `eval_file` on train files where agent failed
- Testing overall prompt? → `eval_specimen` on a few train specimens
- Measuring generalization? → `eval_split` on train (detailed) or valid (aggregate)

### eval_file(prompt_path, specimen, file_path)
- **Purpose:** Fast iteration on one file
- **Cost:** Low (single file review)
- **Constraints:** Train split only, file must have >0 issues
- **Returns:** detection_rate, detected_issues, issues_in_file

### eval_specimen(prompt_path, specimen)
- **Purpose:** Test on full specimen
- **Cost:** Medium (full specimen review)
- **Returns:** expected, reported, true_positives, false_positive, unknown, false_negatives, precision, recall
- **Caveat:** Precision may be low due to sparse labeling (only issues that bothered annotator)

### eval_split(prompt_path, split: "train"|"valid")
- **Purpose:** Evaluate on full split
- **Cost:** ~$0.70 per split (measured on 3-specimen valid split)
- **Returns:**
  - split="train": detailed_metrics (per-specimen list), specimens list
  - split="valid": aggregate_recall, aggregate_precision, specimen_count, issue_count
    - **Note:** detailed_metrics and specimens are intentionally null for valid (prevents overfitting)
  - split="test": raises error (hidden from you)

**Iteration strategy (cheap → expensive):**
1. **Start small on train**: Test hypotheses cheaply before committing budget
   - File-level: `eval_file()` on 2-3 train files where best prompt failed (fastest)
   - Specimen-level: `eval_specimen()` on 2-3 train specimens (faster than full split)
   - Iterate quickly to debug specific patterns
2. **Expand to full train split**: `eval_split(split="train")` for comprehensive train analysis
   - Only run when you have a promising candidate
   - Use detailed metrics to identify remaining failure patterns
3. **Validate generalization**: `eval_split(split="valid")` to check your optimization target
   - This is expensive - only run when confident in improvements
   - Validation recall is your proxy for test performance
4. **Monitor budget**: Check `budget_remaining` after each call to plan remaining iterations

**Budget management:**
- Don't run full splits early - you'll waste budget on unpromising prompts
- Use file/specimen evals on small N for rapid iteration
- Reserve most budget for validation checks of your best candidates

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
- **Deep-dive on failures:**
  - Pick 2-3 specimens where the best prompt had low recall
  - Read their ground truth issues (`/specimen_defs/train/<slug>/issues/*.libsonnet`)
  - Read what was reported (`critique.json`) vs what was missed (`grade.json` false_negatives)
  - **Analyze the trajectory** (`critic/events.jsonl`): Did the agent examine relevant files? Run appropriate tools? Which tools were used and in what order?
  - Look for patterns: Are certain issue types consistently missed? Is the workflow insufficient?
- **Compare optimization trajectories:**
  - Read prompts from multiple runs: what changed between iterations?
  - Which changes correlated with validation recall improvements?
  - Which changes hurt generalization (improved train but hurt valid)?
  - Extract lessons: what prompt elements seem to help across runs?

**Iteration strategy:**
- Write prompts to `/workspace/` (e.g., `/workspace/prompts/v1.txt`)
- Test hypotheses cheaply on train specimens first
- Verify improvements on validation before considering them successful
- **Critical**: Avoid overfitting to train specifics - your prompt will be evaluated on a hidden test set

**Metrics interpretation and the generalization challenge:**
- **Test recall** (hidden from you) is the ultimate goal
- **Validation recall** is your proxy - optimize for this
- **Train recall** is for debugging only, NOT the goal
- Precision may be misleadingly low due to incomplete labeling
- Unknown detections might be real issues that weren't labeled

**The generalization requirement:**
Your prompt must work on specimens you've never seen. The test set may have:
- Different programming languages than train/valid
- Different project structures and conventions
- Different types of code quality issues
- Different codebases entirely

Focus on principles that generalize (e.g., "look for unreachable code") rather than surface patterns (e.g., "check files matching `test_*.py`").

## Analyzing Agent Trajectories

**What trajectories contain:**
- Agent transcripts: `/artifacts/prompt_evals/eval_<timestamp>/<specimen>/critic/events.jsonl`
- Each line is a JSON object recording agent actions
- Tool calls: `{event: "tool_use", name: "...", input: {...}}`
- Tool results: `{event: "tool_result", tool_use_id: "...", content: [...], is_error: bool}`
- **Note:** Internal reasoning is not included in trajectories

**Example diagnostic queries:**

Check which tools were used:
```bash
jq -r 'select(.event == "tool_use") | .name' events.jsonl | sort | uniq -c
```

Find if a specific file was examined:
```bash
# Look for Read tool calls
jq -r 'select(.event == "tool_use" and .name == "Read") | .input.file_path' events.jsonl | grep "filename"
```

Find failed tool calls:
```bash
jq -r 'select(.event == "tool_result" and .is_error == true) | {tool: .name, error: .content[0].text}' events.jsonl
```

Check tool call sequence:
```bash
# Show the sequence of tools used
jq -r 'select(.event == "tool_use") | .name' events.jsonl
```

**Python alternative** (for complex analysis):
```python
import json
from pathlib import Path

events = [json.loads(line) for line in Path("events.jsonl").read_text().splitlines()]

# What did the agent do?
tool_sequence = [e for e in events if e["event"] == "tool_use"]
print(f"Agent used {len(tool_sequence)} tools")

# Did it read ground truth files?
reads = [e for e in tool_sequence if e["name"] == "Read"]
read_files = [e["input"]["file_path"] for e in reads]
print(f"Read {len(read_files)} files: {read_files[:5]}...")

# Did it fail on any tools?
results = [e for e in events if e["event"] == "tool_result"]
failures = [e for e in results if e.get("is_error")]
print(f"{len(failures)} tool failures")
```

**Using trajectories to improve prompts:**

1. **Compare successful vs failed runs:**
   - Load trajectories from high-recall and low-recall runs
   - What tools did successful runs use that failures didn't?
   - What files did successful runs examine?
   - What was the sequence of operations (tool ordering)?

2. **Identify coverage gaps:**
   - Load ground truth: `/specimen_defs/train/<slug>/issues/*.libsonnet`
   - Load reported issues: `/artifacts/prompt_evals/eval_<timestamp>/<specimen>/critique.json`
   - For each false negative, check the trajectory: Did the agent examine the relevant file? Did it run relevant tools? Which tools succeeded/failed?

3. **Spot inefficiencies:**
   - Are there redundant tool calls?
   - Is the agent reading files it doesn't need?
   - Is it running tools in a suboptimal order?

4. **Extract generalizable patterns:**
   - Don't overfit to "agent should read file X" (specimen-specific)
   - Do extract "agent should run static analysis before file reads" (generalizable)
   - Focus on workflow patterns, not specific file names

## Avoiding Local Optima

**The diversity challenge:** Iterative refinement can get stuck in local optima where small changes don't improve validation recall.

**Strategies when validation plateaus:**

1. **Lateral exploration:** Try a significantly different approach rather than incremental tweaks:
   - Different tool sequencing (e.g., start with grep instead of static analysis)
   - Different scope (e.g., broader initial sweep vs. targeted deep dives)
   - Different emphasis (e.g., focus on test coverage vs. code duplication)

2. **Analyze what's NOT being caught:**
   - Look at false negatives from validation (aggregate metrics only, no per-specimen details)
   - From train specimens, categorize missed issues by type (dead code? type safety? architecture?)
   - If one category dominates misses, add explicit guidance for that pattern

3. **Contrast successful vs struggling prompts:**
   - Read multiple past prompts from `/artifacts/prompt_evals/eval_*/prompt.txt`
   - What did high-validation-recall prompts have in common?
   - What did low-recall prompts lack?
   - Extract commonalities, not surface patterns

4. **Meta-prompt elements:**
   - Clear success criteria (what counts as an issue?)
   - Explicit workflow (exploration → analysis → synthesis)
   - Concrete examples (positive and negative cases)
   - Calibrated eagerness (thorough but not exhaustive)

**Red flags for local optima:**
- Validation recall unchanged after 3+ iterations of refinement
- Prompts getting longer without improving metrics
- Adding specimen-specific cues (file names, directory structure)
- Incremental tweaks that don't address root causes

## Output Format

The critic prompt you generate will be passed to a harness that enforces structured output.
Do not prescribe JSON schemas in your prompt.
Focus on analysis strategy, search patterns, and guardrails.
