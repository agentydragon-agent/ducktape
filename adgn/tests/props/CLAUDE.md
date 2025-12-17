# Testing Guide for Props Tests

## Core Principle

**Git fixtures are the single source of truth for ALL test data.**

Never create synthetic ORM models (Snapshot, TruePositive, FalsePositive, Example) directly in tests. Use the git-tracked test fixtures in `tests/props/fixtures/specimens/` and the `synced_test_fixtures` pytest fixture.

## Available Git Fixtures

Located in `tests/props/fixtures/specimens/`:

- **test-fixtures/test-trivial** (TRAIN split)
  - Files: add.py, subtract.py, multiply.py, divide.py
  - Issues: 4 TPs (test-issue.libsonnet through test-issue-4.libsonnet)
  - Use for: Multi-file tests, duplication detection, RLS train split

- **test-fixtures/test-validation** (VALID split)
  - Files: subtract.py
  - Issues: 1 TP (test-issue.libsonnet)
  - Use for: RLS valid split, warm-start validation

- **test-fixtures/test-validation-2** (VALID split)
  - Files: calculator.py
  - Issues: 1 TP (validation-issue.libsonnet)
  - Use for: Warm-start with multiple validation examples

- **test-fixtures/test-split-test** (TEST split)
  - Files: example_module.py
  - Issues: 1 TP (test-split-issue.libsonnet)
  - Use for: RLS test split verification

## Using Git Fixtures in Tests

### Step 1: Depend on synced_test_fixtures

```python
def test_my_feature(synced_test_fixtures: DatabaseConfig):
    """My test that needs fixture data."""
    # synced_test_fixtures automatically:
    # 1. Creates isolated test database
    # 2. Overrides ADGN_PROPS_SPECIMENS_ROOT to tests/props/fixtures/specimens/
    # 3. Runs sync_all() to populate database
    # 4. Returns test_db config for any additional setup
```

### Step 2: Query Examples from Database

```python
from adgn.props.db import get_session
from adgn.props.db.examples import Example

def test_critic_on_train_example(synced_test_fixtures: DatabaseConfig, test_prompt_sha: str):
    """Test critic on training data."""
    with get_session() as session:
        # Query the example you need
        example = session.query(Example).filter_by(
            snapshot_slug="test-fixtures/test-trivial"
        ).first()

        # Use factory with required example parameter
        critic_run = make_critic_run(example=example, prompt_sha256=test_prompt_sha)
        session.add(critic_run)
        session.commit()
```

### Step 3: Use Scope Fixtures (Optional)

If you need to query specific scopes:

```python
def test_single_file_scope(
    synced_test_fixtures: DatabaseConfig,
    add_py_scope: ExplicitFileScope,
    test_prompt_sha: str,
):
    """Test with single-file scope."""
    with get_session() as session:
        # Find example matching scope
        example = session.query(Example).filter_by(
            snapshot_slug="test-fixtures/test-trivial",
            scope_hash=add_py_scope.compute_hash(),
        ).one()

        critic_run = make_critic_run(
            example=example,
            prompt_sha256=test_prompt_sha,
        )
```

## Available Fixtures (conftest.py)

### Canonical Prompts

- `CANONICAL_CRITIC_PROMPT`: String constant with realistic critic prompt
- `test_prompt_sha`: Fixture returning SHA256 hash (auto-upserted)
- `test_prompt_sha`: Minimal test prompt (legacy, use canonical for realistic tests)

### Scope Fixtures

- `subtract_file_scope`: ExplicitFileScope(files=["subtract.py"])
- `add_py_scope`: ExplicitFileScope(files=["add.py"])
- `multiply_py_scope`: ExplicitFileScope(files=["multiply.py"])
- `divide_py_scope`: ExplicitFileScope(files=["divide.py"])
- `example_module_py_scope`: ExplicitFileScope(files=["example_module.py"])
- `calculator_py_scope`: ExplicitFileScope(files=["calculator.py"])
- `all_files_scope`: AllFilesScope()

### Factory Functions

**make_critic_run()** - Build CriticRun from Example

```python
def make_critic_run(
    *,  # Keyword-only arguments
    example: Example,  # REQUIRED
    prompt_sha256: str,  # REQUIRED
    model: str = "test-model",
    output: DBCriticOutput | None = None,
    status: CriticRunStatus = CriticRunStatus.COMPLETED,
    completion_summary: str | None = None,
    transcript_id: UUID | None = None,
) -> CriticRun:
```

**Key points**:
- `example` parameter is REQUIRED (not optional)
- `prompt_sha256` is REQUIRED
- Automatically derives `snapshot_slug` and `scope_hash` from example
- Returns ORM model (not yet added to session)

**make_grader_run()** - Build GraderRun from CriticRun

```python
def make_grader_run(
    critic_run_id: UUID,
    snapshot_slug: SnapshotSlug,
    canonical_issues_snapshot,
    model: str = "test-model",
    output: DBGraderOutput | None = None,
    transcript_id: UUID | None = None,
) -> GraderRun:
```

### Helper Fixtures

- `test_train_example_with_runs`: Returns (Example, CriticRun, GraderRun) tuple for train split with 80% recall
- `test_valid_example_with_runs`: Returns (Example, CriticRun, GraderRun) tuple for valid split with 60% recall
- `test_trivial_snapshot`: Returns Snapshot ORM for test-trivial fixture
- `test_validation_snapshot`: Returns Snapshot ORM for test-validation fixture

## Example Patterns

### Pattern 1: Test Critic Behavior

```python
def test_critic_finds_dead_code(
    synced_test_fixtures: DatabaseConfig,
    test_prompt_sha: str,
):
    """Critic should detect dead code in test fixtures."""
    with get_session() as session:
        example = session.query(Example).filter_by(
            snapshot_slug="test-fixtures/test-trivial"
        ).first()

        critic_run = make_critic_run(
            example=example,
            prompt_sha256=test_prompt_sha,
        )
        session.add(critic_run)
        session.commit()

        # Load issues from normalized tables directly via ORM relationship
        session.refresh(critic_run)
        assert len(critic_run.reported_issues) > 0
```

### Pattern 2: Test Grader Metrics

```python
def test_grader_computes_recall(
    synced_test_fixtures: DatabaseConfig,
    test_prompt_sha: str,
):
    """Grader should compute recall correctly."""
    with get_session() as session:
        example = session.query(Example).filter_by(
            snapshot_slug="test-fixtures/test-trivial"
        ).first()

        # Create critic run with known output
        critic_run = make_critic_run(
            example=example,
            prompt_sha256=test_prompt_sha,
            output=make_critic_success(issues=[...]),
        )
        session.add(critic_run)
        session.flush()

        # Create grader run
        grader_run = make_grader_run(
            critic_run_id=critic_run.id,
            snapshot_slug=example.snapshot_slug,
            canonical_issues_snapshot=EMPTY_CANONICAL_ISSUES_SNAPSHOT,
        )
        session.add(grader_run)
        session.commit()

        # Assert on grader metrics
        assert grader_run.output.tag == "success"
```

### Pattern 3: Test ORM Relationships

```python
def test_example_critic_runs_relationship(synced_test_fixtures: DatabaseConfig, test_prompt_sha: str):
    """Example.critic_runs relationship should work bidirectionally."""
    with get_session() as session:
        example = session.query(Example).filter_by(
            snapshot_slug="test-fixtures/test-trivial"
        ).first()

        # Create two critic runs for same example
        run1 = make_critic_run(example=example, prompt_sha256=test_prompt_sha)
        run2 = make_critic_run(example=example, prompt_sha256=test_prompt_sha)
        session.add_all([run1, run2])
        session.commit()

        # Refresh to load relationship
        session.refresh(example)

        # Assert bidirectional relationship works
        assert len(example.critic_runs) == 2
        assert run1.example_obj == example
        assert run2.example_obj == example
```

## Anti-Patterns (DO NOT DO)

### ❌ Creating Synthetic Snapshots

```python
# WRONG - Don't do this
def test_bad_example(test_db):
    with get_session() as session:
        snapshot = Snapshot(
            slug="synthetic/test",
            split=Split.TRAIN,
            source=LocalSource(vcs="local", root="."),
        )
        session.add(snapshot)
```

**Why wrong**: Creates data not tracked in git. Use `synced_test_fixtures` instead.

### ❌ Creating Synthetic TPs/FPs

```python
# WRONG - Don't do this
def test_bad_grading(test_db):
    with get_session() as session:
        tp = TruePositive(
            snapshot_slug="test/spec",
            tp_id="synthetic-tp",
            rationale="Test issue",
            occurrences=[...],
        )
        session.add(tp)
```

**Why wrong**: Ground truth should come from git fixtures. Modify issue files instead.

### ❌ Creating Synthetic Examples

```python
# WRONG - Don't do this
def test_bad_example_creation(test_db):
    with get_session() as session:
        example = Example.from_explicit_files("test/spec", ["foo.py"])
        session.add(example)
```

**Why wrong**: Examples are auto-generated by sync_all(). Query them instead.

### ❌ Manual ORM Construction

```python
# WRONG - Don't do this
def test_bad_critic_run(test_db):
    critic_run = CriticRun(
        transcript_id=uuid4(),
        snapshot_slug="test/spec",
        scope_hash="abc123",
        model="test-model",
        prompt_sha256="def456",
        output=make_critic_success(),
    )
```

**Why wrong**: Use `make_critic_run(example=..., prompt_sha256=...)` factory instead.

### ❌ Ad-hoc Prompt Strings

```python
# WRONG - Don't do this
def test_bad_prompts(synced_test_fixtures, test_db):
    prompt_sha = hash_and_upsert_prompt("review this code")
    another_sha = hash_and_upsert_prompt("find bugs here")
    # ... 14 more ad-hoc prompts
```

**Why wrong**: Use `test_prompt_sha` or `test_prompt_sha` fixtures.

### ❌ Inline Scope Construction

```python
# WRONG - Don't do this
def test_bad_scope_usage(synced_test_fixtures):
    scope1 = ExplicitFileScope(files=["test.py"])
    scope2 = ExplicitFileScope(files=["test.py"])  # Duplicate
    scope3 = AllFilesScope()
```

**Why wrong**: Use scope fixtures (`add_py_scope`, `all_files_scope`, etc.) for reusability.

## RLS Testing Pattern

For tests that verify row-level security policies across splits:

```python
@pytest.mark.asyncio
async def test_rls_train_valid_test_isolation(synced_test_fixtures):
    """Test that RLS properly isolates TRAIN/VALID/TEST splits."""
    # Use all three split fixtures
    with get_session() as session:
        train_snapshots = session.query(Snapshot).filter_by(split=Split.TRAIN).all()
        valid_snapshots = session.query(Snapshot).filter_by(split=Split.VALID).all()
        test_snapshots = session.query(Snapshot).filter_by(split=Split.TEST).all()

        assert len(train_snapshots) == 1  # test-trivial
        assert len(valid_snapshots) == 2  # test-validation, test-validation-2
        assert len(test_snapshots) == 1   # test-split-test
```

## Warm-Start Testing Pattern

For tests that need multiple validation examples:

```python
def test_warm_start_with_multiple_valid_snapshots(synced_test_fixtures):
    """Warm-start should handle multiple validation snapshots."""
    valset = [
        Example.from_scope("test-fixtures/test-validation", ExplicitFileScope(files=["subtract.py"])),
        Example.from_scope("test-fixtures/test-validation-2", ExplicitFileScope(files=["calculator.py"])),
    ]

    state = build_historical_gepa_state(
        valset=valset,
        critic_model="test-model",
        grader_model="test-model",
    )

    assert state is not None
    # Assert on warm-start state structure
```

## Migration Checklist

When migrating existing tests to use git fixtures:

1. ✅ Replace `make_test_snapshot()` calls with `synced_test_fixtures` + queries
2. ✅ Replace `make_true_positive()` calls with git issue files
3. ✅ Replace `make_example()` calls with queries (Examples auto-created)
4. ✅ Update `make_critic_run()` calls to include required `example` parameter
5. ✅ Replace inline scopes with scope fixtures
6. ✅ Replace ad-hoc prompts with `test_prompt_sha`
7. ✅ Verify test still passes with `pytest tests/props/path/to/test.py::test_name`

## Success Metrics

A well-written test should:
- ✅ Use `synced_test_fixtures` for data (no synthetic ORM models)
- ✅ Use factory functions (`make_critic_run`, `make_grader_run`)
- ✅ Use scope fixtures (80%+ usage target)
- ✅ Use canonical prompts (not ad-hoc strings)
- ✅ Be concise (<50 lines per test, <100 for complex scenarios)
- ✅ Query examples rather than creating them
- ✅ Test behavior, not implementation details
