# Prompt Evaluation (PE) System — Design Doc

Status: draft
Owner: mpokorny
Module: adgn_llm
Last updated: 2025-09-13

## Goal

Enable iterative prompt engineering for the critic agent. A top‑level Prompt Engineer (PE) agent proposes candidate system prompts and evaluates them using a single MCP tool that:
- Spins up one critic run per specimen with the candidate system prompt (no property definitions mounted; minimal user prompt only)
- Grades each run with the structured grader (GradeSubmitPayload)
- Returns per‑specimen metrics to the PE agent, and persists artifacts for offline analysis

## Constraints
- MCP tool input: prompt only (no model/specimen params)
- Model is fixed internally (e.g., gpt-5) for both critic and grader
- Always runs exactly one critic+grader job per known specimen (full set from SpecimenRegistry)
- Concurrency is internal (implementation detail), not a user parameter

## In-scope
- New MCP server (prompt_eval) exposing test_prompt(prompt: str, …) → list[metrics]
- Critic runs per specimen using candidate system prompt
- Structured grading using existing grader (GradeSubmitPayload)
- Persisting prompt + metrics per invocation under runs/prompt_eval/<ts>/

Out of scope (initial):
- Non‑LLM grading (pure matching). We can add later if desired.
- Hyperparameter sweeps and Bayesian optimization orchestrators

## High-level flow

1) Outer PE agent calls MCP tool: prompt_eval.test_prompt with a candidate system prompt string (prompt only).
2) For each specimen:
   - Hydrate specimen workspace (SpecimenRegistry)
   - Launch a critic run in MiniCodex with:
     - System prompt = candidate prompt string (provided by caller)
     - Minimal user prompt: “Analyze the mounted code under /workspace only; report issues concisely via submit tool.”
     - Container wiring: mount specimen under /workspace; DO NOT mount property definitions
     - In‑proc critic_submit server; require one submit_result
   - Save resulting CriticSubmitPayload to per‑specimen file
3) Grade:
   - Build grading prompt via build_grade_from_json_prompt with canonical positives (issues/), known false positives (false_positives/), and the critic JSON just produced for that specimen
   - Launch MiniCodex with in‑proc grader_submit; require one submit_result
   - Extract GradeSubmitPayload.metrics
4) Aggregate results across specimens and return to caller; persist all artifacts under a timestamped run directory.

## Interfaces

### MCP tool (server: prompt_eval)
- Name: test_prompt
- Input schema:
  - prompt: str (required) — candidate system prompt for critic
- Output:
  - results: list[GradeMetrics] — one entry per specimen in deterministic order (same order as internal enumeration)

Note: The tool returns only numeric metrics; it does not return file paths, errors, or a summary object.

### Wire-up points
- Critic runner: reuse specimen-check internals but override system prompt and remove properties mount. Minimal user prompt string (no template):
  - “Analyze code under /workspace (read‑only). Use tools to read files as needed. Submit your findings using the submit_result tool. Do not include patches.”
- Grader: reuse build_grade_from_json_prompt + make_grader_submit_server; precision/recall semantics per GradeMetrics (recall = TP / expected; precision = TP / (TP + false_positive + unknown)).

## Data model

- GradeMetrics (existing): expected, reported, true_positives, false_positive, unknown, false_negatives, precision, recall
- CriticSubmitPayload (existing)
- PE result record (new, internal):
  - specimen: str
  - critic: CriticSubmitPayload (file only)
  - grade: GradeSubmitPayload (file only)
  - metrics: GradeMetrics (persisted locally; only metrics list is returned by the tool)

## Filesystem layout

runs/prompt_eval/<ts>_<shortid>/
- prompt.txt — candidate system prompt (verbatim)
- params.json — { specimens: [all], concurrency: <internal>, notes?: str }
- results.json — array of { specimen, metrics } (for offline analysis; not returned via MCP)
- per-specimen/
  - <specimen>/
    - critic.json — CriticSubmitPayload
    - grade.json — GradeSubmitPayload

## Orchestration

- Concurrency with asyncio.Semaphore
- Each specimen job:
  1) Hydrate specimen via SpecimenRegistry.hydrated_copy
  2) Critic run: MiniCodex with in‑proc critic_submit; container wiring: properties_docker_spec(content_root, mount_properties=False)
  3) Grade run: build canonical_list from rec.issues; known_fp_list from rec.false_positives; build_grade_from_json_prompt(…, submit_tool_name); MiniCodex with in‑proc grader_submit
  4) Persist artifacts and return metrics

## Error handling
- Any failing specimen still writes local artifacts (critic/grade JSON, traceback.txt)
- The MCP tool does not return per-specimen errors or paths; it returns only metrics. Implementation may either:
  - omit a failed specimen from the results list, or
  - include a zeroed metrics entry. (Pick one in implementation and document there.)
- Do not abort the entire batch unless all specimens fail.

## Security/sandboxing
- No network in containers (reuse critic image policy)
- Read‑only mounts for critic; grader does not require container access initially (see TODO below)

## Configuration knobs
- model: (default gpt‑5)
- specimens: default all; allow name prefixes; validate via SpecimenRegistry
- concurrency: default 4, cap to CPU count
- timeouts: per run (critic, grader) optional; default none

## Versioning/traceability
- Include prompt hash (e.g., SHA‑256 of prompt string) in results.json and run dir name suffix
- Include versions: adgn_llm git SHA, docker image tag used for critic

## Open questions / TODOs
- TODO: Provide specimen container access for grader (mount workspace) if richer grading or audits are desired.
- Consider pure programmatic grading for speed/determinism (no LLM) — optional path.
- Add per‑specimen weightings (e.g., larger specimens weigh more/less) in macro summary.
- Add stratified metrics (by category/severity) once available.
- Provide a secondary tool to fetch historical results and compare prompt variants.

## Sketch of implementation

- New package: adgn_llm/prompt_eval/
  - server.py — FastMCP server with test_prompt tool
  - runner.py — orchestration helpers (critic_run, grade_run, persist)
- CLI (optional) to run outside MCP: adgn-prompt-eval …

Pseudocode (tool handler):
```python
@dataclass
class JobResult:
    specimen: str
    metrics: GradeMetrics | None

@mcp.tool()
async def test_prompt(prompt: str) -> list[dict]:
    run_dir = make_run_dir(prompt)
    (run_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
    (run_dir / "params.json").write_text(json.dumps({"specimens": "ALL"}, indent=2), encoding="utf-8")

    specimens = list_specimen_names(find_specimens_base())
    sem = asyncio.Semaphore(4)

    async def one(specimen: str) -> JobResult | None:
        async with sem:
            try:
                rec = SpecimenRegistry.load_strict(specimen)
                async with rec.hydrated_copy(gitconfig=None) as content_root:
                    critic = await run_critic_with_system_prompt(content_root, prompt, model_fixed="gpt-5")
                    grade = await run_grader(rec, critic, model_fixed="gpt-5")
                    save_json(run_dir/specimen/"critic.json", critic)
                    save_json(run_dir/specimen/"grade.json", grade)
                    return JobResult(specimen, grade.metrics)
            except Exception:
                save_text(run_dir/specimen/"error.txt", traceback.format_exc())
                return None

    results = [r for r in await asyncio.gather(*(one(s) for s in specimens)) if r is not None]
    # Return only numeric metrics in specimen order
    save_json(run_dir/"results.json", [{"specimen": r.specimen, "metrics": r.metrics.model_dump()} for r in results])
    return [r.metrics.model_dump() for r in results]
```

## Acceptance criteria
- A single MCP call runs critic+grader across N specimens and returns per‑specimen GradeMetrics.
- Artifacts persisted under runs/prompt_eval/<ts> with prompt, params, results, per‑specimen critic.json and grade.json.
- No property definitions mounted for critic runs; grader uses canonical issues/false_positives via registry.
- Error cases captured per specimen; batch continues.

## Links
- Critic server/payload: src/adgn/llm/properties/critic.py
- Grader server/payload: src/adgn/llm/properties/grader.py
- Specimen registry: src/adgn/llm/properties/specimens/registry.py
- Prompt builders: src/adgn/llm/properties/prompts/builder.py
- Inop optimizer (reference): src/adgn/llm/inop/engine/optimizer.py
