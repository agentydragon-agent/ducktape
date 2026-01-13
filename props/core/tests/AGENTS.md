# Testing Guide for Props Tests

## Core Principle

**Git fixtures are the single source of truth for ALL test data.**

Never create synthetic ORM models (Snapshot, TruePositive, FalsePositive, Example) directly in
tests. Use the git-tracked test fixtures in `tests/fixtures/specimens/` and the `synced_test_db`
pytest fixture.

## Available Git Fixtures

Located in `fixtures/specimens/`:

- **test-fixtures/train1** (TRAIN split)
  - Files: add.py, subtract.py, multiply.py, divide.py
  - Issues: 4 TPs (tp1.yaml through tp4.yaml), 1 FP (fp1.yaml)
  - Use for: Multi-file tests, duplication detection, RLS train split

- **test-fixtures/valid1** (VALID split)
  - Files: subtract.py
  - Issues: 1 TP (tp1.yaml)
  - Use for: RLS valid split, warm-start validation

- **test-fixtures/valid2** (VALID split)
  - Files: calculator.py
  - Issues: 1 TP (tp1.yaml)
  - Use for: Warm-start with multiple validation examples

- **test-fixtures/test1** (TEST split)
  - Files: example_module.py
  - Issues: 1 TP (tp1.yaml)
  - Use for: RLS test split verification

## Using Git Fixtures in Tests (short form)

- Always depend on `synced_test_db` to seed the DB from git fixtures.
- Query examples/TPs/FPs from the DB, never fabricate IDs.
- Use shared factories from `tests/props/conftest.py` (`make_critic_run`, `make_grader_run`, etc.).
- Scope fixtures: `add_py_scope`, `subtract_file_scope`, `multiply_py_scope`, `divide_py_scope`, `all_files_scope`.

## High-value fixtures (conftest.py)

- Scopes: `subtract_file_scope`, `add_py_scope`, `multiply_py_scope`, `divide_py_scope`,
  `example_module_py_scope`, `calculator_py_scope`, `all_files_scope`.
- Examples: `example_subtract_orm` (1 TP occurrence), `example_multi_tp_orm` (multi-TP), `test_trivial_snapshot`, `test_validation_snapshot`.
- IDs: `tp_single_id`, `tp_single_occurrence_id`, `tp_occurrences_multi`, `fp_id`, `fp_occurrence_id`.
- Helpers: `make_critic_run`, `make_grader_run`, `make_grader_run_with_credit`, `test_train_example_with_runs`, `test_valid_example_with_runs`.

## Anti-patterns (do not)

- Fabricate snapshots/examples/TPs/FPs in tests—query from the synced DB instead.
- Hardcode IDs like `tp-001`, `occ-001`, `fp-001`; use the fixtures above.
- Build scopes inline; reuse scope fixtures to avoid drift.

## Fixture guidance

- If coverage is missing, extend the git fixtures rather than fabricating data in tests.
- Prefer the single-field ID fixtures for clarity; tuple fixtures stay for iteration only.
