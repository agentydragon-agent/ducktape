# Props Run Management Design

## Overview

Unified structure for all props evaluation runs with type-safe management, computed paths, and hard-to-misuse APIs.

## Directory Structure

**Note**: All specimen slugs must have exactly one slash (`{project}/{date-sequence}`). Flat specimens (e.g., `2025-08-29-pyright_watch_report`) should be migrated to `misc/{name}` (e.g., `misc/2025-08-29-pyright_watch_report`).

```
runs/
  train/                           # Split-level (only for atomic runs)
    critic/
      specimen:ducktape/2025-11-26-00/
        TIMESTAMP/
          input.json
          output.json
          events.jsonl

      specimen-file:ducktape/2025-11-26-00/
        TIMESTAMP/
          input.json
          output.json
          events.jsonl

      specimen:misc/2025-08-29-pyright_watch_report/
        TIMESTAMP/
          input.json
          output.json
          events.jsonl

    grader/
      specimen:ducktape/2025-11-26-00/
        TIMESTAMP/
          input.json
          output.json
          events.jsonl
          unknowns/*.yaml

  valid/
    critic/...
    grader/...

  all/                             # Non-split-aware
    critic/...
    grader/...

  evals/                           # Orchestrated sessions (no split nesting)
    full-split:train/
      TIMESTAMP/
        input.json
        output.json

    full-split:valid/
      TIMESTAMP/
        input.json
        output.json

  optimize/
    TIMESTAMP/
      input.json
      output.json
      prompts/
      transcript/
        events.jsonl

  cluster/
    TIMESTAMP/
      input.json
      output.json
      results/
        SPECIMEN/
          clusters.json
```

## Key Design Principles

1. **Input data is the spec**: No artificial split between spec and input - the input contains all information needed to compute paths
2. **Split nesting only for atomic runs**: `runs/{split}/{run_type}/...`
3. **Orchestrated sessions are flat**: `runs/evals/full-split:{split}/...`
4. **Scope ID computed by run class**: Each run type knows how to encode its input into scope_id
5. **Paths are computed properties**: Lazy evaluation, single source of truth
6. **Status is StrEnum**: Type-safe enum for run states
7. **Reference paths relative to `runs/`**: Easy resolution across run types

## Core Types

### RunStatus (StrEnum)

```python
from enum import StrEnum

class RunStatus(StrEnum):
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
```

### Split (StrEnum)

```python
class Split(StrEnum):
    TRAIN = "train"
    VALID = "valid"
    ALL = "all"  # Non-split-aware
```

### RunType (StrEnum)

```python
class RunType(StrEnum):
    CRITIC = "critic"
    GRADER = "grader"
```

## Input/Output Models

### Base Models

```python
class RunInputBase(BaseModel):
    """Minimal base for all run inputs."""
    model_config = ConfigDict(extra="forbid")


class RunOutputBase(BaseModel):
    """Base for all run outputs."""
    started_at: str
    finished_at: str | None = None
    duration_seconds: float | None = None
    cost: float
    input_tokens: int | None = None
    output_tokens: int | None = None
    status: RunStatus  # StrEnum
    error: str | None = None

    model_config = ConfigDict(extra="forbid")
```

### SpecimenSlug Type (New)

```python
# In adgn.props.ids (new addition):

# Specimen slug type with validated pattern enforcing exactly one slash
# Pattern: {project}/{date-sequence}
#   - project: lowercase alphanumeric, underscore, hyphen (e.g., "ducktape", "crush", "misc")
#   - date-sequence: typically YYYY-MM-DD-NN or YYYY-MM-DD-name (e.g., "2025-11-26-00", "2025-08-30-internal_db")
# Constraint: EXACTLY ONE SLASH for consistent directory depth in runs/
#
# Valid examples:
#   - "ducktape/2025-11-26-00"
#   - "crush/2025-08-30-internal_db"
#   - "misc/2025-08-29-pyright_watch_report"
#
# Invalid:
#   - "2025-08-29-pyright_watch_report" (no slash - migrate to misc/)
#   - "a/b/c" (multiple slashes)
#
# Pattern breakdown:
#   ^[a-z0-9_-]+  - project part (1+ chars)
#   /             - exactly one slash separator
#   [a-z0-9_-]+$  - date-sequence part (1+ chars)
#
# ruff: noqa: UP040 - TypeAlias required for mypy compatibility
SpecimenSlug: TypeAlias = Annotated[  # type: ignore[valid-type]
    constr(
        pattern=r"^[a-z0-9_-]+/[a-z0-9_-]+$",
        min_length=3,  # Minimum: "a/b"
        max_length=100,  # Reasonable upper bound
    ),
    _STR_IDENTITY_SERIALIZER,
]


### Scope Types (Reusable)

```python
from adgn.props.splits import get_train_specimens, get_valid_specimens
from adgn.props.ids import SpecimenSlug


def derive_split(specimen: SpecimenSlug) -> Split:
    """Derive split from specimen membership."""
    if specimen in get_train_specimens():
        return Split.TRAIN
    elif specimen in get_valid_specimens():
        return Split.VALID
    else:
        raise ValueError(f"Specimen {specimen} not in train or valid split")


class SpecimenScope(BaseModel):
    """Full-specimen scope."""
    tag: Literal["specimen"] = "specimen"
    specimen: SpecimenSlug  # Validated type: {project}/{YYYY-MM-DD-sequence}

    model_config = ConfigDict(extra="forbid")

    @property
    def split(self) -> Split:
        """Derive split from specimen membership."""
        return derive_split(self.specimen)

    def scope_id(self) -> str:
        """Encode scope for filesystem path.

        Returns path like "specimen:ducktape/2025-11-26-00" with slash preserved.
        All specimens guaranteed to have exactly one slash.
        """
        return f"specimen:{self.specimen}"


class SpecimenFileScope(BaseModel):
    """Single-file scope within a specimen."""
    tag: Literal["file"] = "file"
    specimen: SpecimenSlug  # Validated type
    file_path: str = Field(..., description="Relative path within specimen")

    model_config = ConfigDict(extra="forbid")

    @property
    def split(self) -> Split:
        """Derive split from specimen membership."""
        return derive_split(self.specimen)

    def scope_id(self) -> str:
        """Encode scope for filesystem path.

        Returns path like "specimen-file:ducktape/2025-11-26-00" with slash preserved.
        All specimens guaranteed to have exactly one slash.
        """
        return f"specimen-file:{self.specimen}"


# Union type for scope
Scope = Annotated[SpecimenScope | SpecimenFileScope, Field(discriminator="tag")]
```

### Scoped Input Base

```python
class ScopedInputBase(RunInputBase):
    """Base for inputs with specimen-based scope."""
    scope: SpecimenScope | SpecimenFileScope  # Both variants have specimen + split
```

### Critic Models

```python
class CriticInput(ScopedInputBase):
    """Input for critic runs (supports both scope variants)."""
    scope: Scope  # Can be either SpecimenScope or SpecimenFileScope
    model: str
    system_prompt: str


class CriticIssue(BaseModel):
    """Single issue from critic."""
    id: str
    should_flag: bool
    rationale: str
    occurrence: dict  # FilesToRanges structure

    model_config = ConfigDict(extra="forbid")


class CriticResult(BaseModel):
    """Critic substantive output."""
    issues: list[CriticIssue]

    model_config = ConfigDict(extra="forbid")


class CriticOutput(RunOutputBase):
    """Output for critic runs."""
    result: CriticResult
```

### Grader Models

```python
class GraderInput(ScopedInputBase):
    """Input for grader runs (always full-specimen scope)."""
    scope: SpecimenScope  # Narrows to specimen-only (grader doesn't grade files)
    model: str
    critic_result: CriticResult = Field(description="Issues reported by critic")
    critic_run_ref: str | None = Field(
        default=None,
        description="Relative path from runs/ (for provenance, if available)"
    )

    @classmethod
    def from_critic_output(
        cls,
        critic_output: CriticOutput,
        critic_scope: Scope,
        model: str,
        critic_run_path: str | None = None
    ) -> GraderInput:
        """Create input from critic output, embedding result directly.

        Use when you already have the critic output in memory.
        Optionally provide critic_run_path for provenance tracking.

        Extracts specimen from critic scope (works for both scope variants).
        """
        # Extract specimen from critic's scope
        if isinstance(critic_scope, SpecimenFileScope):
            scope = SpecimenScope(specimen=critic_scope.specimen)
        else:
            scope = critic_scope  # Already SpecimenScope

        return cls(
            scope=scope,
            model=model,
            critic_result=critic_output.result,
            critic_run_ref=critic_run_path
        )

    @classmethod
    def from_critic_run(
        cls,
        critic_run_path: str,
        runs_root: Path,
        model: str
    ) -> GraderInput:
        """Create input by loading critic run from disk.

        Use when you only have the run path (loads input.json + output.json).
        Derives specimen and split from critic's input.
        """
        # Load critic input to get scope
        critic_input = CriticInput.model_validate_json(
            (runs_root / critic_run_path / "input.json").read_text(encoding="utf-8")
        )

        # Load critic output to get result
        critic_output = CriticOutput.model_validate_json(
            (runs_root / critic_run_path / "output.json").read_text(encoding="utf-8")
        )

        return cls.from_critic_output(
            critic_output=critic_output,
            critic_scope=critic_input.scope,
            model=model,
            critic_run_path=critic_run_path
        )


class ReportedIssueRatios(BaseModel):
    """Breakdown of reported issues."""
    tp: float
    fp: float
    unlabeled: float

    model_config = ConfigDict(extra="forbid")


class GraderResult(BaseModel):
    """Grader substantive output."""
    recall: float
    precision: float
    reported_issue_ratios: ReportedIssueRatios
    matched_issues: list[dict]
    unmatched_canonical: list[dict]
    unmatched_reported: list[dict]

    model_config = ConfigDict(extra="forbid")


class GraderOutput(RunOutputBase):
    """Output for grader runs."""
    result: GraderResult
```

## Run Manager API

### AgentRun (Generic Base)

```python
TInput = TypeVar("TInput", bound=RunInputBase)
TOutput = TypeVar("TOutput", bound=RunOutputBase)


class AgentRun(ABC, Generic[TInput, TOutput]):
    """Base run manager. Paths are computed from input data."""

    def __init__(self, input_data: TInput, runs_root: Path, timestamp: str | None = None):
        self.input = input_data
        self.runs_root = runs_root
        self.timestamp = timestamp or datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        self._computed_cost = 0.0  # Tracked during execution

    # ---- Computed properties (from input) ----

    @abstractmethod
    def run_type(self) -> RunType:
        """Return run type (critic or grader)."""
        ...

    @property
    def relative_path(self) -> str:
        """Relative path from runs/ (for references and path construction)."""
        # split and scope_id() both live on the scope object
        return f"{self.input.scope.split}/{self.run_type()}/{self.input.scope.scope_id()}/{self.timestamp}"

    @property
    def root(self) -> Path:
        """Root directory for this run."""
        return self.runs_root / self.relative_path

    @property
    def input_path(self) -> Path:
        return self.root / "input.json"

    @property
    def output_path(self) -> Path:
        return self.root / "output.json"

    @property
    def events_path(self) -> Path:
        return self.root / "events.jsonl"

    # ---- Core operations ----

    def ensure_exists(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def write_input(self) -> None:
        """Write input.json."""
        self.ensure_exists()
        self.input_path.write_text(
            self.input.model_dump_json(indent=2),
            encoding="utf-8"
        )

    def read_output(self) -> TOutput:
        """Read output.json."""
        return self._output_type().model_validate_json(
            self.output_path.read_text(encoding="utf-8")
        )

    def write_output(self, output: TOutput) -> None:
        """Write output.json."""
        self.output_path.write_text(
            output.model_dump_json(indent=2),
            encoding="utf-8"
        )

    # ---- Main execution ----

    async def run(self) -> TOutput:
        """Execute the run. Subclasses implement _execute()."""
        self.write_input()
        self._prepare()

        started_at = datetime.now(UTC)
        try:
            result = await self._execute()
            finished_at = datetime.now(UTC)
            duration = (finished_at - started_at).total_seconds()

            output = self._build_output(
                result=result,
                started_at=started_at.isoformat(),
                finished_at=finished_at.isoformat(),
                duration_seconds=duration,
                status=RunStatus.SUCCESS
            )
        except Exception as e:
            finished_at = datetime.now(UTC)
            duration = (finished_at - started_at).total_seconds()

            output = self._build_output(
                result=None,
                started_at=started_at.isoformat(),
                finished_at=finished_at.isoformat(),
                duration_seconds=duration,
                status=RunStatus.FAILED,
                error=str(e)
            )
            raise
        finally:
            self.write_output(output)
            self._cleanup()

        return output

    # ---- Subclass hooks ----

    @abstractmethod
    def _output_type(self) -> type[TOutput]:
        """Return Output pydantic type."""
        ...

    @abstractmethod
    async def _execute(self) -> Any:
        """Execute the actual work. Return result data."""
        ...

    @abstractmethod
    def _build_output(
        self,
        result: Any,
        started_at: str,
        finished_at: str,
        duration_seconds: float,
        status: RunStatus,
        error: str | None = None
    ) -> TOutput:
        """Build output model from result."""
        ...

    def _prepare(self) -> None:
        """Optional: prepare additional directories/files."""
        pass

    def _cleanup(self) -> None:
        """Optional: cleanup after execution."""
        pass
```

### Concrete Run Types

```python
class CriticRun(AgentRun[CriticInput, CriticOutput]):
    """Critic run manager."""

    def run_type(self) -> RunType:
        return RunType.CRITIC

    def _output_type(self) -> type[CriticOutput]:
        return CriticOutput

    async def _execute(self) -> CriticResult:
        """Run critic agent, return issues."""
        # ... actual critic execution using self.input ...
        # TranscriptHandler writes to self.events_path
        # Track cost in self._computed_cost
        return CriticResult(issues=[...])

    def _build_output(
        self,
        result: CriticResult | None,
        started_at: str,
        finished_at: str,
        duration_seconds: float,
        status: RunStatus,
        error: str | None = None
    ) -> CriticOutput:
        return CriticOutput(
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=duration_seconds,
            cost=self._computed_cost,
            status=status,
            error=error,
            result=result or CriticResult(issues=[])
        )


class GraderRun(AgentRun[GraderInput, GraderOutput]):
    """Grader run manager."""

    def run_type(self) -> RunType:
        return RunType.GRADER

    @property
    def unknowns_dir(self) -> Path:
        return self.root / "unknowns"

    def _output_type(self) -> type[GraderOutput]:
        return GraderOutput

    def _prepare(self) -> None:
        """Create unknowns directory."""
        self.unknowns_dir.mkdir(parents=True, exist_ok=True)

    async def _execute(self) -> GraderResult:
        """Run grader agent, write unknowns, return grade."""
        # Load critic results from self.input.critic_run
        # ... grading logic ...
        # Write unknowns to self.unknowns_dir via write_unknown_yaml()
        # Track cost in self._computed_cost
        return GraderResult(...)

    def _build_output(
        self,
        result: GraderResult | None,
        started_at: str,
        finished_at: str,
        duration_seconds: float,
        status: RunStatus,
        error: str | None = None
    ) -> GraderOutput:
        return GraderOutput(
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=duration_seconds,
            cost=self._computed_cost,
            status=status,
            error=error,
            result=result or GraderResult(
                recall=0.0,
                precision=0.0,
                reported_issue_ratios=ReportedIssueRatios(tp=0, fp=0, unlabeled=0),
                matched_issues=[],
                unmatched_canonical=[],
                unmatched_reported=[]
            )
        )

    def write_unknown_yaml(self, filename: str, content: str) -> None:
        """Helper for writing unknowns during execution."""
        (self.unknowns_dir / filename).write_text(content, encoding="utf-8")

    def list_unknowns(self) -> list[Path]:
        """List all unknown YAML files."""
        return sorted(self.unknowns_dir.glob("*.yaml"))
```

## Usage Examples

### Running a Critic

```python
from adgn.props.runs import CriticInput, CriticRun, SpecimenScope
from adgn.props.prop_utils import pkg_dir

runs_root = pkg_dir() / "runs"

# Create input (split is computed from specimen on scope)
input_data = CriticInput(
    scope=SpecimenScope(specimen="ducktape/2025-11-26-00"),
    model="gpt-5",
    system_prompt="You are a code reviewer..."
)

# Split is computed automatically on the scope
print(input_data.scope.split)  # Split.TRAIN (derived from specimen membership)

# Run
run = CriticRun(input_data, runs_root)
output = await run.run()

# Reference this run from grader
print(run.relative_path)  # "train/critic/specimen:ducktape_2025-11-26-00/20251127_143022"
```

### Running a Grader

```python
from adgn.props.runs import GraderInput, GraderRun

# Option 1: From in-memory critic output with provenance
grader_input = GraderInput.from_critic_output(
    critic_output=output,
    critic_scope=input_data.scope,  # Extracts specimen from critic's scope
    model="gpt-5",
    critic_run_path=run.relative_path  # Optional: preserve provenance
)

# Option 2: From critic run path (loads input.json + output.json, derives everything)
grader_input = GraderInput.from_critic_run(
    critic_run_path="train/critic/specimen:ducktape_2025-11-26-00/20251127_143022",
    runs_root=runs_root,
    model="gpt-5"
)

# Option 3: Programmatic (no run reference)
grader_input = GraderInput.from_critic_output(
    critic_output=programmatic_critic_output,
    critic_scope=SpecimenScope(specimen="ducktape/2025-11-26-00"),
    model="gpt-5"
    # critic_run_path omitted - no provenance
)

# Grader has immediate access to critic issues and computed split
print(f"Grading {len(grader_input.critic_result.issues)} issues")
print(f"Split: {grader_input.scope.split}")  # Computed from scope.specimen
if grader_input.critic_run_ref:
    print(f"From critic run: {grader_input.critic_run_ref}")

grader_run = GraderRun(grader_input, runs_root)
grader_output = await grader_run.run()

# Inspect unknowns
for path in grader_run.list_unknowns():
    print(path)
```

### File-Scoped Critic Run

```python
from adgn.props.runs import CriticInput, CriticRun, SpecimenFileScope

file_input = CriticInput(
    scope=SpecimenFileScope(
        specimen="ducktape/2025-11-26-00",
        file_path="src/adgn/mcp/compositor/server.py"
    ),
    model="gpt-5",
    system_prompt="..."
)

# Split is computed from specimen on scope
print(file_input.scope.split)  # Split.TRAIN

file_run = CriticRun(file_input, runs_root)
output = await file_run.run()

# Path includes file scope marker
print(file_run.relative_path)  # "train/critic/specimen-file:ducktape_2025-11-26-00/20251127_143555"
```

### Reading Existing Runs

```python
# Read input from disk to reconstruct run
input_data = CriticInput.model_validate_json(
    (runs_root / "train/critic/specimen:ducktape_2025-11-26-00/20251127_143022/input.json").read_text()
)

# Split is computed on scope from specimen
print(input_data.scope.split)  # Split.TRAIN
print(input_data.scope.specimen)  # "ducktape/2025-11-26-00"

# Reconstruct run with known timestamp
run = CriticRun(input_data, runs_root, timestamp="20251127_143022")

# Read output
if run.root.exists():
    output = run.read_output()
    print(f"Found {len(output.result.issues)} issues")
```

## Orchestrated Sessions (Separate Design)

Orchestrated sessions (full-split evals, optimizer) will have their own input/run types that:
- Don't nest under `{split}/{run_type}/`
- Store under `runs/evals/` or `runs/optimize/`
- Reference atomic runs via `relative_path`
- Have their own input/output models

Example:

```python
class FullSplitEvalInput(BaseModel):
    split: Split
    specimens: list[str]
    system_prompt: str
    model: str

class FullSplitEvalRun(AgentRun[FullSplitEvalInput, FullSplitEvalOutput]):
    @property
    def root(self) -> Path:
        # Override: no split nesting
        return self.runs_root / "evals" / f"full-split:{self.input.split}" / self.timestamp

    async def _execute(self):
        # Launch multiple CriticRun + GraderRun in parallel
        # Collect references and aggregate metrics
        ...
```

Example paths:
- `runs/evals/full-split:train/TIMESTAMP/`
- `runs/optimize/TIMESTAMP/`

## Migration Notes

### Current → New Structure

1. **Standalone `prompt-eval` runs**: Move from `runs/prompt_eval/TS/SPECIMEN/` to `runs/all/critic/specimen:X/TS/` and `runs/all/grader/specimen:X/TS/`

2. **Prompt-optimizer evals**: Move from `runs/prompt_evals/{train,valid}/eval_TS/SPECIMEN/` to `runs/{train,valid}/{critic,grader}/specimen:X/TS/`

3. **References**: Update all `critic_run` references to use new relative paths

4. **Cluster-unknowns**: Update glob to `runs/{train,valid,all}/grader/specimen*/*/unknowns/*.yaml`

### Migration Helper

```python
def migrate_old_run(old_path: Path, runs_root: Path) -> Path:
    """Migrate old run structure to new structure.

    Old: runs/prompt_eval/TS/SPECIMEN/{critic.json, grade.json, unknowns/}
    New:
      - runs/all/critic/specimen:X/TS/{input.json, output.json}
      - runs/all/grader/specimen:X/TS/{input.json, output.json, unknowns/}
    """
    # ... migration logic ...
```

## Design Rationale

### Why No Separate Spec?

Initially, we had a separate `RunSpec` hierarchy that duplicated information from input models:
- `spec.specimen` vs `input.specimen`
- `spec.split` vs needing to pass split separately

This was artificial - the input data already contains everything needed to:
- Identify the run (specimen, scope, split)
- Execute the run (model, prompts, parameters)
- Compute paths (via run class methods)

By making the run class compute paths from input, we:
- Eliminate duplication
- Have a single source of truth (the input)
- Simplify the API (`CriticRun(input, root)` vs `CriticRun(spec, root)`)
- Make it impossible to have mismatched spec and input

### Why Computed Properties?

Paths are computed on-the-fly from input data instead of being stored:
- Ensures consistency (can't have stale cached paths)
- Makes run objects lightweight (just input + root + timestamp)
- Easy to serialize/deserialize (just save input.json + timestamp)
- Properties are cheap enough for repeated access

## Future Considerations

### Typed Path References

Currently, run references use plain strings (e.g., `critic_run: str`). We could introduce a more specific type:

```python
class RunReference(str):
    """Newtype for run-relative paths (relative to runs/)."""
    pass

class GraderSpecimenInput(SpecimenScopeInput):
    critic_run: RunReference
```

Benefits:
- Type safety: distinguish run references from arbitrary strings
- Static analysis: catch incorrect path usage
- Documentation: self-documenting in function signatures

Trade-offs:
- Additional complexity for marginal benefit
- Plain strings work fine for now
- Can migrate later if needed without breaking serialization (strings are compatible)
