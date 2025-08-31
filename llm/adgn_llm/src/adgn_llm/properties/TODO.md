# TODO

- Severity/requiredness levels and aggregation rubric
- Evaluation LLM (critic/grader) integration and output schema
- Prompt-generation LLM integration flow
- Optional specimen sections: Signals (how discovered) and Lessons (when useful)
- Potential indexing (property ↔ specimen cross-refs) if/when scale requires it
- Policy question: If an ABC's method docstring is repeated verbatim by an implementing subclass method, should this violate no-useless-docs? Lean yes, but leave undecided for now; reasonable people may disagree. Track under properties/no-useless-docs.md
- Windows/locale encodings: keep encoding="utf-8" for read_text/write_text to avoid surprises. TODO: I hate this.
- Target Python version detection/guidance: how agents/graders/reviewers determine target (crawl pyproject.toml/tooling, parse runtime markers, else infer from code/CI); decide where this lives in the framework.
- Forbid useless list(...) around dict views in loops when not mutating the dict during iteration
- Property naming mismatch: 'self-describing names' vs guidance 'use datetime for datetimes'. Decide: either scope the property strictly to naming/units and create a separate 'time APIs and units' property (datetime vs time.monotonic, absolute vs interval), or rename/split. Update specimens and docs accordingly.

- New general property (planned): no-footguns (clear, unambiguous outputs)
  - Kind: behavior
  - Predicate: Outputs must be clear, correct, and unambiguous; when multiple accounting modes exist (e.g., first-match vs all-matches), the chosen mode must be explicitly surfaced in output/docs; avoid misleading displays (e.g., hard-coded extension lists diverging from constants).
  - Acceptance ideas:
    - Chosen accounting mode is stated near the results (or in help/docs)
    - Derived output from single source of truth (e.g., CODE_EXTS) — no drift
    - Avoid confusing throwaway state that obscures meaning; inline when clearer

Example (scrubbed):
```python
# Useless list(...) over dict values
while True:
    for worker in list(self.workers.values()):
        if worker.proc and worker.status == JobStatus.RUNNING:
            if worker.proc.returncode is not None:
                logger.warning(
                    "Worker process died unexpectedly",
                    worker_id=worker.id,
                    return_code=worker.proc.returncode,
                )
                worker.status = JobStatus.FAILED

# Better: iterate directly over the view when not mutating the dict
# for worker in self.workers.values():
```

## Codex property enforcer and analyzer

Observation (to investigate)
- Enforcer added a local import justification in a test that already imports the module at top of file.
  - File: project/ditto/ditto_chat/ditto_chat/tools/tests/test_sandboxed_shell_tool.py
  - Symptom: Inserted a comment asserting “Local import in test to avoid heavy module import … heavy import justified,” but a top-level import for the same module already exists.
  - Action: Re-run against this file with a “find-only” analyzer and ask whether the state is correct; capture the agent’s argument.

