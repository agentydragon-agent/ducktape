# Props Agent Guide (AGENTS.md)

## Scope
- Applies to the entire `src/adgn/props/` subtree: properties, specimens, detectors, runbooks, and CLIs.

## MCP Wiring & Prompt Authoring

### What the agent already sees automatically
  - MiniCodex prepends an MCP “wiring banner” to the system message before sampling (see `src/adgn/agent/agent.py`: `_build_effective_instructions`).
  - The banner is computed from a live MCP snapshot: running server names, their tool names/descriptions, and a short list of resources (URIs) per server.
  - For the Docker exec server, the `container.info` resource includes image tag/ID, image build history (e.g., `pip install ... ruff==…`), mounted volumes (e.g., `/workspace`, `/props`), working directory, and network mode.
  - The banner lists only a few resources per server for readability; the agent can call `resources/list`/`resources/read` to enumerate/read more.

### Implications for runbooks/prompts (do vs don’t)
  - Do:
    - Describe the analysis strategy and sequencing (what to check, in what order, why).
    - Provide concrete command examples (e.g., run Ruff/Mypy/Vulture/custom detectors) and define the required final outputs (inline JSON/markdown with truncation rules).
  - Don’t (redundant due to wiring/banner):
    - Re‑enumerate MCP servers, tool schemas, or resource URIs shown in the banner.
    - Restate tool versions/pins or platform details; the agent can read them from `container.info`.
    - Repeat wiring details like server names, volumes (`/workspace`, `/props`), or cache/temp env; these are implied by the container wiring.
    - Restate long acceptance criteria verbatim; link to property docs or summarize briefly.

## Tooling Specifics (Current Image)
- Ruff: run `ruff check --output-format json /workspace`; set `XDG_CACHE_HOME=/tmp` (or `RUFF_CACHE_DIR=/tmp/.ruff_cache`).
- Mypy (preferred): run the CLI with the repo config if present, e.g., `mypy --config-file pyproject.toml /workspace` (add `--strict` if appropriate).
- Vulture: pinned to `2.14`. You may use the CLI (`vulture /workspace --min-confidence 60 --sort-by-size`) or Python API as needed.
- Custom detectors: `adgn-detectors-custom --root /workspace --out /tmp/custom-findings.json`.
- Duplication hotspots: `jscpd --path /workspace --reporters json` (or restrict via `--languages python`, honor `.gitignore` if applicable).

## Unified Runner (CLI)
- Preferred command: `adgn-properties2 run`
  - Scope (choose one): `--specimen <slug>` or `--path /path/to/code`
  - Prompt source (choose one): `--preset <name>` or `--prompt-file /path/to/runbook.j2.md` or `--prompt-text 'inline'`
  - Mode:
    - Freeform (default): emits plain final text
    - Structured: `--structured true` — attaches `critic_submit` and requires a final `submit(issues=N)`; compatible with graders
  - Always renders prompts via Jinja with standard props context; plain Markdown passes through unchanged.

Examples
- Structured, max‑recall critic on a specimen:
  - `adgn-properties2 run --specimen <slug> --structured true --preset max-recall-critic`
- Dead‑code runbook on a local path (structured):
  - `adgn-properties2 run --preset dead-code-and-reachability --path /repo --structured true`
- Open review with a custom runbook (freeform):
  - `adgn-properties2 run --prompt-file ./my_review.j2.md --path /repo`

Notes

## Wiring Defaults (Container)
- Network disabled; workspace mounted read‑only at `/workspace`.
- Caches/temp redirected to `/tmp` and Python pycache relocated to `/tmp/__pycache__`.
- Tool versions/pins are visible via the Docker `container.info` resource (image history shows the build lines). Don’t restate versions in runbooks; the agent can read them when needed.

## Docker Build
- Properties critic image lives under `docker/llm/properties-critic/Dockerfile`.
  - Build locally: `docker build -f docker/llm/properties-critic/Dockerfile -t adgn-llm/properties-critic:latest .`

## Findings Organization (Specimens)
- Follow repo markdown conventions when authoring specimen docs.
- Split findings into:
  - `covered.md`: only those that map to an existing, formal property under `props/definitions/**`.
  - `not_covered_yet.md`: anything that doesn’t map cleanly to an existing definition (or is only tangentially related).
