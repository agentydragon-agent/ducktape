# Detectors test fixtures

This directory contains fixtures and tests for the standalone detectors under
`src/adgn/props/detectors`.

Philosophy
- Single parametric test (tests/detectors/test_detectors.py) covers both:
  - Bad fixtures (must-fire): minimal samples that MUST trigger a given detector
    with at least one detection for the expected property.
  - Ok fixtures (no-findings): minimal samples that MUST NOT trigger the given
    detector. These are “compliant for this specific detector” only, not global
    endorsements.

Structure
- Fixtures live under `tests/detectors/fixtures/bad/` and
  `tests/detectors/fixtures/ok/` and are copied into a temporary repo for each
  test case.

Future structure (optional)
- If we grow many detectors, we can also split by heuristic strength, e.g.:
  `tests/detectors/fixtures/{positive,negative}/{heuristic,deterministic}/...`.

Running
- `pytest tests/detectors -q`

Notes
- Fixtures intentionally avoid other smells unrelated to the target detector.
  When a smell would distract (e.g., unnecessary casts or redundant patterns),
  we adjust the fixture to keep the test’s intent narrow and clear.
