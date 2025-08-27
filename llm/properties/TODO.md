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
