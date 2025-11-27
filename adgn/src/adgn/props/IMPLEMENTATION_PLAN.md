# Props Run Management: Implementation Plan

## Definition of Done

When this implementation is complete, the following MUST all be true:

### 1. Clean Run Directory Structure
- ✅ Every run has exactly 3 files: `input.json`, `output.json`, `events.jsonl`
- ✅ NO redundant files: NO `critique.json`, NO `grade.json`, NO `unknowns/*.yaml`, NO `metadata.json`
- ✅ All files go directly into run directory (no extra subdirectories like `transcript/` or `unknowns/`)
- ✅ Path structure: `runs/{split}/{run_type}/{scope_id}/{timestamp}/`

### 2. Type-Safe Data Loading
- ✅ All run discovery loads typed `input.json`/`output.json` using Pydantic
- ✅ NO manual path parsing to extract metadata (specimen, split, timestamp, etc.)
- ✅ Metadata comes from typed models, NOT from filesystem paths
- ✅ `cluster_unknowns.py` loads `GraderOutput` directly, extracts from `grade.novel_critique_issues`

### 3. Test Quality
- ✅ NO tests that are always skipped (no `@pytest.mark.skip` without removal plan)
- ✅ All tests either pass or are marked `live_llm`/`integration` with clear reason
- ✅ Test coverage for: scope validation, path computation, discriminated unions, serialization

### 4. Consistency
- ✅ All specimen slugs validated: exactly one slash (`{project}/{date}`)
- ✅ Split computed from specimen membership (via `splits.py` lookup)
- ✅ Paths computed from typed objects (never parsed)
- ✅ `isinstance()` checks for discriminated unions (not `.tag` access)

### 5. Implementation Complete
- ✅ `agent_runners.py` simplified: returns result objects, no file writes except via handlers
- ✅ `run_managers.py` handles all persistence: `input.json`, `output.json` via `save_input()`/`save_output()`
- ✅ `cluster_unknowns.py` rewritten: discovers via glob, loads typed outputs, no YAML export
- ✅ All imports cleaned up (no unused imports from removed functions)
- ✅ Runs directory computed once and passed down: `discover_grader_runs(runs_dir)` requires explicit path
  - ⚠️ TODO: Audit all callers to pass `runs_dir` explicitly (no fallbacks to `pkg_dir() / "runs"`)

### 6. Path Token Deduplication (TODO)
- ❌ Path tokens ("grader", "critic", "output.json", "input.json", "events.jsonl") must not be duplicated
- ❌ Current violations (audit results):
  - `cluster_unknowns.py:66`: `runs_dir.rglob("*/grader/*/*/output.json")` - hardcoded pattern
  - `cluster_unknowns.py:88,98`: `run_dir / "input.json"`, `run_dir / "output.json"` - direct path construction
  - `run_managers.py:134,149,188,202`: Multiple `/ "input.json"` and `/ "output.json"` duplications
  - `run_managers.py:291`: `return "grader"` - hardcoded run type string
  - `grade_runner.py:59`: `transcript_out_dir / "grader"` - hardcoded subdirectory
  - `per_file_eval.py:243`: `file_run_dir / "grader"` - hardcoded subdirectory
- ❌ Solution: `RunsContext` object pattern:
  - Holds base runs directory
  - Provides methods for path derivation: `discover_grader_runs()`, `run_input_path(run_dir)`, `run_output_path(run_dir)`
  - Centralizes path token constants (no string literals in business logic)
  - Injected at entry point level (CLI commands, MCP tools)
- ⚠️ Implementation steps:
  1. Create `runs_context.py` with `RunsContext` class and path derivation methods
  2. Define constants: `RUN_TYPE_GRADER`, `RUN_TYPE_CRITIC`, `INPUT_JSON`, `OUTPUT_JSON`, `EVENTS_JSONL`
  3. Refactor `run_managers.py` to use context methods
  4. Refactor `cluster_unknowns.py` discovery pattern
  5. Update all callers to inject `RunsContext` instead of bare `Path`

## Executive Summary

**Goal**: Unified, type-safe run management with atomic runs + orchestrated sessions

**Status**:
- ✅ Specimen migrated: `misc/2025-08-29-pyright_watch_report` added to splits
- ✅ Design complete: Types, models, and path structure defined
- ✅ Core implementation started: redundant files removed
- 🎯 Next: Complete cluster_unknowns.py rewrite

**Key Decisions**:
- NO migration of existing run data (old paths stay where they are)
- NO legacy mount points (clean break to new structure)
- Atomic runs are separate, referenceable units
- Orchestrated sessions reference atomic runs (no data duplication)
- Clean 3-file structure: input.json, output.json, events.jsonl ONLY

## Directory Structure (Final)

The clean, minimal structure with NO redundant files:

```
runs/
  {train,valid,test}/         # Split-level (only for atomic runs)
    {critic,grader}/
      specimen:{project}/{date}/
        TIMESTAMP/
          input.json          # CriticInput or GraderInput (typed scope)
          output.json         # CriticOutput or GraderOutput (full structured result)
          events.jsonl        # Agent transcript (all events with timestamps)

  evals/                      # Orchestrated sessions (no split nesting)
    full-split:{split}/
      TIMESTAMP/
        input.json            # FullSplitEvalInput
        output.json           # FullSplitEvalOutput (references atomic runs)

  cluster/                    # Cluster unknowns workflow
    TIMESTAMP/
      input.json              # Clustering inputs
      output.json             # Clustering results
      {project}/{date}/       # Per-specimen cluster outputs
        clusters.json
```

**What was removed** (redundant files that existed in old structure):
- ❌ `critique.json` - redundant (data already in `output.json` as `CriticOutput`)
- ❌ `grade.json` - redundant (data already in `output.json` as `GraderOutput`)
- ❌ `unknowns/*.yaml` - redundant export format (extract from `output.json` directly)
- ❌ `metadata.json` - redundant (only contained timestamp, not needed)
- ❌ `transcript/` subdirectory - files go directly into run directory

**Data extraction patterns**:
- Unknown issues: Load `output.json` as `GraderOutput`, extract from `grade.novel_critique_issues`
- Specimen/split: Load `input.json` as `GraderInput`/`CriticInput`, read from `scope.specimen_slug` and `scope.split`
- Timestamps: Read from run directory name (YYYYMMDDTHHMMSS format)

**Path invariants**:
1. All specimen slugs have exactly one slash: `{project}/{date-sequence}`
2. Atomic runs always under `{split}/{run_type}/specimen:{slug}/TIMESTAMP/`
3. Orchestrated sessions never nest under split
4. Every run has `input.json` and `output.json`

## How Paths Thread Through The System

### Core Concept: Path Composition

**Paths are NEVER parsed - always computed from typed objects**

```
Path = runs_root / relative_path
       ↑             ↑
       constant      computed from scope + timestamp

relative_path = f"{scope.split}/{run_type}/{scope.scope_id()}/{timestamp}"
                   ↑             ↑          ↑                   ↑
                   from scope    constant   from scope          timestamped
```

### Thread 1: Scope → Path

```python
# User provides specimen slug (validated by Pydantic)
specimen = "ducktape/2025-11-26-00"  # SpecimenSlug type validates pattern

# Create scope (embeds specimen, computes split on demand)
scope = SpecimenScope(specimen=specimen)

# Scope knows its split (computed from specimen membership)
print(scope.split)  # Split.TRAIN (from splits.py lookup)

# Scope knows how to encode itself for filesystem
print(scope.scope_id())  # "specimen:ducktape/2025-11-26-00"
```

**Key insight**: Scope owns split computation and filesystem encoding. No external code needs to know how.

### Thread 2: Input → Path (via Run)

```python
# Create input (scope + run params)
critic_input = CriticInput(
    scope=scope,
    model="gpt-5",
    system_prompt="Review this code..."
)

# Create run manager (input + root)
run = CriticRun(critic_input, runs_root)

# Run computes path from input data
print(run.relative_path)
# "train/critic/specimen:ducktape/2025-11-26-00/20251127_143022"
#   ↑      ↑       ↑                              ↑
#   split  type    scope_id()                     timestamp
#   from   from    from scope                     from run
#   scope  run
```

**Path computation** (in `AgentRun.relative_path`):
```python
@property
def relative_path(self) -> str:
    return f"{self.input.scope.split}/{self.run_type()}/{self.input.scope.scope_id()}/{self.timestamp}"
```

**All paths derived from this**:
```python
@property
def root(self) -> Path:
    return self.runs_root / self.relative_path

@property
def input_path(self) -> Path:
    return self.root / "input.json"

@property
def output_path(self) -> Path:
    return self.root / "output.json"
```

### Thread 3: Critic → Grader Linkage

**Option A: In-memory (no path needed)**
```python
# Run critic
critic_run = CriticRun(critic_input, runs_root)
critic_output = await critic_run.run()

# Create grader input (embeds critic result)
grader_input = GraderInput.from_critic_output(
    critic_output=critic_output,
    critic_scope=critic_input.scope,  # Extracts specimen
    model="gpt-5",
    critic_run_path=critic_run.relative_path  # Optional provenance
)

# Grader has FULL critic result embedded (no load needed)
print(len(grader_input.critic_result.issues))  # Direct access
```

**Option B: From disk (path-based)**
```python
# Load grader input from critic run path
grader_input = GraderInput.from_critic_run(
    critic_run_path="train/critic/specimen:ducktape/2025-11-26-00/20251127_143022",
    runs_root=runs_root,
    model="gpt-5"
)

# Factory loads input.json + output.json, reconstructs everything
print(grader_input.scope.specimen)  # From critic's input
print(grader_input.scope.split)     # Computed from specimen
print(len(grader_input.critic_result.issues))  # From critic's output
```

### Thread 4: Discovery (Finding Runs)

**Old way** (brittle path parsing):
```python
# FRAGILE: Parse path components to extract specimen
parts = path.parts
idx = parts.index("unknowns")
specimen = parts[idx - 1]  # What if depth changes?
```

**New way** (type-safe glob + load):
```python
# Glob for pattern
unknown_paths = runs_root.glob("*/grader/specimen:*/*/unknowns/*.yaml")

# For each path, LOAD input.json to get typed data
for unknown_file in unknown_paths:
    run_dir = unknown_file.parents[1]  # unknowns/../
    input_data = GraderInput.model_validate_json(
        (run_dir / "input.json").read_text()
    )
    # Now we have typed access
    print(input_data.scope.specimen)  # Type-safe
    print(input_data.scope.split)     # Computed
```

### Thread 5: Orchestrated Sessions

```python
class FullSplitEvalInput(BaseModel):
    split: Split
    specimens: list[SpecimenSlug]
    system_prompt: str
    model: str

class FullSplitEvalRun:
    @property
    def root(self) -> Path:
        # Override: no split nesting for sessions
        return self.runs_root / "evals" / f"full-split:{self.input.split}" / self.timestamp

    async def _execute(self):
        atomic_runs = []

        # Launch atomic critic + grader for each specimen
        for specimen in self.input.specimens:
            # Create scope
            scope = SpecimenScope(specimen=specimen)

            # Run critic (atomic)
            critic_input = CriticInput(scope=scope, model=self.input.model, system_prompt=self.input.system_prompt)
            critic_run = CriticRun(critic_input, self.runs_root)
            critic_output = await critic_run.run()

            # Run grader (atomic)
            grader_input = GraderInput.from_critic_output(
                critic_output=critic_output,
                critic_scope=scope,
                model=self.input.model,
                critic_run_path=critic_run.relative_path
            )
            grader_run = GraderRun(grader_input, self.runs_root)
            grader_output = await grader_run.run()

            # Store references (not data)
            atomic_runs.append({
                "specimen": specimen,
                "critic_run": critic_run.relative_path,
                "grader_run": grader_run.relative_path,
            })

        # Return references + aggregate metrics
        return FullSplitEvalResult(
            atomic_runs=atomic_runs,
            aggregate_metrics=compute_aggregates(atomic_runs)
        )
```

**Session output references atomic runs**:
```json
{
  "atomic_runs": [
    {
      "specimen": "ducktape/2025-11-26-00",
      "critic_run": "train/critic/specimen:ducktape/2025-11-26-00/20251127_143022",
      "grader_run": "train/grader/specimen:ducktape/2025-11-26-00/20251127_143055"
    }
  ]
}
```

## Implementation Phases

### Phase 1: Core Types (runs/models.py, ids.py)

**Files to create/update**:
1. `ids.py`: Add `SpecimenSlug` type with regex validation
2. `runs/models.py`: Create scope types, input/output models
3. `runs/runs.py`: Create `AgentRun`, `CriticRun`, `GraderRun` classes

**Dependencies**: None (new code)

**Testing**:
```python
# Test specimen slug validation
assert SpecimenSlug("ducktape/2025-11-26-00")  # Valid
with pytest.raises(ValidationError):
    SpecimenSlug("2025-08-29-pyright")  # No slash

# Test scope split computation
scope = SpecimenScope(specimen="ducktape/2025-11-26-00")
assert scope.split == Split.TRAIN
assert scope.scope_id() == "specimen:ducktape/2025-11-26-00"

# Test path computation
critic_input = CriticInput(scope=scope, model="gpt-5", system_prompt="...")
run = CriticRun(critic_input, Path("/tmp/runs"))
assert run.relative_path == "train/critic/specimen:ducktape/2025-11-26-00/{timestamp}"
```

### Phase 2: Refactor Existing Runners (agent_runners.py, grade_runner.py)

**Current** (`agent_runners.py`):
```python
async def run_critic_agent(specimen_rec, content_root, system_prompt, client, transcript_dir, ...):
    # Takes raw paths, writes to transcript_dir
    ...
```

**New** (`CriticRun._execute()`):
```python
class CriticRun(AgentRun[CriticInput, CriticOutput]):
    async def _execute(self) -> CriticResult:
        # Load specimen from self.input.scope.specimen
        async with SpecimenRegistry.load_and_hydrate(self.input.scope.specimen) as (rec, content_root):
            # Run agent
            result = await run_critic_agent(
                specimen_rec=rec,
                content_root=content_root,
                system_prompt=self.input.system_prompt,
                client=client,
                transcript_dir=self.root,  # Write to run.root directly
                ...
            )
            return CriticResult(issues=result.issues)
```

**Changes**:
- ✅ Wrap existing `run_critic_agent` / `run_grader_agent` in new run classes
- ✅ Pass `self.root` instead of caller-provided paths
- ✅ Write input.json / output.json in run lifecycle
- ✅ Track cost in `self._computed_cost`

### Phase 3: Update cluster_unknowns.py

**Current**:
```python
def discover_unknown_yaml_paths(root: Path | None = None) -> list[Path]:
    runs_root = (root or pkg_dir()) / "runs" / "prompt_optimize"  # WRONG PATH
    return sorted(runs_root.rglob("*/unknowns/*.yaml"))

def load_unknowns(paths: Iterable[Path]) -> list[UnknownIssue]:
    # Parses path to extract specimen (FRAGILE)
    idx = parts.index("unknowns")
    specimen = parts[idx - 1]
    run_ts = parts[idx - 2]
```

**New**:
```python
def discover_unknown_yaml_paths(root: Path | None = None, split: str | None = None) -> list[Path]:
    """Discover unknowns from new structure.

    Returns unknowns from: runs/{split}/grader/specimen:*/TIMESTAMP/unknowns/*.yaml
    """
    runs_root = root or pkg_dir() / "runs"

    if split:
        pattern = f"{split}/grader/*/*/unknowns/*.yaml"
    else:
        pattern = "*/grader/*/*/unknowns/*.yaml"

    return sorted(runs_root.glob(pattern))

def load_unknowns(paths: Iterable[Path]) -> list[UnknownIssue]:
    """Load unknowns by reading run input.json (no path parsing)."""
    issues: list[UnknownIssue] = []

    for yp in paths:
        data = yaml.safe_load(yp.read_text(encoding="utf-8")) or {}
        core = (data or {}).get("core") or {}
        occ = (data or {}).get("occurrence") or {}

        # Load grader input to get specimen (type-safe)
        run_dir = yp.parents[1]  # unknowns/../
        try:
            grader_input = GraderInput.model_validate_json(
                (run_dir / "input.json").read_text()
            )
            specimen = grader_input.scope.specimen
            timestamp = run_dir.name
        except Exception as e:
            logger.warning(f"Could not load input.json from {run_dir}: {e}")
            specimen = "UNKNOWN"
            timestamp = ""

        iid = str(core.get("id") or "")
        files = set((occ.get("files") or {}).keys())
        uid = f"{timestamp}:{specimen}:{iid}"

        issues.append(UnknownIssue(
            uid=uid,
            specimen=specimen,
            id=iid,
            should_flag=core.get("should_flag"),
            rationale=str(core.get("rationale") or ""),
            files=files,
            yaml_path=str(yp),
        ))

    return issues

# Update output path
def cluster_unknowns(...) -> Path:
    root = cast(Path, pkg_dir()) / "runs" / "cluster" / ts
    root.mkdir(parents=True, exist_ok=True)

    async def _run_all() -> Path:
        tasks = []
        for spec, items in by_spec.items():
            # Preserve specimen slug structure with slash
            out_spec = root / "results" / spec  # e.g., results/ducktape/2025-11-26-00/
            out_spec.mkdir(parents=True, exist_ok=True)
            tasks.append(...)
        ...
```

**Changes**:
- ✅ Update glob pattern to new structure
- ✅ Load input.json instead of parsing paths
- ✅ Change output from `cluster_unknowns/` to `cluster/`
- ✅ Preserve specimen slug with slash in output

### Phase 4: Refactor prompt_eval Server

**Big lift** - split orchestrated eval from atomic runs

**Before**: Single `_run_critic_and_grader()` function writes to `eval_dir/{specimen}/`

**After**: Use `CriticRun` and `GraderRun` classes

```python
@mcp.tool(flat=True)
async def eval_train_split(payload: EvalSplitInput) -> EvalTrainSplitOutput:
    """Run full split eval using atomic runs."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Create orchestrated session
    session_dir = evals_root / "full-split:train" / ts
    session_dir.mkdir(parents=True, exist_ok=True)

    # Write session input
    session_input = {
        "split": "train",
        "prompt_path": payload.prompt_path,
        "specimens": get_train_specimens(),
    }
    (session_dir / "input.json").write_text(json.dumps(session_input, indent=2))

    atomic_run_refs = []
    metrics = []

    # Run atomic critic + grader for each specimen
    for specimen in get_train_specimens():
        scope = SpecimenScope(specimen=specimen)

        # Critic
        critic_input = CriticInput(scope=scope, model=agent_model, system_prompt=prompt_text)
        critic_run = CriticRun(critic_input, atomic_runs_root)
        critic_output = await critic_run.run()

        # Grader
        grader_input = GraderInput.from_critic_output(
            critic_output=critic_output,
            critic_scope=scope,
            model=agent_model,
            critic_run_path=critic_run.relative_path
        )
        grader_run = GraderRun(grader_input, atomic_runs_root)
        grader_output = await grader_run.run()

        # Store reference
        atomic_run_refs.append({
            "specimen": specimen,
            "critic_run": critic_run.relative_path,
            "grader_run": grader_run.relative_path,
        })

        # Collect metrics
        metrics.append(MetricsRow(
            specimen=specimen,
            recall=grader_output.result.recall,
            reported_issue_ratios=grader_output.result.reported_issue_ratios,
            cost=critic_output.cost + grader_output.cost,
        ))

    # Write session output
    session_output = {
        "status": "success",
        "atomic_runs": atomic_run_refs,
        "aggregate_metrics": {...},
    }
    (session_dir / "output.json").write_text(json.dumps(session_output, indent=2))

    return EvalTrainSplitOutput(
        detailed_metrics=metrics,
        specimens=get_train_specimens(),
        cost=sum(m.cost for m in metrics),
        budget_remaining=...,
        detailed_artifacts_dir=str(session_dir),
    )
```

**Changes**:
- ✅ Replace `_run_critic_and_grader()` with `CriticRun` + `GraderRun`
- ✅ Create orchestrated session under `runs/evals/full-split:{split}/`
- ✅ Atomic runs go to `runs/{split}/{critic,grader}/specimen:*/`
- ✅ Session output references atomic runs (not data duplication)
- ⚠️ Major refactor - split across multiple PRs if needed

### Phase 5: Update CLI Commands

**prompt-eval command**:
```python
@app.command("prompt-eval")
async def prompt_eval(prompt: str, out_dir: Path | None, ...):
    atomic_runs_root = out_dir or (pkg_dir() / "runs")

    for specimen in get_train_specimens():
        # Use CriticRun + GraderRun
        scope = SpecimenScope(specimen=specimen)

        critic_input = CriticInput(scope=scope, model=model, system_prompt=prompt)
        critic_run = CriticRun(critic_input, atomic_runs_root)
        critic_output = await critic_run.run()

        grader_input = GraderInput.from_critic_output(...)
        grader_run = GraderRun(grader_input, atomic_runs_root)
        grader_output = await grader_run.run()

        print(f"[{specimen}] Recall: {grader_output.result.recall:.2%}")
```

**per-file-eval**:
```python
@app.command("per-file-eval")
async def cmd_per_file_eval(specimen: str, file_path: str, ...):
    scope = SpecimenFileScope(specimen=specimen, file_path=file_path)
    critic_input = CriticInput(scope=scope, model=model, system_prompt=prompt)

    run = CriticRun(critic_input, runs_root)
    output = await run.run()

    print(f"Path: {run.root}")
    print(f"Issues: {len(output.result.issues)}")
```

### Phase 6: Update Dependent Tools

1. **prompt_optimizer.py**: Update volume mounts to new structure
2. **Dashboards/analysis**: Update path references
3. **Documentation**: Update examples

## Consistency Checks

✅ **All paths computed from types** - No string parsing
✅ **Split always derived from specimen** - Single source of truth
✅ **Specimen slugs validated** - Regex enforces exactly one slash
✅ **Atomic runs referenceable** - Via `relative_path`
✅ **Orchestrated sessions separate** - No split nesting
✅ **Input/output always present** - Every run has both JSON files

## Can We Implement This?

**Yes, but in phases:**

1. **Phase 1-2** (Core types + refactor): ~3-5 days
   - Low risk: New code, existing behavior unchanged
   - Can test in isolation

2. **Phase 3** (cluster_unknowns): ~1 day
   - Medium risk: Existing tool changes
   - Can add backward compat for old paths
   - Test with existing unknowns

3. **Phase 4** (prompt_eval server): ~5-7 days
   - High risk: Major refactor of core eval workflow
   - Split into smaller PRs:
     - PR1: Add `CriticRun`/`GraderRun` alongside existing code
     - PR2: Update single-specimen tools to use new classes
     - PR3: Refactor full-split eval

4. **Phase 5** (CLI): ~2-3 days
   - Low risk: Commands are independent
   - Can update one at a time

5. **Phase 6** (dependent tools): ~2-3 days
   - Low risk: Update references

**Total estimate**: 13-19 days (split across multiple PRs)

## Risk Mitigation

1. **Backward compat in cluster_unknowns**: Search both old and new paths during transition
2. **Parallel implementation**: Keep old code working while adding new
3. **Gradual migration**: One tool at a time, starting with lowest risk
4. **Testing strategy**: Test each phase independently before moving to next

## Open Questions

None remaining. Design is complete and implementable.
