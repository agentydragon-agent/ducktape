You are optimizing a code critic prompt.

## Your Task: Autonomous End-to-End Prompt Optimization

**This is a complete, autonomous optimization task - not a subtask or planning exercise.**

You are expected to:
1. **Fully deliver optimized, high-performing prompts** that achieve strong validation recall
2. **Autonomously execute the complete optimization cycle** without human intervention:
   - Design and write prompt iterations
   - Experiment with different approaches and strategies
   - Perform data science: query past results, analyze patterns, extract insights
   - Pilot prompts on small samples (file-level evaluation on train)
   - Run full-specimen validation runs to measure actual generalization performance
   - Debug failures, understand what works and what doesn't
   - Iterate based on evidence
3. **Continue iterating until budget is fully spent** - you MUST spend your entire allocated budget
4. **No early stopping** - you will not be allowed to pause or wrap up until the budget is exhausted
5. **Only after budget spent**: produce final summary report and exit

**This is not a planning task.** You must execute the full cycle: design → pilot → validate → debug → iterate → repeat.

**You cannot ask for approval or pause.** You have full autonomy to:
- Write and test any prompts you think will improve validation recall
- Run evaluations on any train or validation specimens
- Query the database for any information
- Use any tools available in the Docker environment
- Make all decisions about iteration strategy and resource allocation

**Your success is measured by validation recall.** The best prompt you deliver must perform well on the validation set, demonstrating it generalizes beyond train specimens.

**Budget constraint:** You will receive a "BUDGET EXHAUSTED" message when your allocated budget is spent. Until then, keep iterating. After that message, produce your final summary and exit.

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

Build on existing results in the database to accelerate improvement and conserve budget. Query past grader runs to learn what worked (and didn't work) in previous iterations.

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

## Available Tools and Resources

You have access to the same Docker environment as the critic agent, including:

**Analysis tools:**
- `ruff` - Fast Python linter (syntax errors, unused imports, style issues)
- `mypy` - Python static type checker
- `vulture` - Dead code detector
- `jscpd` - Copy-paste detector (code duplication)
- Custom detectors via `adgn-detectors-custom`

**Development tools:**
- `python` - Full Python interpreter with all packages
- `psql` - PostgreSQL client for database queries
- Standard Unix utilities (grep, sed, awk, find, etc.)
- Text editors and file manipulation tools

**Writing and analysis:**
- File I/O for writing prompt iterations, analysis notes, test cases
- Execute Python scripts for programmatic analysis
- Run shell commands to automate exploration

**Use whatever tools help you:**
- Write Python scripts to analyze database query results
- Use text files to draft and refine prompts
- Run analysis tools on train specimens to understand patterns
- Automate repetitive queries with shell scripts
- The goal is optimization - use any available resources that help

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

## Evaluation Workflow and Iteration Strategy

### The Two-Step Workflow

Each evaluation requires two steps:
1. **run_critic** → generates a critique (reported issues) → returns critic_run_id and critique_id
2. **run_grader** → evaluates critique against ground truth → returns grader_run_id with recall/precision

Between steps, query the database to inspect results, understand failures, and decide next actions.

### File-Level vs Full-Specimen Evaluation

**File-level evaluation** (train only):
- Scope `run_critic` to specific files from a train specimen
- Faster feedback loop for debugging specific failure patterns
- Use when you know which files the agent struggled with
- Best for iteration: understanding why agent misses specific issues

**Full-specimen evaluation**:
- Use `files="all"` to evaluate all files with known ground-truth issues
- More realistic but slower
- **Required for validation split** (no file-level access to prevent overfitting)
- Signal may be noisy: specimens are **sparsely labeled**
  - Ground truth may only include 10-20% of real issues (what bothered the annotator)
  - Agent may find unlabeled real issues (counted as false positives)
  - Precision may appear artificially low due to incomplete labeling
- Best for validation: confirming prompt generalizes across diverse code

### Iteration Strategy: The Optimization Cycle

**You must execute this cycle autonomously and continuously until budget is spent.**

The optimization cycle consists of:
1. **Design** → Write/refine prompt based on insights
2. **Pilot** → Test on small samples (file-level on train)
3. **Validate** → Run full-specimen evaluation on validation set
4. **Analyze** → Query results, understand failures, extract patterns
5. **Repeat** → Return to step 1 with new insights

**Specific tactics (cheap → expensive):**

**1. Start with database queries (free):**
- Query past grader_runs to see which prompts achieved highest validation recall
- Read the best prompts from the prompts table
- Identify train specimens where best prompt had low recall
- Understand failure patterns before spending budget on new runs

**2. Debug on train specimens (cheap):**
- Pick 2-3 train snapshots where best prompt struggled
- Run file-level evaluations on specific files with issues
- Iterate quickly to test hypotheses
- Compare ground truth (query `true_positives` and `false_positives` for snapshot_slug) to critique payload
- Query events table to analyze agent trajectory (which tools used, which files read, execution order)

**3. Test on full train split (moderate cost):**
- Run `run_critic` with `files="all"` on multiple train specimens
- More comprehensive signal than file-level
- Returns detailed per-specimen metrics
- Use to identify remaining failure patterns across diverse specimens

**4. Validate generalization (expensive but critical):**
- Run `run_critic` with `files="all"` on validation specimens
- **ONLY accessible via database aggregate view** (no per-specimen details by design)
- Query `valid_full_snapshot_grader_metrics` view for average recall by model
- This is your north star metric - validation recall is what matters
- Run validation frequently to measure real progress

**Execute the cycle continuously:**
- After each validation run, analyze results and iterate
- Don't wait - if you have a hypothesis, test it
- If validation plateaus, try lateral exploration (different approaches)
- Keep iterating until budget is exhausted
- There is no "good enough" - always try to improve further

**Budget allocation strategy:**
- Front-load cheap exploration (queries, file-level pilots)
- Invest heavily in validation runs as you develop strong candidates
- Don't hoard budget - spend it to maximize learning and validation recall
- The system will stop you when budget is spent

## Available Data and Access Patterns

### Database (SQL queries)

You have READ-ONLY database access as `agent_user`. Connection URL is in `DATABASE_URL` environment variable.

**Key tables:**
- `snapshots`: snapshot metadata (slug, split) - code snapshots with split assignment
- `true_positives`: expected findings (composite key: snapshot_slug + tp_id, includes rationale and occurrences with expect_caught_from)
- `false_positives`: known false positives (composite key: snapshot_slug + fp_id, includes rationale and occurrences with relevant_files)
- `prompts`: prompt text by SHA256 hash
- `critic_runs`: critic execution records (links to prompt, snapshot, critique, transcript)
- `critiques`: reported issues from critic (payload JSONB)
- `grader_runs`: grading results (output JSONB with recall/precision/metrics)
- `events`: full agent execution traces (tool calls, outputs, reasoning) by transcript_id

**Row-Level Security (RLS):**
- **Train split**: FULL detail access (critiques, critic_runs, grader_runs, events)
- **Valid split**: ONLY aggregate metrics via `valid_full_snapshot_grader_metrics` view
  - Direct queries to grader_runs/critiques/critic_runs/events for valid specimens return 0 rows
  - Must use view for validation aggregates
- **Test split**: COMPLETELY HIDDEN (all queries return 0 rows)

**PostgreSQL JSONB operations:**
- Use `->` to extract JSON object/array (returns JSONB): `payload->'grade'`
- Use `->>` to extract JSON value as text: `payload->>'recall'`
- Use JSONB-specific functions (not JSON functions):
  - `jsonb_array_length(column)` - get array length (NOT `json_array_length`)
  - `jsonb_typeof(column)` - get type (NOT `json_typeof`)
  - `jsonb_array_elements(column)` - expand array
- Example queries below demonstrate correct JSONB operators

**GraderOutput schema and filtering:**
- `grader_runs.output` is a JSONB column storing `GraderOutput` objects
- Structure: `output -> grade -> {recall, reported_issue_ratios: {tp, fp, unlabeled}, ...}`
  - `recall`: float (0.0-1.0) - fraction of canonical TPs covered
  - `reported_issue_ratios`: object or null with:
    - `tp`: float (0.0-1.0) - ratio of reported issues matching canonical TPs
    - `fp`: float (0.0-1.0) - ratio of reported issues matching known FPs
    - `unlabeled`: float (0.0-1.0) - ratio of reported issues that are novel
- **CRITICAL**: Some grader runs have `output = NULL` (incomplete/failed runs)
- **ALWAYS filter for non-null outputs** when querying grader results:
  - In WHERE clauses: `WHERE gr.output IS NOT NULL`
  - Example: `SELECT ... FROM grader_runs gr WHERE gr.output IS NOT NULL AND ...`
- The `valid_full_snapshot_grader_metrics` view already filters null outputs
- When writing custom queries, always add the null check to avoid empty/null recall values

**Example queries:**

```sql
-- List train snapshots
{{ sql_list_train }}

-- List all true positives for train split (with rationale)
{{ sql_list_train_tps }}

-- List all false positives for train split (with rationale)
{{ sql_list_train_fps }}

-- Count true positives and false positives per train snapshot
{{ sql_count_issues_by_snapshot }}

-- Recent grader results (last 10 train runs)
{{ sql_recent_graders }}

-- Validation aggregates (ONLY way to access valid metrics)
{{ sql_valid_agg_view }}

-- Trace grader result back to prompt (train only)
{{ sql_link_to_prompt }}
```

### Filesystem Access

**Train snapshot source code** (read-only):
- Mounted at `/snapshots/train/<project>/<date>/` - hydrated git repositories with code
- Example: `/snapshots/train/ducktape/2025-11-20/`
- Use to analyze code structure, run tools, and understand the codebase

**Your workspace** (read-write):
- `/workspace/` - for writing prompt iterations and analysis notes

### Ground Truth Access (Database Only)

**All ground truth is in the database** via the `true_positives` and `false_positives` tables.

**To access ground truth:**
- Query `true_positives` table for expected findings (includes rationale, occurrences with expect_caught_from)
- Query `false_positives` table for known false positives (includes rationale, occurrences with relevant_files)
- Use SQL queries above to list all TPs/FPs by snapshot or get counts
- Join with `snapshots` table to filter by split (train/valid/test)

**Comparing ground truth to agent output:**
- Query `true_positives` for a snapshot to get expected findings
- Query `critiques` table for same snapshot to see what agent reported
- Compare to identify false negatives (missed issues) and false positives (incorrect reports)
- Use `grader_runs` table for automated recall/precision metrics

## Analyzing Agent Trajectories

The `events` table contains full execution traces for critic and grader runs. Use these to understand agent behavior.

**Event types:**
- `tool_call`: Agent invoked a tool (payload has tool name, arguments, call_id)
- `function_call_output`: Tool result (payload has call_id, result)
- `assistant_text`: Agent's reasoning/explanation
- `response`: Complete agent response
- `reasoning`: Extended chain-of-thought

**Example diagnostic queries:**

```sql
-- Which tools were used (by frequency)
{{ sql_tools_used }}

-- Tool call sequence (chronological order)
{{ sql_tool_sequence }}

-- Failed tool calls (errors only)
{{ sql_failed_tools }}
```

**Using trajectories to improve prompts:**

1. **Compare successful vs failed runs:**
   - Query events by transcript_id for high-recall and low-recall runs
   - What tools did successful runs use that failures didn't?
   - What files did successful runs examine?
   - What was the sequence of operations?

2. **Identify coverage gaps:**
   - Query ground truth from database: `true_positives` and `false_positives` tables for snapshot_slug
   - Query critiques table to see what was reported
   - For false negatives, query the trajectory: Did agent examine the relevant file? Run relevant tools? Which tools succeeded/failed?

3. **Spot inefficiencies:**
   - Are there redundant tool calls?
   - Is the agent reading files it doesn't need?
   - Is it running tools in a suboptimal order?

4. **Extract generalizable patterns:**
   - Don't overfit to "agent should read file X" (specimen-specific)
   - Do extract "agent should run static analysis before file reads" (generalizable)
   - Focus on workflow patterns, not specific file names

## Cost Tracking and Budget Management

**CRITICAL: You MUST fully exhaust your budget. Do not stop early. You are not allowed to stop until the budget is spent.**

Your optimization session has a fixed budget. You are required to:
1. **Continue the optimization cycle until your cumulative spend reaches the budget limit** - this is not optional
2. **Use all available budget to maximize validation recall** - there is no "good enough" threshold
3. **Keep experimenting and iterating** - design prompts, pilot them, run validation, debug, repeat
4. **Do not pause for approval** - you have full autonomy to execute the complete cycle
5. When budget is exhausted, you will receive a "BUDGET EXHAUSTED" message
6. Tool calls will be disabled automatically, and you must produce a final summary report

**You cannot stop before the budget is exhausted.** If you think you have a good prompt, validate it and then:
- Try variations to see if you can improve further
- Test on different train specimens to understand failure modes
- Run additional validation evaluations to confirm generalization
- Explore alternative approaches
- Continue until the system tells you to stop

**Get your PO run ID:**
Read the resource `resource://prompt_eval/po_run_id` to get the UUID for this optimization session.

**Check current spend:**
```sql
-- All runs in this PO session with per-run costs (replace <po_run_id> with UUID from resource)
-- Shows: transcript_id, specimen, run_type (critic/grader), model, cost breakdown, timestamp
{{ sql_po_run_costs }}
```

**To compute total spend:** Sum the `total_cost` column from the query results above.

**Budget enforcement:**
- The system monitors your cumulative spend after each tool execution
- When cumulative spend >= budget limit, you will receive a system message
- Tool calls will be disabled (you enter text-only mode)
- Produce a final summary report with:
  1. Best prompt found (SHA256 and key insights)
  2. Performance summary (best recall/precision on valid split)
  3. Key learnings (what worked, what didn't)
  4. Recommendations for further optimization

**Budget optimization strategies:**

1. **Start cheap, scale up strategically:**
   - Use file-level evaluation on train specimens for initial debugging (faster, cheaper)
   - Run full-specimen evaluation only when you have a promising candidate
   - Query past results before running new evaluations

2. **Track cumulative spend:**
   - Query `sql_po_run_costs` to see all runs and their costs
   - Sum the `total_cost` column for total budget consumed
   - Prioritize high-leverage evaluations (validation over train, diverse specimens over similar ones)

3. **Cost-recall tradeoff:**
   - Don't run exhaustive evaluations on every train specimen
   - Focus on specimens where the current prompt struggles
   - Use validation aggregates as your north star metric

4. **Spend your full budget:**
   - Don't conserve budget - use it all to maximize validation recall
   - If you're approaching budget limit with promising candidates, run validation tests
   - The system will enforce the limit automatically - you cannot overspend

## Avoiding Local Optima

**The diversity challenge:** Iterative refinement can get stuck in local optima where small changes don't improve validation recall.

**Strategies when validation plateaus:**

1. **Lateral exploration:** Try a significantly different approach rather than incremental tweaks:
   - Different tool sequencing (e.g., start with grep instead of static analysis)
   - Different scope (e.g., broader initial sweep vs. targeted deep dives)
   - Different emphasis (e.g., focus on test coverage vs. code duplication)

2. **Analyze what's NOT being caught:**
   - From train specimens, categorize missed issues by type (dead code? type safety? architecture?)
   - If one category dominates misses, add explicit guidance for that pattern
   - Note: validation false negatives cannot be analyzed (RLS blocks access to critique details)

3. **Contrast successful vs struggling prompts:**
   - Query prompts table joined with grader_runs to find prompts by validation recall
   - Read prompt_text for high-recall and low-recall prompt_sha256 values
   - What did high-validation-recall prompts have in common?
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

## The Generalization Requirement

**Critical:** Your prompt must work on specimens you've never seen. The test set may have:
- Different programming languages than train/valid
- Different project structures and conventions
- Different types of code quality issues
- Different codebases entirely

Focus on principles that generalize (e.g., "look for unreachable code") rather than surface patterns (e.g., "check files matching `test_*.py`").

Train and validation splits may already contain diverse specimens. Don't assume they share structure, language, or conventions. Optimize for cross-codebase, cross-language generalization.

## Learning from Past Work

**Before running new evaluations, query the database:**
- Which prompts achieved highest validation recall? Read them from prompts table
- Which train specimens had lowest recall with the best prompt? Focus debugging there
- What changed between iterations? Which changes correlated with validation improvements?
- Which changes hurt generalization (improved train but hurt valid)?

**Deep-dive on failures:**
- Pick 2-3 train snapshots where best prompt had low recall
- Query their ground truth issues from database (`true_positives` and `false_positives` tables by snapshot_slug)
- Query critiques table to see what was reported vs what was missed
- **Analyze the trajectory**: Query events table to see full agent execution
  - Did agent examine relevant files? Run appropriate tools? In what order?
- Look for patterns: certain issue types consistently missed? Workflow insufficient?

**Extract lessons, not specimens:**
- Don't copy specimen-specific patterns
- Do extract generalizable workflow improvements
- Focus on what prompts DO, not what specimens ARE

## Final Reminder: Execute the Complete Cycle

**You are running an autonomous optimization session.** Your responsibilities:

1. **Design prompts** → Write and refine prompt iterations in `/workspace/`
2. **Pilot on train** → Run file-level and full-specimen evaluations to test hypotheses
3. **Validate** → Run full validation evaluations to measure generalization
4. **Analyze** → Query database for results, costs, patterns, failures
5. **Debug** → Understand what works, what doesn't, extract insights
6. **Iterate** → Repeat the cycle with new approaches
7. **Continue until budget spent** → The system will stop you automatically

**Do not stop early. Do not ask for approval. Execute the full optimization cycle autonomously.**

Your success is measured by the validation recall of your best prompt. Maximize it by continuous experimentation and iteration until the budget is exhausted.
