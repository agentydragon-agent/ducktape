# Spawn Graph - Parallel Execution of Dependency Graphs

Execute a complex task by breaking it into a dependency graph and spawning parallel agents to work through it at maximum throughput.

## Usage

```
/spawn-graph [--workflow=naive|worktree]
```

Or conversationally anywhere in your prompt:
```
"analyze this monorepo, find if I can delete service X /spawn-graph oh and make it thorough"
"refactor the auth system /spawn-graph using the worktree workflow please"
```

Use this command when you have a complex task that can be broken into subtasks with dependencies between them. The command can appear at the start, middle, or end of your message.

## IMPORTANT: Confirmation Required

**Before spawning any agents, I will ALWAYS:**
1. **Tell you which workflow will be used** (worktree by default, naive if specified)
2. **Show you the execution plan** with:
   - Total number of tasks
   - Number of phases
   - Tasks per phase
   - Example: "This will spawn **23 tasks** across **4 phases** using **worktree workflow**"
3. **Ask for your confirmation** before proceeding

You can then:
- Confirm to proceed
- Request changes to the plan
- Cancel the operation

## Workflow Modes

### 1. Worktree Workflow (Default)
**Each task gets its own git worktree for complete isolation.** This is the default and recommended approach for maximum parallelism and clean merging of parallel work.

**Git worktrees allow multiple working directories for the same repository:**
```bash
# Example: Creating a worktree for a task
git worktree add ./spawn-graph/2025-01-02-1430/phase01/task01-auth feature/auth-refactor

# This creates:
# - A new working directory at the specified path
# - Checks out the branch 'feature/auth-refactor'
# - Multiple agents can work in parallel without conflicts
```

### 2. Naive Workflow
All tasks work in the same repository. Only use this for simple tasks where git isolation isn't needed.

**Always use worktree workflow (the default) unless you have a specific reason not to:**
- **Worktree (default)**: Parallel development, clean git history, no merge conflicts during work
- **Naive**: Only for read-only analysis or very simple non-conflicting tasks

## What It Does

1. **Analyzes** the current task/request to identify all component pieces
2. **Creates** an explicit dependency graph showing what depends on what
3. **Executes** in waves:
   - Identifies all tasks with satisfied prerequisites
   - Spawns a batch of agents to work on them in parallel
   - Waits for completion
   - Repeats until all tasks are done
4. **Coordinates** results back into a coherent whole

## CRITICAL: Git Commands for Spawning Agent

**The spawning agent (YOU, when using this command) MUST run specific git commands:**

### Before Spawning Each Wave:
```bash
# CRITICAL: Always operate from git repository root!
cd "$(git rev-parse --show-toplevel)"

# Example for 3 tasks in phase01:
INSTANCE="2025-01-02-1430"
PHASE="phase01"

# Using brace expansion for multiple tasks
for TASK in task01-auth task02-database task03-api; do
    BRANCH_NAME="spawn-graph/${INSTANCE}/${PHASE}/${TASK}"
    WORKTREE_PATH="./spawn-graph/${INSTANCE}/${PHASE}/${TASK}"
    git worktree add "${WORKTREE_PATH}" -b "${BRANCH_NAME}"
done

# Or using brace expansion in one line:
# for TASK in task{01-auth,02-database,03-api}; do ...; done
```

### After Each Wave Completes:
```bash
# CRITICAL: Always operate from git repository root!
cd "$(git rev-parse --show-toplevel)"

# 1. Check results from each task
for TASK_DIR in ./spawn-graph/${INSTANCE}/${PHASE}/task*/; do
    if [ -d "$TASK_DIR" ]; then
        TASK_NAME=$(basename "$TASK_DIR")
        BRANCH="spawn-graph/${INSTANCE}/${PHASE}/${TASK_NAME}"
        OUTPUT_PATH="spawn-graph/${INSTANCE}/${PHASE}/${TASK_NAME}/OUTPUT.md"
        
        # Check OUTPUT.md from the branch
        if git show "${BRANCH}:${OUTPUT_PATH}" 2>/dev/null; then
            echo "=== Results from ${TASK_NAME} ==="
        fi
    fi
done

# 2. Merge successful tasks back to main
git checkout main
for TASK_DIR in ./spawn-graph/${INSTANCE}/${PHASE}/task*/; do
    if [ -d "$TASK_DIR" ]; then
        TASK_NAME=$(basename "$TASK_DIR")
        BRANCH="spawn-graph/${INSTANCE}/${PHASE}/${TASK_NAME}"
        
        # Check if task succeeded (parse OUTPUT.md)
        if git show "${BRANCH}:spawn-graph/${INSTANCE}/${PHASE}/${TASK_NAME}/OUTPUT.md" 2>/dev/null | grep -q "^STATUS: SUCCESS"; then
            git merge --no-ff "${BRANCH}" -m "Merge ${TASK_NAME} from spawn-graph phase ${PHASE}"
        fi
    fi
done

# 3. Clean up successfully merged worktrees
for TASK_DIR in ./spawn-graph/${INSTANCE}/${PHASE}/task*/; do
    if [ -d "$TASK_DIR" ]; then
        TASK_NAME=$(basename "$TASK_DIR")
        BRANCH="spawn-graph/${INSTANCE}/${PHASE}/${TASK_NAME}"
        
        # Only remove if branch was merged
        if git branch --merged | grep -q "${BRANCH}"; then
            git worktree remove "${TASK_DIR}" --force
            git branch -d "${BRANCH}" 2>/dev/null || true
        fi
    fi
done
```

## Process

### Phase 1: Graph Construction
1. Break down the task into atomic subtasks
2. Identify dependencies between subtasks
3. Create a DAG (Directed Acyclic Graph) representation
4. Validate no circular dependencies exist
5. Identify the critical path

### Phase 2: Execution Planning
1. Topologically sort the graph
2. Group tasks into execution waves
3. Estimate resource requirements
4. Plan agent allocation strategy

### Phase 3: Parallel Execution

Use the Task tool to spawn multiple agents in parallel:

```
while (incomplete tasks exist):
    ready_tasks = find_all_tasks_with_met_dependencies()

    # Spawn all ready tasks in ONE message with multiple Task tool calls
    results = parallel_task_execution([
        Task(description=f"Task {task.id}", prompt=task.prompt)
        for task in ready_tasks
    ])

    collect_results(results)
    update_completion_status()
```

**CRITICAL**: The key is to use multiple Task tool invocations in a SINGLE message. This spawns multiple agents that work in parallel.

### Phase 4: Integration
1. Collect all agent outputs
2. Resolve any conflicts
3. Integrate results into final deliverable
4. Generate summary report

## Worktree Workflow Details

When using `--workflow=worktree` (or requesting worktree workflow conversationally), the system creates an isolated git environment for maximum parallelism and clean merging.

### Key Definitions

- **Graph Instance Directory**: `./spawn-graph/{timestamp}-{description}/` - The root directory for a specific spawn-graph execution (e.g., `./spawn-graph/2025-01-02-1430-parallel-fizzbuzz/`)
- **Phase Directory**: `{graph-instance-dir}/phase{N}-{phasename}/` - Groups all tasks for a specific execution phase (e.g., `phase01-analysis/`, `phase02-compute/`)
- **Task Directory**: `{phase-dir}/task{M}-{taskname}/` - The git worktree where a task agent operates (e.g., `task01-fizzbuzz-1-33/`)
- **Task Output Dir**: `{task-dir}/spawn-graph/{timestamp}-{description}/phase{N}-{phasename}/task{M}-{taskname}/` - Subdirectory within the task directory for progress notes and final output. The path components after spawn-graph/ are duplicated to prevent merge conflicts.

### Scaffolding Structure

**NOTE**: Worktrees must be created within the repository due to Claude's security model.
See [CLAUDE_SECURITY_MODEL.md](~/code/ducktape/dotfiles/claude-commands/CLAUDE_SECURITY_MODEL.md) for details on why centralized storage outside the repo is not possible.

```
./spawn-graph/
├── README.md                                    # Explains this is for coordinating spawn-graph tasks
└── 2025-01-02-1234-improve-security-protocol/  # {graph-instance-dir}
    ├── TASK.md                                 # Full description of overall task
    ├── PLAN.md                                 # Dependency graph and execution phases
    ├── phase01-foundation/                     # {phase-dir} for Phase 1 (holds task worktrees)
    │   ├── task01-define-interfaces/           # {task-dir} for Phase 1 Task 1 (git worktree, checked out to branch spawn-graph/2025-01-02-1234-improve-security-protocol/phase01-foundation/task01-define-interfaces)
    │   │   ├── .git/                          # Git metadata (worktree link)
    │   │   ├── [project files]                # Actual code being worked on
    │   │   └── spawn-graph/                   # {task-output-dir} begins here
    │   │       └── 2025-01-02-1234-improve-security-protocol/
    │   │           └── phase01-foundation/
    │   │               └── task01-define-interfaces/
    │   │                   ├── PROGRESS.md    # Running notes
    │   │                   └── OUTPUT.md      # Final result
    │   ├── task02-security-audit/
    │   └── task03-threat-model/
    └── phase02-implementation/                 # {phase-dir} for Phase 2 (holds task worktrees)
        ├── task01-auth-module/
        └── task02-encryption-layer/
```

**KEY INSIGHT**: The task output dir is intentionally duplicated! When branches merge, each task's output lands in a unique location, preventing conflicts.

### Critical Invariant: Repository View Consistency

**INVARIANT**: Spawned agents must see the repository structure exactly as the spawning agent sees it.

If spawning agent sees:
```
repo/
├── src/
├── tests/
└── spawn-graph/
```

Then spawned agent in worktree MUST also see:
```
worktree-root/
├── src/
├── tests/
└── spawn-graph/
```

This means:
- Same relative paths work for both agents
- Same file references remain valid
- No path translation needed between agents
- `./src/main.py` means the same thing to both

### Workflow Process

1. **Initialization**
   - Create `./spawn-graph/` directory with README explaining its purpose
   - Create graph instance directory: `./spawn-graph/{timestamp}-{task-description}/`
   - Write `TASK.md` with full task description
   - Analyze dependencies and create `PLAN.md` with:
     - List of all subtasks
     - Dependency edges (DAG)
     - Optimized phases for minimal serial execution
     - Each task named like `phase01-foundation/task03-check-dependencies` (format: phase{N}-{phasename}/task{M}-{taskname})

2. **Worktree Setup per Task**
   
   **CRITICAL: The spawning agent MUST run these exact git commands for each task:**
   
   ```bash
   # CRITICAL: Always operate from git repository root!
   cd "$(git rev-parse --show-toplevel)"
   
   # For each task in the phase, run:
   INSTANCE="2025-01-02-1430-parallel-fizzbuzz"  # Example
   PHASE="phase01-foundation"
   TASK="task01-define-interfaces"
   BRANCH_NAME="spawn-graph/${INSTANCE}/${PHASE}/${TASK}"
   WORKTREE_PATH="./spawn-graph/${INSTANCE}/${PHASE}/${TASK}"
   
   # Create the worktree with a new branch
   git worktree add "${WORKTREE_PATH}" -b "${BRANCH_NAME}"
   
   # If the main working directory has uncommitted changes, replicate them:
   if [ -n "$(git status --porcelain)" ]; then
       # Save current changes
       git stash push -m "spawn-graph-${INSTANCE}-uncommitted"
       
       # Apply to the new worktree
       cd "${WORKTREE_PATH}"
       git stash pop
       cd -
   fi
   ```
   
   - Task output dir will be created by agent at: `./spawn-graph/{instance}/phase{N}-{phasename}/task{M}-{taskname}/spawn-graph/{instance}/phase{N}-{phasename}/task{M}-{taskname}/`

3. **Phase Execution**
   For each phase:
   - Launch N parallel agents (one per task in phase)
   - Each agent receives:
     ```
     CRITICAL: Your starting directory reflects spawning agent's position!
     If spawning agent was in subdirectory src/utils/ when spawning,
     you will also start in src/utils/ within your worktree.
     
     Your worktree root is: {repo-root}/spawn-graph/{instance}/phase{X}-{phasename}/task{Y}-{taskname}/
     Your current directory: {repo-root}/spawn-graph/{instance}/phase{X}-{phasename}/task{Y}-{taskname}/{relative_path_from_repo_root}
     
     First, navigate to your worktree root:
     cd "$(git rev-parse --show-toplevel)"
     
     Read TASK.md and PLAN.md from ./spawn-graph/{instance}/
     Execute task phase{X}-{phasename}/task{Y}-{taskname}
     
     IMPORTANT: You are working in a git worktree!
     This is a separate working copy of the repository.
     
     Install pre-commit hooks in your worktree:
     pre-commit install
     
     Create task output dir at: ./spawn-graph/{instance}/phase{X}-{phasename}/task{Y}-{taskname}/spawn-graph/{instance}/phase{X}-{phasename}/task{Y}-{taskname}/
     Make logical commits on branch spawn-graph/{instance}/phase{X}-{phasename}/task{Y}-{taskname}
     Write final OUTPUT.md in task output dir when done/blocked
     ```

4. **Agent Work Pattern**
   - Read overall task and plan
   - Work only in assigned worktree
   - Create task output directory (with full path duplication)
   - Keep current state in task output directory
   - Make incremental commits including task output
   - **CRITICAL: Before marking task complete, perform quality checks on YOUR contribution:**
     ```bash
     # 1. Run pre-commit checks on YOUR changes:
     # First, check what files YOU changed:
     git diff --name-only main...HEAD
     
     # Run pre-commit ONLY on files you modified:
     pre-commit run --files $(git diff --name-only main...HEAD)
     
     # If pre-commit fails on YOUR files, fix the issues:
     # - Format code you wrote (black, prettier, etc.)
     # - Fix linting errors in your code
     # - Address type errors you introduced
     # - Keep running until YOUR changes pass
     
     # Note: If pre-commit fails on files you DIDN'T modify, that's not your responsibility
     # Only fix issues in code YOU added or changed
     ```
     
   - **ADDITIONAL QUALITY STEPS - Think about what's relevant for YOUR task:**
     - **Self-Review**: Read through all code you wrote. Ask yourself:
       - Is this the clearest way to express this logic?
       - Are variable/function names descriptive?
       - Would another developer understand this easily?
       - Can any of this be simplified or made more elegant?
       - Are there any code smells or anti-patterns?
     - **Documentation & Links**:
       - If you added documentation with links, test they work
       - If you reference external resources, verify they're accessible
       - Check relative file paths in docs/comments are correct
     - **Testing**:
       - If you added features, did you add tests?
       - Run any relevant test suites for code you touched
       - Consider edge cases you might have missed
     - **Dependencies**:
       - If you added new dependencies, are they necessary?
       - Are versions pinned appropriately?
     - **Performance**:
       - For algorithmic code: Is this efficient?
       - For UI code: Will this cause unnecessary re-renders?
     - **Security**:
       - No hardcoded secrets or credentials
       - Input validation where needed
       - No SQL injection or XSS vulnerabilities
     - **Cleanup**:
       - Remove any debug print statements
       - Delete commented-out code
       - Remove unused imports
       - Clean up any temporary files
     
     **Think contextually**: What other cleanup makes sense for YOUR specific task?
     - API work? Check error handling and response codes
     - Frontend? Check accessibility and responsive design  
     - Data processing? Verify data integrity and edge cases
     - Documentation? Spell check and verify examples work
     
     **Take action**: Don't just think about these - actually make improvements!
   - Document observations, side outputs, blockers
   - **CRITICAL: Ensure clean worktree before completion**:
     ```bash
     # Commit all your work
     git add -A
     git commit -m "final: Complete task ${TASK_NAME}"
     
     # Verify clean status
     git status --porcelain
     # Should show NO output - if it does, commit remaining changes!
     ```
   - Final output goes to task output directory's `OUTPUT.md` with status:
     - SUCCESS: Task completed AND pre-commit passes on YOUR changes AND worktree is clean
     - FAILED: Task cannot be completed
     - BLOCKED: Waiting on dependency or external factor
     - PARTIAL: Some progress made but incomplete

5. **Phase Completion**
   
   **CRITICAL: The spawning agent MUST run these exact git commands after each phase:**
   
   ```bash
   # CRITICAL: Always operate from git repository root to avoid path disasters!
   cd "$(git rev-parse --show-toplevel)"
   
   # After all agents in a phase complete, run:
   
   # 1. IMPORTANT: Each agent MUST ensure their worktree is clean before phase completion
   # Agents are responsible for committing all their work and having a clean git status
   
   # 2. Check out each task's OUTPUT.md to see results
   for TASK_DIR in ./spawn-graph/${INSTANCE}/${PHASE}/task*/; do
       TASK_NAME=$(basename "$TASK_DIR")
       BRANCH="spawn-graph/${INSTANCE}/${PHASE}/${TASK_NAME}"
       
       # Get the OUTPUT.md from the branch
       OUTPUT_FILE="${TASK_DIR}/spawn-graph/${INSTANCE}/${PHASE}/${TASK_NAME}/OUTPUT.md"
       if git show "${BRANCH}:${OUTPUT_FILE}" > /dev/null 2>&1; then
           echo "=== Results from ${TASK_NAME} ==="
           git show "${BRANCH}:${OUTPUT_FILE}"
       fi
   done
   
   # 3. Merge successful tasks back to main
   git checkout main
   
   for TASK_DIR in "$SPAWN_GRAPH_BASE/${INSTANCE}/${PHASE}"/task*/; do
       TASK_NAME=$(basename "$TASK_DIR")
       BRANCH="spawn-graph/${INSTANCE}/${PHASE}/${TASK_NAME}"
       
       # Check if task succeeded (you need to parse OUTPUT.md for this)
       if [task succeeded]; then
           echo "Merging ${BRANCH}..."
           git merge --no-ff "${BRANCH}" -m "Merge ${TASK_NAME} from spawn-graph phase ${PHASE}"
       fi
   done
   
   # 4. Clean up successfully merged worktrees
   # IMPORTANT: Only delete worktrees that were successfully merged
   for TASK_DIR in "$SPAWN_GRAPH_BASE/${INSTANCE}/${PHASE}"/task*/; do
       TASK_NAME=$(basename "$TASK_DIR")
       BRANCH="spawn-graph/${INSTANCE}/${PHASE}/${TASK_NAME}"
       
       # Only remove if branch was merged
       if git branch --merged | grep -q "${BRANCH}"; then
           echo "Removing worktree ${TASK_DIR}..."
           git worktree remove "${TASK_DIR}" --force
           
           # Delete the merged branch
           git branch -d "${BRANCH}" 2>/dev/null || true
       else
           echo "Keeping unmerged worktree: ${TASK_DIR}"
       fi
   done
   ```
   
   - Update `PLAN.md` if needed (add retries, conflict resolution tasks)
   - Proceed to next phase

### Example: Parallel FizzBuzz Computation

**Graph Instance**: `./spawn-graph/2025-01-02-1430-parallel-fizzbuzz/`

**TASK.md**:
```markdown
# Parallel FizzBuzz Analysis
Generate FizzBuzz for numbers 1-100 with parallel computation and analysis
```

**PLAN.md**:
```markdown
# Execution Plan

## Dependency Graph
```
phase01-analysis
├── task01-range-partition    → phase02-compute/task01, task02, task03
├── task02-pattern-study       → phase02-compute/task04
└── task03-optimization-plan   → phase02-compute/task04

phase02-compute
├── task01-fizzbuzz-1-33      → phase03-merge/task01
├── task02-fizzbuzz-34-66     → phase03-merge/task01
├── task03-fizzbuzz-67-100    → phase03-merge/task01
└── task04-optimized-algo      → phase03-merge/task02

phase03-merge
├── task01-combine-results     → phase04-analysis/task01
└── task02-benchmark           → phase04-analysis/task01

phase04-analysis
└── task01-final-report
```

## Phases
- Phase 1: Analysis and planning (3 parallel tasks)
- Phase 2: Computation (4 parallel tasks)
- Phase 3: Merging and benchmarking (2 parallel tasks)
- Phase 4: Final analysis (1 task)
```

**Parallel Execution Visualization**:
```
Time →
T0: [Analysis Task 1] [Analysis Task 2] [Analysis Task 3]
T1: [Compute 1-33] [Compute 34-66] [Compute 67-100] [Optimized Algo]
T2: [Merge Results] [Benchmark]
T3: [Final Report]
```

**Agent Work Example (Phase 2, Task 1)**:
```bash
# CRITICAL: Agent starts where spawning agent was!
# If spawning agent was in /home/user/myproject/src/utils/, 
# then agent starts in /home/user/myproject/spawn-graph/2025-01-02-1430-parallel-fizzbuzz/phase02-compute/task01-fizzbuzz-1-33/src/utils/

# First, navigate to worktree root
cd "$(git rev-parse --show-toplevel)"
# Now we're at: /home/user/myproject/spawn-graph/2025-01-02-1430-parallel-fizzbuzz/phase02-compute/task01-fizzbuzz-1-33/

# We are now in {task-dir} for Phase 2, Task 1
# pwd is /home/user/myproject/spawn-graph/2025-01-02-1430-parallel-fizzbuzz/phase02-compute/task01-fizzbuzz-1-33/
# This is a separate working directory created with:
# git worktree add ./spawn-graph/2025-01-02-1430-parallel-fizzbuzz/phase02-compute/task01-fizzbuzz-1-33 \
#     -b spawn-graph/2025-01-02-1430-parallel-fizzbuzz/phase02-compute/task01-fizzbuzz-1-33

# Create {task-output-dir} for this task (note the path duplication!)
mkdir -p spawn-graph/2025-01-02-1430-parallel-fizzbuzz/phase02-compute/task01-fizzbuzz-1-33/

# The full path of {task-output-dir} is:
# /home/user/myproject/spawn-graph/2025-01-02-1430-parallel-fizzbuzz/phase02-compute/task01-fizzbuzz-1-33/spawn-graph/2025-01-02-1430-parallel-fizzbuzz/phase02-compute/task01-fizzbuzz-1-33/

# Write progress (append to track history)
cat >> spawn-graph/2025-01-02-1430-parallel-fizzbuzz/phase02-compute/task01-fizzbuzz-1-33/PROGRESS.md << EOF
## Progress update - commit $(git rev-parse --short HEAD) @ $(date -u +"%Y-%m-%d %H:%M:%S UTC")

- Starting FizzBuzz computation for range 1-33
- Implementing standard algorithm
- Added unit tests
- Performance optimizations applied

EOF

# Do the actual work
cat > src/fizzbuzz_1_33.py << 'EOF'
def fizzbuzz_range_1_33():
    results = []
    for i in range(1, 34):
        if i % 15 == 0:
            results.append("FizzBuzz")
        elif i % 3 == 0:
            results.append("Fizz")
        elif i % 5 == 0:
            results.append("Buzz")
        else:
            results.append(str(i))
    return results
EOF

# Commit work
git add -A
git commit -m "feat: implement fizzbuzz for range 1-33"

# Write tests
cat > tests/test_fizzbuzz_1_33.py << 'EOF'
# ... test implementation ...
EOF

git add -A
git commit -m "test: add comprehensive test coverage"

# CRITICAL: Quality checks before finalizing
echo "=== Starting quality checks on my contribution ==="

# 1. Pre-commit checks
echo "Checking what files I modified..."
MY_FILES=$(git diff --name-only main...HEAD)
echo "Files I changed: $MY_FILES"

if [ -n "$MY_FILES" ]; then
    echo "Running pre-commit checks on my changes..."
    pre-commit run --files $MY_FILES
    
    # If pre-commit fails on MY files, fix issues
    while ! pre-commit run --files $MY_FILES; do
        echo "Pre-commit checks failed on my code, fixing issues..."
        git add $MY_FILES
        git commit -m "style: fix formatting and linting issues in my code"
    done
    
    echo "Pre-commit checks passed on my changes!"
fi

# 2. Self-review and improvements
echo "Performing self-review of my code..."

# Example: Improving the fizzbuzz function after review
cat > src/fizzbuzz_1_33.py << 'EOF'
"""Generate FizzBuzz sequence for numbers 1-33."""
from typing import List

def fizzbuzz_range_1_33() -> List[str]:
    """
    Generate FizzBuzz sequence for numbers 1 through 33.
    
    Returns:
        List of strings where:
        - Numbers divisible by 15 are replaced with "FizzBuzz"
        - Numbers divisible by 3 are replaced with "Fizz"
        - Numbers divisible by 5 are replaced with "Buzz"
        - Other numbers are converted to strings
    """
    results = []
    for i in range(1, 34):
        if i % 15 == 0:
            results.append("FizzBuzz")
        elif i % 3 == 0:
            results.append("Fizz")
        elif i % 5 == 0:
            results.append("Buzz")
        else:
            results.append(str(i))
    return results


# After review, realized we could make this more efficient:
def fizzbuzz_range_1_33_optimized() -> List[str]:
    """Optimized version using list comprehension."""
    def fizzbuzz_value(n: int) -> str:
        if n % 15 == 0:
            return "FizzBuzz"
        elif n % 3 == 0:
            return "Fizz"
        elif n % 5 == 0:
            return "Buzz"
        return str(n)
    
    return [fizzbuzz_value(i) for i in range(1, 34)]
EOF

# 3. Run tests to ensure nothing broke
echo "Running tests..."
pytest tests/test_fizzbuzz_1_33.py -v

# 4. Check for any debug prints or TODOs
echo "Checking for debug artifacts..."
grep -n "print(" src/fizzbuzz_1_33.py || echo "No debug prints found ✓"
grep -n "TODO\|FIXME\|XXX" src/fizzbuzz_1_33.py || echo "No TODOs found ✓"

# 5. Verify no hardcoded values that should be configurable
echo "Checking for magic numbers..."
# In this case, 1-33 range is the requirement, so it's OK

# 6. Final commit with improvements
git add -A
git commit -m "refactor: improve code quality based on self-review"

echo "=== Quality checks complete! ==="

# Final output goes in task output directory
# We're still in {task-dir}, so we write to the relative path:
cat > spawn-graph/2025-01-02-1430-parallel-fizzbuzz/phase02-compute/task01-fizzbuzz-1-33/OUTPUT.md << 'EOF'
STATUS: SUCCESS

Generated FizzBuzz for numbers 1-33
- Implementation: src/fizzbuzz_1_33.py
- Tests: tests/test_fizzbuzz_1_33.py
- Test coverage: 100%
- Performance: 0.002s for range

Quality Checks Performed:
- Pre-commit: ✅ All checks passed on my changes
- Self-review: ✅ Refactored for clarity and added optimized version
- Documentation: ✅ Added comprehensive docstrings
- Testing: ✅ All tests pass
- Cleanup: ✅ No debug code or TODOs remaining
- Type hints: ✅ Full type annotations added

Results preview:
1, 2, Fizz, 4, Buzz, Fizz, 7, 8, Fizz, Buzz, 11, Fizz, 13, 14, FizzBuzz...
EOF

# The full path of OUTPUT.md is:
# /home/user/myproject/spawn-graph/2025-01-02-1430-parallel-fizzbuzz/phase02-compute/task01-fizzbuzz-1-33/spawn-graph/2025-01-02-1430-parallel-fizzbuzz/phase02-compute/task01-fizzbuzz-1-33/OUTPUT.md

git add -A
git commit -m "docs: add final output and results"
```

### Phase Completion: Reviewing and Merging Results

**IMPORTANT: This is what the spawning agent MUST do after Phase 2 completes:**

```bash
#!/bin/bash
# SPAWNING AGENT MUST RUN THESE COMMANDS

# CRITICAL: Always operate from git repository root!
cd "$(git rev-parse --show-toplevel)"

# Set variables
INSTANCE="2025-01-02-1430-parallel-fizzbuzz"
PHASE="phase02-compute"

# 1. First, check the status of all tasks
echo "=== Checking task results ==="
for TASK_DIR in ./spawn-graph/${INSTANCE}/${PHASE}/task*/; do
    if [ -d "$TASK_DIR" ]; then
        TASK_NAME=$(basename "$TASK_DIR")
        BRANCH="spawn-graph/${INSTANCE}/${PHASE}/${TASK_NAME}"
        OUTPUT_PATH="spawn-graph/${INSTANCE}/${PHASE}/${TASK_NAME}/OUTPUT.md"
        
        echo "Checking ${TASK_NAME}..."
        
        # Try to get OUTPUT.md from the branch
        if git show "${BRANCH}:${OUTPUT_PATH}" > /tmp/output_check.md 2>/dev/null; then
            STATUS=$(grep "^STATUS:" /tmp/output_check.md | cut -d' ' -f2)
            echo "  Status: ${STATUS}"
        else
            echo "  Status: NO OUTPUT FILE"
        fi
    fi
done

# 2. Merge successful tasks
echo -e "\n=== Merging successful tasks ==="
git checkout main

for TASK_DIR in "$SPAWN_GRAPH_BASE/${INSTANCE}/${PHASE}"/task*/; do
    if [ -d "$TASK_DIR" ]; then
        TASK_NAME=$(basename "$TASK_DIR")
        BRANCH="spawn-graph/${INSTANCE}/${PHASE}/${TASK_NAME}"
        OUTPUT_PATH="spawn-graph/${INSTANCE}/${PHASE}/${TASK_NAME}/OUTPUT.md"
        
        # Check if OUTPUT.md exists and contains SUCCESS
        if git show "${BRANCH}:${OUTPUT_PATH}" 2>/dev/null | grep -q "^STATUS: SUCCESS"; then
            echo "Merging ${TASK_NAME}..."
            git merge --no-ff "${BRANCH}" -m "Merge ${TASK_NAME} from spawn-graph ${PHASE}"
        else
            echo "Skipping ${TASK_NAME} (not successful)"
        fi
    fi
done

# 3. Clean up worktrees
echo -e "\n=== Cleaning up worktrees ==="
for TASK_DIR in "$SPAWN_GRAPH_BASE/${INSTANCE}/${PHASE}"/task*/; do
    if [ -d "$TASK_DIR" ]; then
        echo "Removing worktree: ${TASK_DIR}"
        git worktree remove "${TASK_DIR}" --force
    fi
done

# 4. Delete merged branches
echo -e "\n=== Deleting merged branches ==="
for TASK_DIR in "$SPAWN_GRAPH_BASE/${INSTANCE}/${PHASE}"/task*/; do
    TASK_NAME=$(basename "$TASK_DIR")
    BRANCH="spawn-graph/${INSTANCE}/${PHASE}/${TASK_NAME}"
    
    # Only delete if fully merged
    if git branch --merged | grep -q "${BRANCH}"; then
        echo "Deleting branch: ${BRANCH}"
        git branch -d "${BRANCH}"
    else
        echo "Keeping unmerged branch: ${BRANCH}"
    fi
done

# 5. List any worktrees that remain (there should be none)
echo -e "\n=== Remaining worktrees ==="
git worktree list

# Example output:
# === Checking task results ===
# Checking task01-fizzbuzz-1-33...
#   Status: SUCCESS
# Checking task02-fizzbuzz-34-66...
#   Status: SUCCESS
# Checking task03-fizzbuzz-67-100...
#   Status: BLOCKED
# Checking task04-optimized-algo...
#   Status: SUCCESS
#
# === Merging successful tasks ===
# Merging task01-fizzbuzz-1-33...
# Merging task02-fizzbuzz-34-66...
# Skipping task03-fizzbuzz-67-100 (not successful)
# Merging task04-optimized-algo...
#
# === Cleaning up worktrees ===
# Removing worktree: ./spawn-graph/2025-01-02-1430-parallel-fizzbuzz/phase02-compute/task01-fizzbuzz-1-33/
# Removing worktree: ./spawn-graph/2025-01-02-1430-parallel-fizzbuzz/phase02-compute/task02-fizzbuzz-34-66/
# Removing worktree: ./spawn-graph/2025-01-02-1430-parallel-fizzbuzz/phase02-compute/task03-fizzbuzz-67-100/
# Removing worktree: ./spawn-graph/2025-01-02-1430-parallel-fizzbuzz/phase02-compute/task04-optimized-algo/
```

**After Merging All Successful Tasks**:
```
[main branch after merge]
├── src/
│   ├── fizzbuzz_1_33.py
│   ├── fizzbuzz_34_66.py
│   ├── fizzbuzz_67_100.py         # Missing due to blocked task
│   └── fizzbuzz_optimized.py
├── tests/
│   └── [test files]
└── spawn-graph/2025-01-02-1430-parallel-fizzbuzz/
    └── phase02-compute/
        ├── task01-fizzbuzz-1-33/
        │   ├── PROGRESS.md
        │   └── OUTPUT.md
        ├── task02-fizzbuzz-34-66/
        │   ├── PROGRESS.md
        │   └── OUTPUT.md
        ├── task03-fizzbuzz-67-100/
        │   ├── PROGRESS.md
        │   └── OUTPUT.md          # Shows BLOCKED status
        └── task04-optimized-algo/
            ├── PROGRESS.md
            └── OUTPUT.md
```

### Benefits of Path Duplication

1. **Conflict-Free Merges**: Each task's output has a unique path
2. **Complete History**: All task outputs preserved in final merge
3. **Easy Navigation**: Can review any task's work in isolation
4. **Debugging**: Full paper trail of what each agent did
5. **Reusability**: Can cherry-pick specific task implementations

**Note on Storage Location**: While centralized worktree storage would be cleaner, Claude's security model requires worktrees to be within the repository. See [CLAUDE_SECURITY_MODEL.md](~/code/ducktape/dotfiles/claude-commands/CLAUDE_SECURITY_MODEL.md) for technical details.

### When to Use Worktree vs Naive

**Use Worktree Workflow when**:
- Complex refactoring across many files
- High risk of merge conflicts
- Need clean git history per subtask
- Want ability to cherry-pick specific task results
- Running many tasks in parallel (>5)
- Need full audit trail of parallel work

**Use Naive Workflow when**:
- Simple task decomposition
- Low conflict risk
- Quick experiments
- Tasks mostly read-only or in different areas
- Don't need isolated git history

## Example Execution

Given a task like "Refactor the client library to use modern patterns":

### Generated Graph:
```
A1: Define new interfaces (2d)
├─→ A2: Create type system (3d)
│   ├─→ A3: Implement core classes (4d)
│   └─→ A4: Build validators (2d)
├─→ B1: Design API surface (2d)
│   └─→ B2: Implement API (5d)
└─→ C1: Plan migration (1d)
    └─→ C2: Write migration tools (3d)

Critical Path: A1 → A2 → A3 = 9 days
Parallel Path: 4-5 days with 3 agents
```

### Execution Waves:
- **Wave 1**: Spawn 1 agent for A1
- **Wave 2**: Spawn 3 agents for A2, B1, C1
- **Wave 3**: Spawn 3 agents for A3, A4, B2
- **Wave 4**: Spawn 1 agent for C2

## Implementation

The actual implementation uses Claude's Task tool to spawn parallel agents:

### Step 1: Analyze and Create Graph
First, analyze the task and create the dependency graph with all subtasks clearly defined.

### Step 2: Execute in Waves
For each wave, use multiple Task tool invocations in a SINGLE message:

```
# Example of spawning Wave 1 with 15 parallel tasks:
<multiple_tool_use>
  <invoke name="Task">
    <parameter name="description">A1.1 Basic Types</parameter>
    <parameter name="prompt">Create NodeId, EdgeId, WorkspaceId type definitions...</parameter>
  </invoke>
  <invoke name="Task">
    <parameter name="description">A1.2 Core Interfaces</parameter>
    <parameter name="prompt">Define INode, IEdge, IStore interfaces...</parameter>
  </invoke>
  <invoke name="Task">
    <parameter name="description">B1.1 WebSocket Wrapper</parameter>
    <parameter name="prompt">Implement WebSocket connection wrapper...</parameter>
  </invoke>
  ... (12 more Task invocations)
</multiple_tool_use>
```

### Step 3: Collect Results
Each Task tool returns a result. Process these results and determine the next wave of ready tasks.

### Step 4: Repeat Until Complete
Continue spawning waves of parallel tasks until the entire graph is processed.

## Agent Instructions Template

Each spawned agent receives:

```markdown
You are agent {agent_id} working on task {task_id}.

## CRITICAL: You are working in a Git Worktree
- Your worktree root: {absolute_worktree_path}
- Your starting directory: {current_working_directory}
- IMPORTANT: You may not be at worktree root! The spawning agent's cwd is preserved.
- First action: `cd "$(git rev-parse --show-toplevel)"` to go to worktree root
- This is a SEPARATE working copy from the main repository
- You have your own branch: spawn-graph/{instance}/{phase}/{task}
- Other agents are working in parallel in their own worktrees
- Your changes will be merged back to main after completion
- NOTE: Worktrees are in ./spawn-graph/ due to security restrictions (see CLAUDE_SECURITY_MODEL.md)

## Your Task
{task_description}

## Dependencies Completed
{completed_dependencies_and_outputs}

## Your Deliverables
{expected_outputs}

## Integration Points
{how_your_output_connects_to_other_tasks}

## QUALITY REQUIREMENTS
Before marking your task complete:
1. Run pre-commit on YOUR changed files only
2. Do a thorough self-review of your code:
   - Is it clear and well-documented?
   - Are names descriptive?
   - Can anything be simplified?
3. Check all links/references work
4. Run relevant tests
5. Remove debug code and TODOs
6. Think: What else needs cleanup for THIS specific task?
7. Actually make the improvements!
8. **CRITICAL: Ensure clean worktree**:
   - Commit ALL your work
   - Run `git status --porcelain` - must show NO output
   - If any files remain, commit them before marking complete

Only mark SUCCESS when your code is high quality AND worktree is clean.

## Constraints
- Time limit: {estimated_duration}
- Must produce: {output_format}
- Must coordinate with: {related_agents}
```

## Best Practices

1. **Granularity**: Break tasks down to 1-4 hour chunks for optimal parallelism
2. **Dependencies**: Make dependencies explicit, not implicit
3. **Interfaces**: Define clear interfaces between tasks
4. **Checkpoints**: Built-in validation at wave boundaries
5. **Fallbacks**: Have strategies for agent failures
6. **Storage Location**: Worktrees must be in `./spawn-graph/` within the repo (not centralized) due to Claude's security model - see [CLAUDE_SECURITY_MODEL.md](~/code/ducktape/dotfiles/claude-commands/CLAUDE_SECURITY_MODEL.md)

## When to Use

Perfect for:
- Large refactoring projects
- Multi-component system design
- Complex documentation tasks
- Research projects with multiple threads
- Any task with natural parallelism

Not suitable for:
- Strictly sequential tasks
- Tasks requiring continuous context
- Small tasks (< 2 hours)
- Tasks with unclear requirements

## Output Format

The command produces:
1. Dependency graph visualization
2. Execution plan with timeline
3. Wave-by-wave progress updates
4. Final integrated result
5. Performance metrics (speedup achieved)

## Advanced Features

### Resource Constraints
```
/spawn-graph --max-agents=5 --memory-limit=8GB
```

### Priority Scheduling
```
/spawn-graph --optimize=critical-path
/spawn-graph --optimize=resource-usage
```

### Checkpoint Recovery
```
/spawn-graph --checkpoint=every-wave
/spawn-graph --resume-from=wave-3
```

## How It Actually Works

The magic happens through Claude's ability to invoke multiple Task tools in parallel:

1. **Single Message, Multiple Tasks**: When you invoke the Task tool multiple times in one message, Claude spawns that many agents to work in parallel.

2. **True Parallelism**: Each Task tool invocation creates an independent agent that works on its assigned task without blocking others.

3. **Result Collection**: All agents return their results, which can then be processed to determine the next wave.

### Example Execution Pattern

```
U: /spawn-graph

Claude: I'll execute the first wave of 15 independent tasks:
[Invokes 15 Task tools in one message]

[15 agents work in parallel]

[Results returned]

Claude: Wave 1 complete. Based on results, Wave 2 has 20 ready tasks:
[Invokes 20 Task tools in one message]

[Process continues until graph is complete]
```

## Related Commands

- `/spawn` - Simple multi-agent parallelism without dependency management
- `/plan` - Create execution plan without spawning agents
- `/coordinate` - Manage already-running parallel agents

## Implementation Note

This command leverages Claude's Task tool capability:
1. **Dependency graph analysis** - Break down complex tasks into DAG
2. **Topological sorting** - Determine execution order
3. **Wave-based execution** - Group tasks by dependency level
4. **Parallel Task invocation** - Use multiple Task tools in one message
5. **Result integration** - Combine outputs from all agents

The key innovation is using multiple Task tool invocations in a single message to achieve true parallel execution while respecting dependencies. Each wave spawns N agents where N is the number of ready tasks.
