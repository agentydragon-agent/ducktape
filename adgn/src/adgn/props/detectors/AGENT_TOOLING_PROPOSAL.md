# AI Code Quality Agent (Tooling + Instructions)

The code-quality pipeline uses layered static/dynamic detectors plus an AI agent to produce structured, anchored, per‑property findings with high recall and precise ranges.

## Acceptance criteria (checklist)
- Detectors produce a unified JSON stream of danger signals with: `property`, `path`, `ranges` (1‑based), `detector`, `confidence`, `snippet`.
- Deterministic coverage exists for: `python/imports-top`, `python/forbid-dynamic-attrs`, `python/pathlike`, `python/pydantic-2`, `markdown/inline-formatting`, broad `except` ordering, and common Ruff families. (Pathlib migration and modern type‑hint idioms are handled by Ruff; no custom detectors.)
- Heuristic coverage exists for: `no-oneoff-vars-and-trivial-wrappers`, `early-bailout`, `minimize-nesting`, `structured-data-over-untyped-mappings`, `no-useless-docs`, `self-describing-names`, `domain-types-and-units/time`.
- Dynamic harnesses exist for unix socket hardening and flag‑propagation when static signals are insufficient.
- The agent consumes detector output, verifies applicability strictly against property wording, corrects mislabels via `PROPERTY_INCORRECTLY_ASSIGNED`/`PROPERTY_SHOULD_BE_ASSIGNED`, and anchors minimal exact ranges.
- Findings are reported via Critic MCP (`upsert_issue`, `add_occurrence(_files)`, `submit(issues=N)`).
- Specimen backtesting integrates with `prompt-eval` and `eval_harness` to measure recall/precision and anchor accuracy.

## Positive examples
Python imports at top (property: `python/imports-top`):
```python
# Violation
def f():
    import json
    return json.loads("{}")

# Compliant
import json

def f():
    return json.loads("{}")
```

PathLike passed directly (property: `python/pathlike`):
```python
# Violation
subprocess.run(["tool", str(Path("/etc/cfg"))])
# Compliant
subprocess.run(["tool", Path("/etc/cfg")])
```

Unix socket hardening (proposed `unix-socket-hardening`), server prepares 0700 dir, binds, and chmods 0600:
```python
sock_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
try:
    sock_path.unlink()
except FileNotFoundError:
    pass
srv.bind(str(sock_path))
os.chmod(sock_path, 0o600)
```

## Negative examples
- LLM‑only pass that lists issues without file/line anchors.
- Property stretching: labeling tuple index brittleness under `no-dead-code` instead of a dedicated “avoid magic tuple indices”.
- Swallowing runtime errors when verifying a dynamic check (must fail loud or catch specific exceptions with logging).

## Tooling map (property → primary detector)
- `type-correctness-and-specificity` → `mypy`/pyright; LLM narrows unions and optionality.
- `structured-data-over-untyped-mappings` → AST/grep for `dict[str, Any]` and friends; agent confirms boundary vs internal.
- `self-describing-names` → primitive‑name regex; agent confirms units/meaning.
- `consistent-naming-and-notation` → repository test layout + filename pattern scan.
- `no-random-renames` → AST pass‑through aliases/import aliasing.
- `no-extra-linebreaks` → formatter + structural diff.
- `no-useless-docs` → doc‑vs‑body heuristic; agent curates.
- `no-oneoff-vars-and-trivial-wrappers` → Ruff `C4`/`SIM` + AST.
- `no-dead-code` → Vulture + Ruff + reachability.
- `early-bailout`, `minimize-nesting` → nested‑guard patterns + LLM.
- `no-useless-tests` → test heuristics + LLM.
- `markdown/inline-formatting` → markdown scanner (`props/props/markdown/inline-formatting.md`).
- `python/imports-top` → AST.
- `python/forbid-dynamic-attrs` → AST/grep.
- `python/walrus` → AST assign‑then‑check.
- `python/pathlike` → AST known PathLike APIs.
- `python/pydantic-2` → AST/grep.
- `python/strenum` → AST enum with string members.
- `python/no-swallowing-errors`, `python/scoped-try-except` → AST/grep; ordering check (broad after specific).
- `python/type-hints`, `python/modern-python-idioms`, `python/pathlib` → Ruff families (UP/PTH).
- `python/pytest-standard-fixtures`, `python/pytest-yield-fixtures` → AST/grep.
- `python/barrel-imports-and-public-api` → AST + agent for API intent.
- `domain-types-and-units/time` → `.total_seconds()`, `time.time()` arithmetic.
- `urls` → string‑built URLs (prefer stdlib `urllib.parse`).
- Proposed: `single-source-of-truth`, `avoid-magic-tuple-indices`, `unix-socket-hardening`, `flag-propagation-fidelity`, `boolean-idioms`.

## Prioritized implementation plan

P0 — Framework and deterministic coverage
- Detectors framework: `src/adgn/props/detectors/` with registry and result schema (`property`, `path`, `ranges`, `detector`, `confidence`, `snippet`).
- CLI: `python -m adgn.props.detectors --root <path> [--out detections.json]` to run detectors and write a JSON report.
- Deterministic detectors: `imports_inside_def` (→ `python/imports-top`), `dynamic_attr_probe` (→ `python/forbid-dynamic-attrs`), `pathlike_str_casts` (→ `python/pathlike`), `pydantic_v1_shims` (→ `python/pydantic-2`), `broad_except_order` + `swallow` (→ `python/no-swallowing-errors`, `python/scoped-try-except`).
- Tests: small fixtures per detector; golden JSON outputs; run under `pytest`.

P1 — Heuristics and quality
- Heuristic detectors: `walrus_suggest`, `ssot_derived_strings`, `magic_tuple_indices`, `self_describing_primitives`, `no_useless_docs`.
- Duplicate and dead‑code signal: integrate `jscpd`/similar for duplication; Vulture thresholds tuned and merged.
- Specimen integration: extend `prompt-eval` to run detector‑only vs canonical issues (precision/recall pre‑LLM) and combined (post‑LLM).
- Reporting polish: severity buckets, confidence calibration, mapping to property IDs in summary tables.

P2 — Dynamic harnesses and proposed properties
- Harnesses: `harnesses/unix_socket.py` (0700/0600, unlink, SO_PEERCRED check when OS supports), `harnesses/flag_propagation.py` (CLI→protocol→server flow verifications).
- Proposed properties: add `props/props/single-source-of-truth.md`, `props/props/avoid-magic-tuple-indices.md`, `props/props/unix-socket-hardening.md`, `props/props/flag-propagation-fidelity.md`, `props/props/boolean-idioms.md` with full frontmatter + acceptance criteria + examples.
- Specimens: add Jsonnet issues demonstrating each proposed property; backtest with `prompt-eval` and `eval_harness`.

P3 — Refinements and UX
- False‑positive suppression catalog (known allowable patterns) configurable per‑repo.
- SARIF export for CI annotations.
- Documentation: short contributor guide for writing new detectors and properties.

## Status: Implemented So Far

Framework and CLI
- Detectors package with registry, models, utils, and standalone CLI (`python -m adgn.props.detectors`).
- Tests organized under `tests/detectors/` with positive/negative fixtures via `importlib.resources`.

Detectors (deterministic/core)
- `imports_inside_def` (python/imports-top) — cycle-aware; includes evidence in message.
- `dynamic_attr_probe` (python/forbid-dynamic-attrs)
- `pathlike_str_casts` (python/pathlike)
- `pydantic_v1_shims` (python/pydantic-2)
- `broad_except_order` (python/scoped-try-except)
- `swallow_errors` (python/no-swallowing-errors)

Detectors (heuristics)
- `walrus_suggest` (python/walrus)
- `magic_tuple_indices` (avoid-magic-tuple-indices)
- `trivial_alias` (no-oneoff-vars-and-trivial-wrappers)
- `import_aliasing` (no-random-renames) with conventional alias allowlist (np, pd, plt, sns, nx, tf, sa, jnp, npr, nn, F, px)
- `flatten_nested_guards` (minimize-nesting)
- `optional_string_simplify` (boolean-idioms, safe-only)

Detectors replaced by Ruff
- Removed custom detectors for: None/boolean literal comparisons and redundant else‑after‑return; these are covered by Ruff families (E711/E712/RET/SIM). The agent runs Ruff directly; no local adapter is needed.

Tests
- Positive and negative fixtures for each detector; multi-file fixtures for import-cycle scenarios.

## LLM‑Assisted Analysis (Optional Layer)

Mechanical detectors/adapters provide high‑recall, structured “danger signals.” When an LLM is available, we can layer targeted analysis on top to raise precision, cover semantics, and propose property‑aligned rationales and anchors. The agent does not edit code here — it reads, reasons, clusters, and reports.

Goals
- Prioritize and de‑duplicate findings across files/modules.
- Validate applicability against property definitions; correct labels.
- Surface semantics/design signals (SSOT, truthfulness, intent) beyond simple AST.
- Propose crisp rationales and corrected anchors per occurrence.

Available tools for the agent (pre‑baked)
- Run static analyzers: Ruff (E/F/SIM/RET/PTH/UP), Vulture, Mypy.
- Read code with line numbers (nl -ba) and grep/rg within the mounted workspace.
- Invoke our custom detectors (via CLI) to get danger‑signals.json.
- Query AST/paths via small helper commands when needed (optional future micro‑tools).

Recommended analysis flows
1) Triage & anchoring from danger‑signals
   - Input: merged detections (Ruff+Vulture+Mypy+custom) grouped by property/file.
   - For each group:
     - Open surrounding code (±N lines), locate the minimal construct manifesting the issue; adjust anchors.
     - Validate applicability strictly by property text; emit PROPERTY_INCORRECTLY_ASSIGNED/SHOULD_BE_ASSIGNED when needed.
     - Produce one‑paragraph rationales referencing acceptance criteria bullets.
   - Output: CriticSubmitPayload with occurrences and rationales.

2) SSOT discovery (principle‑first)
   - Input: artifacts from extractor (string literals, literal sets, choices/enums, URL bases, regexes).
   - LLM clusters semantically similar artifacts across modules/packages (Jaccard + semantic). For each cluster:
     - Decide whether a single source of truth is warranted (neutral evidence: items, locations, drift).
     - Suggest extract location (nearest stable ancestor), name, and derivation strategy.
   - Output: ssot‑candidates findings with ranked clusters and concrete evidence.

3) Truthfulness/intent review (narrow)
   - Examples:
     - Inside‑function imports with “avoid cycle” comments: confirm cycle exists via graph; flag misleading notes (do not auto‑rename).
     - Messages displaying derived lists: confirm they derive from a constant; flag drift.
   - Output: boolean‑idioms/truthfulness‑adjacent findings with precise anchors and rationale.

4) Error‑handling boundary assessment
   - Inspect try/except boundaries:
     - Broad catch placement order (Ruff), swallow/no‑op caught (custom), redundant catch‑then‑reraise (TODO heuristic).
     - Validate boundary justification (logging/context translation) vs. inner helpers.
   - Output: early‑bailout/scoped‑try‑except findings with context.

Prompts and deliverables
- Critic flow: “You are a strict reviewer. Read detector outputs; verify property applicability; adjust anchors; submit issues via tools.”
- Grader backtest: grade the LLM’s critique against canonical specimens; track recall/precision.
- SSOT flow: “Cluster provided artifacts; surface clusters likely needing a single source of truth; include evidence and suggested extraction points.”

What not to do
- No mass edits; agent proposes and anchors evidence only.
- No NL rewriting of properties — suggest gaps (GAP: …) and proposed acceptance criteria where appropriate.

Expected impact
- Raises precision notably for semantic/design categories (SSOT/truthfulness), improves anchor quality across the board, and reduces false positives by relabeling detections strictly by property definitions.

## Next Steps

P1 (continue heuristics)
- SSOT discovery (generic): artifact extraction + clustering of string/literal sets and rule-shaped expressions; neutral evidence-only messages; behind a flag initially.
- Boolean idioms (additional small patterns) where safe.
- Narrow “no-useless-docs” (trivial pass-through docstrings) with strict guards.
- Expand conventional alias allowlist via config hook.

P2 (dynamic harnesses and properties)
- Harnesses: unix socket hardening, flag propagation (already sketched in plan); optional/opt-in.
- Proposed properties: single-source-of-truth, avoid-magic-tuple-indices (formalize), unix-socket-hardening, flag-propagation-fidelity, boolean-idioms (formalized acceptance text).

P3 (integration polish)
- SARIF export for CI annotations; summary tables with counts per property.
- Optional LLM triage hook (TODO): package detector evidence and hand off clusters to the agent for judgment on SSOT/ambiguous cases.

## Leverage Baked‑In Tools (dedupe where possible)

We ship the critic container with Ruff, Vulture, and Pyright/Mypy. When a mature tool already flags a pattern, prefer calling it instead of re‑implementing detection logic. Our plan:

- Ruff (enable families: E,F,SIM,RET,PTH,C4,…)
  - None/boolean literal comparisons → E711/E712 (maps to `boolean-idioms`)
  - No‑else‑return / early‑bailout → flake8‑return / pylint rules surfaced via Ruff (maps to `early-bailout`)
  - Simplify boolean/ternary/return patterns → flake8‑simplify (SIM**; maps to `boolean-idioms`, `no-oneoff-vars-and-trivial-wrappers`)
  - Pathlib migration → PTH** (maps to `python/pathlib`/`python/pathlike`)
  - Comprehension hints → C4** (maps to `no-oneoff-vars-and-trivial-wrappers`)

- Vulture
  - Dead symbols/unused code (maps to `no-dead-code`).

Usage model
- The agent runs Ruff/Vulture/Mypy first, then our custom detectors to cover gaps (cycle‑aware imports, pathlike casts, Pydantic v2 shims, magic tuple indices, trivial aliases, import aliasing, Optional[str] simplification, etc.).
- Preferred sequence (in container):
  1) `ruff check --output-format json /workspace > /tmp/ruff.json`
  2) `mypy --hide-error-context --show-error-codes /workspace > /tmp/mypy.txt` (add `--strict` if appropriate)
  3) `vulture /workspace --min-confidence 60 --sort-by-size > /tmp/vulture.txt`
  4) `adgn-detectors-custom --root /workspace --out /tmp/custom-findings.json`
- Over time, remove custom detectors that fully overlap with Ruff and rely on Ruff findings instead; keep custom ones for cases Ruff doesn’t cover or where we need additional evidence.

## Notes
- Apply properties strictly by definition text (see `props/README.md` and the Markdown style rules under `props/props/markdown/**`).
- Prefer least‑power in detectors and harnesses; let exceptions propagate unless explicitly justified.
- Always cite exact 1‑based line ranges and the minimal relevant construct (include decorators when applicable).

## References
- Properties: `src/adgn/props/props/**`
- Specimens: `src/adgn/props/specimens/**`
- Critic/Grader: `src/adgn/props/critic.py`, `src/adgn/props/grader.py`
- Lint runner and prompts: `src/adgn/props/lint_issue.py`, `src/adgn/props/prompts/*`
