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

- New general property (planned): right-sized tools (don’t use bigger guns than you need)
  - Kind: behavior
  - Predicate: Prefer the simplest construct that meets the requirement; avoid heavier mechanisms when a direct, simpler reference works (e.g., pass callables/constants instead of string→getattr→dict lookups; use library calls over subprocess when available; choose sync vs async and blocking vs non-blocking appropriately; pass Path directly instead of str conversions).
  - Acceptance ideas:
    - No string→symbol indirection when a direct symbol can be passed
    - No classes-as-namespaces for constants; in Python 'class' implies instances; prefer modules/enums/simple names (use a class only when you intend to instantiate)
    - Prefer direct library APIs over shelling out (unless required by constraints)

- New general property (planned): prefer comprehensions for simple filter/map
  - Kind: outcome
  - Predicate: For simple, readable cases, prefer list/set/dict comprehensions (and generator expressions) over loops that only append/continue or build trivial maps.
  - Acceptance ideas:
    - Single-predicate filters and simple key/value mapping use comprehensions
    - No multi-branch loop when a single comprehension with a concise predicate fits on one readable line
    - Fall back to loops when readability would suffer (long, nested conditions)
    - Keep pre-checks (e.g., early returns) outside the comprehension for clarity

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

## Systematic dead code / reachability analysis (Python-first)

Have critic/fix agents run a repeatable, systematic dead-code and reachability sweep on specimens and repos (Python-first), combining automated/static tools with manual verification.

**Why:** We repeatedly discover unreachable/unused code and test-only prod paths.
This should make sure critics will surface all such findings systematically.

We should probably install vulture, ruff, rg, fd etc. in container for fixer agent.

Workflow
1) Automated discovery (run all):
- Pyright (LSP) JSON diagnostics for unused/unreachable
- Vulture for dead symbols; allow whitelist for FPs
- Ruff selectors (unused imports/assignments); optionally flake8-eradicate for commented-out code
- Semgrep rules: broad except+pass, duplicate guards, unreachable defaults
- ripgrep heuristics: symbol reference counts (exclude definitions/tests as needed)

2) Call graph and refs:
- Build import graph via AST; enumerate exports
- For each symbol, compute references (AST + rg backup)
- Cross-check tool outputs to lower FP rate

3) Manual confirmation:
- Inspect invariants/types/contracts; mark obviously unreachable
- If only test-only usage remains, move under tests/ or consolidate on prod path

4) Fix (optional):
- Delete confirmed dead code (or move to tests) in small PRs
- Replace speculative fallbacks with hard guards (assert/TypeError)

5) Reporting:
- Summarize dead code with proof (tools + rg hits)

Seed examples: from confirmed dead code findings in specimen

## Equip critics/fixers with Python quality tooling (linters/dup detectors/etc.)

Goal: give agents an opinionated toolbox they can run automatically in “check” mode and selectively in “fix” mode.

Checklist (install/enable in agent image + repo):
- [ ] Ruff (check+format). Enable rule families: ANN, A, B, C4, I, NPY, PERF, PTH, PT, RET, RSE, SIM, TRY, ERA, W505, RUF. Add pyproject.toml with per-rule ignores as needed.
- [ ] mypy (or pyright). Start permissive, move toward --strict; type: python version pin and plugin config.
- [ ] vulture (dead code) with allowlist file for intentional symbols.
- [ ] deptry (deps hygiene: unused/undeclared/missing).
- [ ] Bandit (security) and pip-audit (or safety) for dependency vulns.
- [ ] codespell (typos) for code/docs.
- [ ] pyupgrade (syntax modernization; pin e.g. --py312-plus).
- [ ] refurb (refactor suggestions) and flynt (f-strings).
- [ ] pydocstyle (or Ruff D rules) and interrogate (docstring coverage) where useful.
- [ ] import-linter (layer boundaries/contracts) for architecture rules.
- [ ] Semgrep (property-specific checks + autofix where safe).
- [ ] radon + xenon (complexity + CI gates).
- [ ] Pylint duplicate-code (R0801) configured (e.g., --min-similarity-lines=20).
- [ ] jscpd (language-agnostic clone detector) with HTML report artifact.
- [ ] Lizard (complexity + duplicate detection) as a second opinion.
- [ ] Clone Digger (optional, Python-focused clone finding) for stubborn cases.
- [ ] coverage.py + diff-cover (changed-line coverage gates for PRs).

Critic run profiles (how agents use them):
- [ ] “Analyze” profile: ruff check, mypy/pyright, vulture, deptry, bandit, jscpd, pylint R0801, radon (report-only), semgrep; summarize top findings + file:line anchors.
- [ ] “Fix-suggest” profile: ruff --fix, pyupgrade --py312-plus -r ., refurb ., flynt ., codespell (interactive), plus autofixes from selected Semgrep rules; stage diffs for review rather than committing.
- [ ] Duplicate detection config: pylint --enable=duplicate-code --min-similarity-lines=20; jscpd --languages python --reporters console,html --gitignore; lizard -l python -C 15 -d.
- [ ] Output normalization: emit short bullets + anchors; attach HTML artifacts (jscpd, radon) when under CI.

Acceptance criteria:
- [ ] Tools are installed in agent runtime and callable via simple wrappers (e.g., adgn-tools run <profile>).
- [ ] Verify each detected tool runs inside the read-only critic sandbox; track pass/fail per tool and version.
- [ ] Critics include tool-backed evidence in findings; fixers propose safe autofixes first, with diffs.

## TODO: Heuristic flag — redundant catch-and-reraise (agent consideration)

Pattern
- Try/except that immediately re-raises the same exception without adding context, logging, or translation is often unnecessary and can be removed for clarity.

Example

```
try:
    docker_client.cleanup()
except docker.errors.APIError:
    # Cleanup failure: surface as API error
    raise
```

Agent guidance
- Flag such blocks as “consider removing the try/except and allow the exception to propagate.”
- Exceptions (allowed):
  - Adding structured logging/metrics or context
  - Translating exception types (domain-specific)
  - Narrow scoping to preserve invariants (e.g., guarantee finally semantics when language constructs don’t suffice)
- Evidence to include in message: exception type(s), whether body is empty/pass/`raise` only, and whether any useful context/logging is present.

Notes
- Detector can be purely structural: `ast.Try` where each handler body is a bare `raise` (no message/logging) and except types are specific.
- Leave nuanced “is this context useful?” judgment to the agent.

## Codex property enforcer and analyzer

Observation (to investigate)
- Enforcer added a local import justification in a test that already imports the module at top of file.
  - File: project/ditto/ditto_chat/ditto_chat/tools/tests/test_sandboxed_shell_tool.py
  - Symptom: Inserted a comment asserting “Local import in test to avoid heavy module import … heavy import justified,” but a top-level import for the same module already exists.
  - Action: Re-run against this file with a “find-only” analyzer and ask whether the state is correct; capture the agent’s argument.

## Detector ideas (small TODOs)

- Choices vs Arms (CLI/Enum drift)
  - Extract source sets from argparse/Typer choices and Enums; compare against match/case arms, if/elif chains, and dispatch maps.
  - Flag unreachable arms (not in source set), missing arms (values unhandled), and redundant defaults when exhaustive.
  - Anchors: choices/Enum def and arm lines; message includes short proof.

- Union/Instance Exhaustiveness
  - For annotated `Union[T1|T2|…]` params or `isinstance(x, (T1, T2))` chains, ensure all types are handled and no dead arm remains.
  - Optionally scan call sites to prove reachability for each type (evidence: callers constructing/passing Ti).

- Assignment‑If Consolidation
  - Detect patterns where a variable is assigned, then conditionally reassigned in a single if/else, and suggest a conditional expression (`v = A if cond else B`) when readable.

- Optional[str] extensions
  - Beyond `x is None or x == ""`, include `x is None or not x.strip()` (safe-only when confidently Optional[str]).

- Nested Guard Flattening (extended)
  - Support simple boolean algebra (A and B) with parentheses to flatten trivial nested guards while skipping complex cases.

- Registry / Plugin Reachability
  - Index dynamic registries (entrypoint maps, plugin hooks); mark symbols as reachable via registry to reduce Vulture false positives and surface dead registrations.

## CLI consolidation TODOs

- Unify specimen-discover into the `run` command
  - Add `--embed-specimen-notes` to `run` (specimen mode) to auto-embed `covered.md` and `not_covered_yet.md` as supplemental context.
  - For structured runs, keep the critic_submit gating; for `--dry-run`, render with minimal wiring and save the prompt like other presets.
  - Remove the `specimen-discover` command after migration; update docs to use:
    - `adgn-properties2 run --specimen <slug> --preset discover --structured true --embed-specimen-notes`
  - Tests: port any `specimen-discover` dry-run tests to run with `--preset discover --dry-run --embed-specimen-notes`.
