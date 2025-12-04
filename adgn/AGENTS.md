# AGENTS.md — Agent Guide for `adgn`

This file helps AI agents work on the `adgn` package: environment setup, common commands, testing, module map, LLM tooling (MiniCodex), MCP/approvals, and conventions.
See `README.md` for a shorter overview.

## Environment and Setup (direnv + devenv)
- Requirements: Nix + devenv, direnv, Python 3.11+. Node 20 is available in the dev shell for the UI.
- First time here:
  - `cd adgn`
  - `direnv allow`
  - This loads `.envrc` → devenv, creates a Python venv, and installs `adgn` in editable mode with dev extras.
- Re-entering later: just `cd adgn`; direnv activates the environment.
- Verify environment:
  - `direnv status` shows if `.envrc` is loaded
  - `echo "$VIRTUAL_ENV"` contains `.../adgn/.devenv/state/venv`
  - `which python` resolves to `.../adgn/.devenv/state/venv/bin/python`
- Running commands:
  - Inside `adgn/`, tools are on PATH (pytest, ruff, pre-commit, wt, rspcache, adgn-mini-codex, ...)
  - From outside: prefix with `direnv exec adgn <command>`
- Refresh after edits:
  - `devenv.nix`/`.envrc` changes → `direnv reload`
  - `pyproject.toml` dependency changes → `direnv reload` (reinstalls dev extras on entry)

### Devenv Helper Scripts
- `ui-dev` → run Vite dev server for MiniCodex UI (`http://127.0.0.1:5173`)
- `ui-build` → build UI assets into `src/adgn/agent/server/static/web`
- `mini-codex-serve` → start MiniCodex backend server (`http://127.0.0.1:8765`)
- Background: `devenv up` starts the Vite dev server in the background

## Common Dev Commands
- Tests (under `tests/`):
  - Inside `adgn/`: `pytest tests`
  - From repo root: `direnv exec adgn pytest adgn/tests`
- Single test: `direnv exec tana pytest tests/tana/test_convert.py::test_node_export`
- Lint/format: `ruff format .`, `ruff check . --fix`
- Type check: `mypy --config-file pyproject.toml`
- Pre-commit: `pre-commit install`, `pre-commit run -a`
- Optional extras (GNOME console script deps): `python -m pip install -e '.[gnome]'`

## Pytest Defaults (pyproject.toml)
- `timeout = 30`, `timeout_method = thread` (pytest-timeout)
- `asyncio_mode = auto` (pytest-asyncio)
- `testpaths = ["tests"]`
- `addopts` (applied automatically): `-n=16 -m 'not live_llm' -v --tb=short --strict-markers --disable-warnings --durations=25`
- Markers: `slow`, `integration`, `unit`, `shell`, `asyncio`, `real_github`, `live_llm`, `macos`, `requires_docker`, `requires_sandbox_exec`
- Hermetic git (pytest-env): `GIT_CONFIG_NOSYSTEM=1`, `GIT_CONFIG_GLOBAL=/dev/null`

### UI E2E Tests (Playwright)
- Install browsers once: `python -m playwright install`
- Run: `pytest -q tests/agent/e2e -m "not live_llm"`

## High‑Level Module Map
- Packaging: name `adgn`, Python `>=3.11,<3.14`, src layout under `src/`
- Tana export tooling now lives in the sibling `tana/` project (`src/tana/export/`).
  - Key entry points: `convert.py`, `materialize_searches.py`, `export_node_subset.py`, plus helpers under `tana/export/lib/*`.
- Response cache (`src/adgn/rspcache/`)
  - `responses_db.py`; CLI `rspcache`
- LLM toolkit and agent (`src/adgn/llm/*`, `src/adgn/agent/*`, `src/adgn/mcp/*`, `src/adgn/props/*`)
  - MiniCodex UI/server, MCP utilities, instruction optimizer, properties/specimens

## MiniCodex (CLI + Local UI)
- Commands:
  - REPL: `adgn-mini-codex run`
  - UI server: `adgn-mini-codex serve` (opens WS UI at `http://127.0.0.1:8765/`)
  - Dev: `adgn-mini-codex dev` (backend + Vite HMR; auto-picks free ports)
- Model/system defaults: `--model` (OPENAI_MODEL, default `o4-mini`), `--system` (SYSTEM_INSTRUCTIONS)
- MCP configuration:
  - Baseline: if present, `./.mcp.json` in CWD is loaded first
  - Repeatable: `--mcp-config /path/extra.json` merges additional configs (later overrides earlier)
  - Embedded servers: prefer Streamable HTTP (`transport: "http"`) with bearer `auth` or `headers.Authorization`.
  - Compatibility: `transport: "inproc"` with `factory` is still accepted, but is implemented by embedding the server over loopback HTTP with bearer auth (no in‑memory transport).
  - Example: `src/adgn/agent/example.mcp.json`
- Runtime behavior:
  - On connect, server emits `accepted` then a `Snapshot` (MCP servers + current transcript)
  - Approvals: protocol‑native `approval_pending → approval_decision (approve | deny_continue | deny_abort)`
  - Serve/dev build agent and MCP on the uvicorn loop via `app.state.agent_factory` to avoid cross‑loop deadlocks


### UI Development and Builds
- Dev (recommended): `adgn-mini-codex dev` — starts FastAPI + Vite, with proxying for `/ws` and `/transcript`
- Split dev: `adgn-mini-codex serve` (backend) + `npm --prefix src/adgn/agent/web run dev` (optionally set `VITE_BACKEND_ORIGIN=http://127.0.0.1:8765`)
- Build assets (REQUIRED before `serve`):
  - `npm --prefix src/adgn/agent/web install`
  - `npm --prefix src/adgn/agent/web run build`
- Assets output to: `src/adgn/agent/server/static/web`; FastAPI serves `/static/web` and `/assets`
- Troubleshooting:
  - Build UI assets before `serve` to avoid the “missing static directory” RuntimeError
  - If some MCP servers fail at startup, the UI still serves; check terminal logs for failing names/exceptions
  - Use hard refresh after rebuilding assets; server logs include “WS OUT” at `log_level=debug`

## LLM Toolkit and CLIs
- Core scripts (see `[project.scripts]`):
  - `adgn-mini-codex` → MiniCodex UI/REPL
  - `adgn-llm-edit` → `adgn.llm.llm_edit:app`
  - `adgn-sysrw` → `adgn.llm.sysrw.cli:app`
  - `adgn-properties` → `adgn.props.cli:main` (also `adgn-properties` Typer UI)
  - `git-commit-ai` → `adgn.git_commit_ai.cli:main`
  - `sandbox-jupyter` → `adgn.mcp.sandboxed_jupyter.wrapper:main`
  - Other helpers: `adgn-openai-probe`, `adgn-sandboxer`, `adgn-mcp-*`, `adgn-matrix-bot`
### Properties/specimens
- Schema (Pydantic source of truth):
  - @src/adgn/llm/properties/models/specimen.py
  - @src/adgn/llm/properties/models/issue.py
- Registry/loader:
  - @src/adgn/llm/properties/specimen_registry.py
- Authoring guide:
  - @src/adgn/props/CLAUDE.md
- Examples: `adgn-properties snapshot exec <snapshot-slug>`

### Testing LLM Code
- Typical: `direnv exec adgn pytest -q -m "not live_llm"`
- Excluding a suite: `-k "not sandboxed_jupyter"`
- `live_llm` tests require API keys and network access

### Bootstrap Handlers (Agent Initialization)
Bootstrap handlers inject synthetic function calls before the agent's first sampling cycle, providing initial context without requiring explicit agent requests.

**Pattern (immediate construction):**
```python
from adgn.agent.bootstrap import TypedBootstrapBuilder, BootstrapHandler, read_resource_call, docker_exec_call

# Create builder with introspection (validates payload types against server schema)
builder = TypedBootstrapBuilder.for_server(runtime_server)

# Build calls immediately - no factories, no inheritance
calls = [
    read_resource_call(builder, server="resources", uri="resource://foo/bar"),
    docker_exec_call(builder, server="runtime", cmd=["ls", "-la"]),
]

# Create handler
bootstrap = BootstrapHandler(calls)
handlers = [bootstrap, ...other handlers...]
```

**Key principles:**
- Builder instances are local (no global state)
- Auto-generates call_ids (no manual management needed)
- Type-safe: Pydantic payloads validated via introspection
- Immediate construction (not factories/lambdas)
- Helper functions for common patterns: `read_resource_call()`, `docker_exec_call()`

**Future enhancement:** See `docs/bootstrap_type_safety_plans.md` for plans to eliminate string literals via generic/typed stubs

## Conventions and Tips
- MCP naming
  - When composing MCP tool names programmatically, use `build_mcp_function(server, tool)` from `adgn.mcp._shared.naming`.
  - Avoid hard-coded strings like `server_tool` in code. Literal forms in docs/examples are illustrative only.
- FastMCP error handling
  - Do not wrap tool bodies in broad try/except. Uncaught exceptions become MCP errors (`isError=true`) with messages.
  - Prefer Pydantic models for inputs/outputs; validation errors surface as MCP errors automatically.
- Logging
  - Declare a module‑level logger at the top of every module: `logger = logging.getLogger(__name__)`
  - Do not call `logging.getLogger(...)` inside functions/classes; use the module‑level `logger` instead.
  - Do not store the module‑level logger on `self` (e.g., `self._logger = ...`). Refer to the module‑level `logger` directly.
- Arg0 virtual CLIs
  - Virtual commands are exposed by argv0 name on PATH, e.g., `apply_patch` (`applypatch` alias) to apply OpenAI‑style patch envelopes
  - Symlink creation is strict; failures abort startup
- Import aliases
  - Avoid renaming imports unless there is a real collision or a widely
    accepted alias for the library.
- Paths
  - Prefer working with `pathlib.Path` objects directly; only call
    `str(path)` when an external API requires a string.
- MCP CallToolResult handling
  - Normalize FastMCP client results immediately by calling `fastmcp_to_mcp_result`. Downstream helpers should only accept `mcp.types.CallToolResult`.
- Typing discipline
  - Handle exact runtime types. When an external API returns a loose object, convert it at the boundary so the rest of the code sees a single concrete type.
  - During typing passes, scan for broad annotations (`Any`, `object`, large `Union`, untyped `dict`) with `rg` and tighten or document each occurrence. Treat unexplained permissive types as findings.
- Centralize boundary conversions (e.g., `_normalize_result`/`_call_structured`) instead of duplicating `isinstance` + conversion logic.
- Pydantic construction
  - Instantiate models with keyword arguments (e.g., `Model(field=value)`)
    rather than passing raw dictionaries.
  - When validating payloads, prefer `Model.model_validate(data)` and reserve
    `TypeAdapter(...).validate_python` for cases where no concrete model
    exists.
- MCP servers with agent‑specific state
  - Prefer constructors that accept per‑agent state (no hidden globals/singletons)
  - In‑proc servers are mounted on a `Compositor` (via `mount_inproc(...)`)

- Type annotations (no forward refs)
  - Avoid string‑based forward references in type annotations. Define dependent classes above their use, or split models/files to remove cycles.
  - When cross‑module cycles exist, use `if TYPE_CHECKING:` imports and keep annotations as real symbols (with `from __future__ import annotations`). Do not leave quoted type names like "MyType".
  - Do not rely on `model_rebuild()` to resolve forward refs in Pydantic where simple reordering can avoid them. Add a one‑line comment if a forward ref is truly unavoidable and why.

### MCP Conventions (Compositor, Resources, Subscriptions)
- Imports at top
  - Keep all imports at module top. Only import inside a function to break a proven circular dependency; add a one‑line comment at that import explaining the cycle. Do not add per‑file linters or mypy excludes without explicit approval.
- URI helpers, no literals
  - Use canonical constants/format strings from `adgn.mcp._shared.constants` instead of hard-coded strings:
    - `COMPOSITOR_META_STATE_URI_FMT.format(server=...)`, `.INSTRUCTIONS_URI_FMT`, `.CAPABILITIES_URI_FMT`
    - When matching state URIs, compare with `COMPOSITOR_META_STATE_URI_FMT`/`COMPOSITOR_META_URI_PREFIX`
  - Use `COMPOSITOR_ADMIN_SERVER_NAME` instead of the literal `"compositor_admin"`.
- Standard in‑proc mounts (pinned)
  - Mount `resources`, `compositor_meta`, and `compositor_admin` pinned by default. Prefer the helper:
    - `adgn.mcp.compositor.setup.mount_standard_inproc_servers(compositor, gateway_client=...)`
  - Pinned servers cannot be unmounted; pinning is supported only for in‑proc mounts, at mount time.
- Notifications
  - Use the `MountEvent` enum for Compositor mount listeners; no stringly‑typed actions.
  - Do not synthesize resource version counters; forward raw MCP notifications and group by server via the notifications buffer.
  - Do not manually broadcast resource list changes from the container; compositor_meta’s listener handles mount change notifications.
- Subscriptions index
  - Single resource only: `resources://subscriptions` (JSON). No per‑item resources for now.
  - Underlying remote subs are torn down implicitly on unmount (child session closes). The index is the model surface; it’s updated to remove non‑pinned records and mark pinned inactive.
  - Use `read_text_json` / `read_text_json_typed` helpers for reading JSON resources.
- Tests
  - Use PyHamcrest matchers (e.g., `instance_of`, `has_item`) instead of `hasattr` checks.
  - For resource JSON, use `read_text_json(session, uri)` or the typed variant. Avoid hand‑parsing `contents`.

### Linting and Typing
- Ruff
  - Run `ruff format .` and `ruff check . --fix` locally. Fix E402 (imports not at top) by moving imports to the top; do not add ignore rules unless explicitly approved.
- Mypy
  - Run `mypy --config-file pyproject.toml`. Do not add new excludes or ignore patterns without explicit approval. If vendor packages cause false positives (e.g., duplicate module name errors), scope checks to the edited subpackages (e.g., `mypy src/adgn/mcp/...`) while keeping the configuration unchanged.
- Codemod
  - Run `trivial-patterns --scope tests tests` alongside Ruff and mypy before handing off patches. Add more scopes with repeated flags or comma-separated values (e.g., `--scope tests,src/adgn`). Omit `--scope` to scan the entire project. The CLI wraps `adgn-trivial-patterns`; review its findings and fix or justify each one. Skip patterns live under `[tool.adgn.trivial-patterns]` in `pyproject.toml`.

### CallToolResult Conventions (MCP)
- Typed vs. client results
  - The FastMCP client returns a lightweight `CallToolResult` (not a Pydantic model).
  - Pydantic MCP types live under `mcp.types` (e.g., `mcp.types.CallToolResult`). Use these when you need typed validation/serialization.
- Central helpers
  - Use `adgn.mcp._shared.calltool.as_minimal_json(res)` to serialize a client `CallToolResult` for UI/logging/persistence. It returns:
    - `{structured_content?: Any, is_error: bool}` (snake_case keys; `structured_content` is JSON‑dumped if it was a Pydantic model).
  - Use `adgn.mcp._shared.calltool.fastmcp_to_mcp_result(res)` when you need a typed `mcp.types.CallToolResult` (uses alias names `structuredContent`/`isError`).
- Do not call `.model_dump()` on FastMCP’s client `CallToolResult` — it isn’t a Pydantic model. Either:
  - Serialize via `as_minimal_json(...)` for UI/logging, or
  - Adapt to `mcp.types.CallToolResult` via `fastmcp_to_mcp_result(...)` (or `TypeAdapter(mcp.types.CallToolResult).validate_python(...)` on an alias‑keyed dict).
- UI/tests convention
  - Prefer the minimal JSON shape in server→UI messages unless the full typed MCP result is required.
  - When tests need to validate structure, construct/validate against `mcp.types.CallToolResult` explicitly.

Runtime exec
- Runtime Docker MCP server name/tool: `runtime/exec` (shared constants).
- Host-side timeouts enforced for both ephemeral-per-call and per-session containers; timeouts surface and per-session containers are restarted when needed.

Approval Policy
- Policies are standalone Python programs executed in Docker. They read a JSON request from stdin and write a JSON response to stdout.
  - Input: `{name: "<server>_<tool>", arguments: {...}}`
  - Output: `{decision: "allow|deny_continue|deny_abort|ask", rationale?: str}`
- The active policy lives behind the MCP resource `resource://approval-policy/policy.py`. Proposals are managed via the approval policy server and persistence (no host volumes).
- A packaged minimal policy program is provided at `adgn.agent.policies.default_policy`.
- Changes to the active policy trigger `ResourceUpdated` for the canonical URI and the UI refreshes accordingly.

## Notes and Caveats
- GNOME console script deps require system libraries and are not in the default install; use the `[gnome]` extra as needed
- See `tana/export/lib` for the low-level parser modules (some use lazy imports to avoid cycles).
- Tests marked `real_github` or `live_llm` talk to network/services; run explicitly

## References and Further Reading
- MCP servers and presets: `docs/special_mcp_servers.md`
- Approval policy implementation: `src/adgn/agent/approvals.py`
- LLM docs: `docs/llm/*`
- Agent presets: see README.md "Agent Presets" and `examples/presets/*.yaml`

@instructions/jsonnet_authoring.md
@instructions/fastmcp_pydantic.md
@instructions/fastmcp_exceptions.md

---

# Agent Guidelines and Implicit DoD

Scope
- This file applies to the entire `adgn/` subtree and all files beneath it.

Implicit Definition of Done (DoD)
- These rules apply to all tasks unless the user explicitly overrides them. They include all DoD items provided by the user during collaboration, plus the project defaults.

General
- No suspicious nullability: If a field is optional, it must be for a clear transitional reason or represent an intentional, valid state with defined behavior. Otherwise, model as non‑nullable and remove guards.
- No dead code: Remove unused code, unused imports, and historical comments that no longer reflect the behavior.
- Imports at module top unless a documented circular dependency requires deferring (must be commented at the call site).
 - Place all imports at the top of files. Only use in‑function imports to break a proven circular dependency, and add a one‑line comment at that import explaining the cycle it avoids. Do not move imports into functions for scoping/perf.

- Avoid unnecessary renamed imports. Prefer `import foo` over `import foo as foo`/`import foo as bar` unless disambiguation is required; include a comment when the alias prevents a collision.
- No getattr/hasattr/setattr probing unless justified and documented.
- Tests should not use getattr/hasattr. Prefer direct attribute access with precise expectations; adjust fixtures or assertions instead of dynamic probing.
- Do not swallow exceptions. Either allow the framework to surface them or raise domain errors with structured details. Use narrow exception handling (catch specific exception types) and never use broad `except Exception:` unless you immediately re‑raise after adding context.
 - Never use bare `except:` or broad `except Exception:` as a silent fallback. When an operation fails (including snapshot/header building, server status assembly, or compositor queries), let the exception propagate or re‑raise with precise context. Do not "default" to empty values on error — these hide real faults and make failures harder to diagnose.
 - Data mapping must be strict. When parsing enums/typed values from persistence or inputs, do not ignore invalid values. Either validate early or raise; do not `continue` on exceptions.
  - Do not add redundant try/except that simply re‑raises. If you want failures to surface, call the typed function directly and let exceptions bubble. Example: when enriching sampling snapshots (e.g., calling `list_tools()` on a child server), do not wrap in a `try/except: raise`; omit the wrapper entirely.
- Prefer concise comprehensions and idiomatic patterns; keep public interfaces typed with Pydantic where appropriate.
- Full test suite passing; ruff + mypy clean.
 - Run `trivial-patterns --scope tests tests` alongside `ruff` and `mypy`; add scope entries for every directory you touched (`--scope tests --scope src/adgn`) or omit the flag to cover the whole project. Update `[tool.adgn.trivial-patterns]` in `pyproject.toml` if you need additional skip globs. Review both trivial alias and renamed import warnings before sending patches.
 - Prefer precise types. When values are heterogeneous, use discriminated unions, Protocols, TypedDicts, or concrete Pydantic models. For arbitrary JSON fields, use Pydantic’s `JsonValue` inline (do not create a project‑level alias). Using `Any`/`object` is acceptable only when a field truly allows any value (including non‑JSON types) and no stronger contract exists; document such cases.
 - Concurrency messages must be typed. Actor/mailbox patterns should use explicit dataclasses (or Pydantic models) for messages and result types — never `dict[str, T]`. This keeps cross‑task communication precise and verifiable.
 - Antipattern: do not use `dict.get(...)` on Pydantic/typed models. Access fields directly (`model.field`). If data starts as a dict, parse it into a typed model at the boundary and operate on typed fields. Only use `dict.get(...)` for truly untyped external payloads (e.g., raw DB rows, HTTP headers, environment vars), and prefer explicit `is None` checks over "or []" defaulting.
 - Antipattern: do not `model_dump()` just to re‑parse fields for logic. Use the typed attributes on the Pydantic object (e.g., `ReadResourceResult.contents`, `InitializeResult.capabilities`). Dump only at I/O boundaries (logging/serialization).
- Instantiate Pydantic models with keyword arguments (`Model(field=value)`) rather than passing dictionaries. When validating external payloads, prefer `Model.model_validate(data)` to `TypeAdapter(...).validate_python(...)` unless you explicitly need adapter semantics.

Runtime containerization / approval policy specifics
- Evaluation ALWAYS runs in Docker using a one‑off container. No `/trusted` or `/rw` mounts are used.
- Approval policy server exposes the active policy as a single read‑only resource and broadcasts `ResourceUpdated` using the canonical URI `resource://approval-policy/policy.py`.
- Seatbelt templates are managed by their MCP server; no host volume IO is assumed.

- Policy evaluation (server/tool)
- The policy middleware calls a private tool `decide({name, arguments}) -> {decision, rationale}` hosted on the `policy_reader` server. By default this tool is hidden; it may be exposed for testing.
- Backend detail is internal to the server (not DI): it may evaluate by spawning a one‑off container (`python -c <policy_source>`) or another curated backend. The runtime image is built from `docker/runtime/Dockerfile` and is selected via `ADGN_RUNTIME_IMAGE` (default `adgn-runtime:latest`).
- Env: `ADGN_RUNTIME_IMAGE`, `ADGN_POLICY_EVAL_TIMEOUT_SECS`, `ADGN_POLICY_EVAL_MEM`, `ADGN_POLICY_EVAL_NANO_CPUS`.

Testing policy decisions (advisory)
- Optional: expose `policy_reader.decide` to agent/human tokens for testing and planning.
- Advisory only: it does not create approval items or alter enforcement; the policy middleware still evaluates and enforces at execution time.
- Suggested UI affordance: “Test decision” action next to tool payload inspectors; render `{decision, rationale}` with a clear warning.

Docker images
- Do not silently ignore missing Docker images. Image lookups must raise when an image is not present (e.g., `docker.errors.ImageNotFound`). Avoid `try/except: pass` around image checks.

### Building images
- Runtime/policy container image (required for `container` mode):
- Build the shared base: `docker build -t adgn-runtime:latest -f docker/runtime/Dockerfile .`
- Properties critic image:
  - `docker build -f docker/llm/properties-critic/Dockerfile -t adgn-llm/properties-critic:latest .`
- Override the runtime/policy image via `ADGN_RUNTIME_IMAGE` if you tag it differently.

Tests
- Use explicit Pydantic IO types (e.g., `ExecInput`, `ExecResult`) with typed test clients; avoid guessing models from introspection maps.
- Use shared helpers/fixtures for repeated patterns (e.g., volume name derivation).
- Compositor admin tools (mount lifecycle)
- Server: `compositor_admin`; tools: `attach_server({name, spec})`, `detach_server({name})`, `list_mounts({})` (and optional `update_server`).
- Policy: agent/human may invoke; approval policy gates each call. Specs must be typed; mask secrets in logs/UI.
- Avoid trivial async wrappers
  - Do not add pass-through wrappers like `async def foo(): return self.bar()`.
  - Prefer a single implementation (async, when used in server/resource paths) and call it directly.
  - Example: for resource helpers, provide `async def read_...()` and avoid maintaining a sync twin plus an async wrapper.
