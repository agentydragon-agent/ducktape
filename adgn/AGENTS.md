# AGENTS.md — Agent Guide for `adgn`

This file helps AI agents work on the `adgn` package: environment setup, common commands, testing, module map, LLM tooling (Agent), MCP/approvals, and conventions.
See `README.md` for a shorter overview.

## Environment and Setup

See @../AGENTS.md for standard Bazel workflow (`bazel lint //...`, `bazel test //...`).

Requirements: Bazelisk (auto-downloads Bazel), Python 3.12+

Package-specific targets:
- Build: `bazel build //adgn:adgn`
- Test: `bazel test //adgn:tests`
- Run CLI: `bazel run //adgn:adgn-agent`

## Common Dev Commands

### Debugging hangs/timeouts
Run without xdist parallelization for clearer output: `bazel test //adgn:tests --test_arg=-n0 --test_arg=-v`

### Git pre-commit hook
Install with `pre-commit install`. This runs `bazel lint` on staged files, checks for conflict markers, and validates syntax.

## Pytest Defaults
See `[tool.pytest.ini_options]` in `pyproject.toml` for current `addopts`, markers, and timeout settings.
- Hermetic git (pytest-env): `GIT_CONFIG_NOSYSTEM=1`, `GIT_CONFIG_GLOBAL=/dev/null`

### UI E2E Tests (Playwright)
- Install browsers once: `python -m playwright install`
- Run: `bazel test //adgn:tests --test_arg=-m --test_arg="not live_openai_api" --test_arg=-k --test_arg=e2e`

## High‑Level Module Map
- Packaging: name `adgn`, Python `>=3.13`, src layout under `src/`
- Tana export tooling now lives in the sibling `tana/` project (`src/tana/export/`).
  - Key entry points: `convert.py`, `materialize_searches.py`, `export_node_subset.py`, plus helpers under `tana/export/lib/*`.
- Response cache (`src/adgn/rspcache/`)
  - `responses_db.py`; CLI `rspcache`
- LLM toolkit and agent (`src/adgn/llm/*`, `src/adgn/agent/*`, `src/adgn/mcp/*`, `src/adgn/props/*`)
  - Agent UI/server, MCP utilities, instruction optimizer, properties/specimens
- Seatbelt (`src/adgn/seatbelt/`) — sandbox policy validation and compilation
- Instruction optimizer (`src/adgn/inop/`) — Claude instruction optimization
- Tools (`src/adgn/tools/`) — `trivial_patterns` linter, arg0 utilities

## Agent (CLI + Local UI)
- Commands:
  - REPL: `adgn-agent run`
  - UI server: `adgn-agent serve` (opens WS UI at `http://127.0.0.1:8765/`)
  - Dev: `adgn-agent dev` (backend + Vite HMR; auto-picks free ports)
- Model/system defaults: `--model` (OPENAI_MODEL, default `gpt-5.1-codex-mini`), `--system` (SYSTEM_INSTRUCTIONS)
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
- Dev (recommended): `adgn-agent dev` — starts FastAPI + Vite, with proxying for `/ws` and `/transcript`
- Split dev: `adgn-agent serve` (backend) + `npm --prefix src/adgn/agent/web run dev` (optionally set `VITE_BACKEND_ORIGIN=http://127.0.0.1:8765`)
- Build assets (REQUIRED before `serve`):
  - `npm --prefix src/adgn/agent/web install`
  - `npm --prefix src/adgn/agent/web run build`
- Assets output to: `src/adgn/agent/server/static/web`; FastAPI serves `/static/web` and `/assets`
- Troubleshooting:
  - Build UI assets before `serve` to avoid the “missing static directory” RuntimeError
  - If some MCP servers fail at startup, the UI still serves; check terminal logs for failing names/exceptions
  - Use hard refresh after rebuilding assets; server logs include “WS OUT” at `log_level=debug`

## LLM Toolkit and CLIs
See `[project.scripts]` in `pyproject.toml` for the full list of CLI entry points.
### Properties/specimens
**For detailed props-specific documentation, see:**
- @src/adgn/props/AGENTS.md — Complete guide to specimens, models, database, tooling, and workflows
- @src/adgn/props/CLAUDE.md — Props package conventions and authoring
- Quick start: `props run --snapshot <slug>` or `props snapshot exec <snapshot-slug>`

### Testing LLM Code
- Typical: `bazel test //adgn:tests --test_arg=-m --test_arg="not live_openai_api"`
- Excluding a suite: `--test_arg=-k --test_arg="not sandboxed_jupyter"`
- `live_openai_api` tests require OPENAI_API_KEY and network access

### Bootstrap Handlers (Agent Initialization)
Bootstrap handlers inject synthetic function calls before the agent's first sampling cycle, providing initial context without requiring explicit agent requests.

**Pattern (immediate construction):**
```python
from adgn.agent.bootstrap import TypedBootstrapBuilder, BootstrapHandler, docker_exec_call, read_package_file_call

# Create builder with introspection (validates payload types against server schema)
builder = TypedBootstrapBuilder.for_server(runtime_server)

# Create handler. Build calls immediately - no factories, no inheritance
bootstrap = BootstrapHandler([
    # Standalone helper functions:
    docker_exec_call(builder, server=runtime, cmd=["ls", "-la"]),
    read_package_file_call(builder, server=runtime, path="pyproject.toml"),
    # Method on builder for resource reads:
    builder.read_resource(comp.resources, server=some_mount, uri="resource://foo/bar"),
])
handlers = [bootstrap, ...other handlers...]
```

**Key principles:**
- Builder instances are local (no global state)
- Auto-generates call_ids (no manual management needed)
- Type-safe: Pydantic payloads validated via introspection
- Immediate construction (not factories/lambdas)
- Standalone helper: `docker_exec_call()`
- Builder method: `builder.read_resource()` for resources server reads

**Future enhancement:** See `src/adgn/agent/docs/bootstrap_type_safety.md` for plans to eliminate string literals via generic/typed stubs

## Conventions and Tips
- Production code changes and test updates
  - When editing production code in `src/...`, always check what code in `tests/...` uses the interfaces/bits you touched and propagate any necessary edits.
  - Type signature changes, parameter additions/removals, renamed functions/classes, or changed behavior patterns all require corresponding test updates.
  - Example: Changing a function's type from `set[Path]` to `list[str]` requires updating all test callsites that pass data to that function.
  - Run mypy on both `src/` and `tests/` to catch type mismatches after interface changes.
- MCP naming
  - When composing MCP tool names programmatically, use `build_mcp_function(server, tool)` from `mcp_infra.naming`.
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
  - FastMCP client returns `fastmcp.client.client.CallToolResult` (snake_case fields: `is_error`, `structured_content`). MCP Pydantic uses `mcp.types.CallToolResult` (camelCase aliases: `isError`, `structuredContent`). Use the appropriate type at each layer.
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
  - Use canonical constants/format strings from `mcp_infra.constants` instead of hard-coded strings:
    - `COMPOSITOR_META_STATE_URI_FMT.format(server=...)`, `.INSTRUCTIONS_URI_FMT`, `.CAPABILITIES_URI_FMT`
    - When matching state URIs, compare with `COMPOSITOR_META_STATE_URI_FMT`/`COMPOSITOR_META_URI_PREFIX`
  - Use `COMPOSITOR_ADMIN_SERVER_NAME` instead of the literal `"compositor_admin"`.
- Standard in‑proc mounts (pinned)
  - Mount `resources` and `compositor_meta` pinned by default:
    ```python
    await compositor.mount_inproc(
        "resources", make_resources_server(name="resources", compositor=compositor), pinned=True
    )
    compmeta_server = make_compositor_meta_server(compositor=compositor, name=COMPOSITOR_META_SERVER_NAME)
    await compositor.mount_inproc(COMPOSITOR_META_SERVER_NAME, compmeta_server, pinned=True)
    ```
  - If using policy engine, also mount its servers:
    ```python
    await compositor.mount_inproc(POLICY_READER_SERVER_NAME, policy_engine.reader)
    await compositor.mount_inproc(POLICY_PROPOSER_SERVER_NAME, policy_engine.policy_proposer)
    await compositor.mount_inproc(APPROVAL_ADMIN_SERVER_NAME, policy_engine.admin)
    ```
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

Do not add ignore rules or silence individual lint errors unless explicitly approved.

For codemod tasks, run `trivial-patterns` via Bazel (TODO: add trivial-patterns to Bazel aspects).

### CallToolResult Conventions (MCP)
- Typed vs. client results
  - The FastMCP client returns a lightweight `CallToolResult` dataclass (not a Pydantic model) with snake_case fields (`is_error`, `structured_content`).
  - Pydantic MCP types live under `mcp.types` (e.g., `mcp.types.CallToolResult`) with camelCase aliases (`isError`, `structuredContent`). Use these when you need typed validation/serialization.
- No central conversion helper
  - Convert between types at boundaries as needed. For simple cases, construct `mcp.types.CallToolResult(content=..., structuredContent=..., isError=...)` directly.
- Do not call `.model_dump()` on FastMCP's client `CallToolResult` — it isn't a Pydantic model.
- UI/tests convention
  - When tests need to validate structure, construct/validate against `mcp.types.CallToolResult` explicitly.

Runtime exec
- Runtime Docker MCP server name/tool: `runtime/exec` (shared constants).
- Host-side timeouts are enforced; if a command times out the session container is restarted before the next call.

Approval Policy
- Policies are standalone Python programs executed in Docker. They read a JSON request from stdin and write a JSON response to stdout.
  - Input: `{name: "<server>_<tool>", arguments: {...}}`
  - Output: `{decision: "allow|deny_continue|deny_abort|ask", rationale?: str}`
- The active policy lives behind the MCP resource `resource://approval-policy/policy.py`. Proposals are managed via the approval policy server and persistence (no host volumes).
- A packaged minimal policy program is provided at `adgn.agent.policies.default_policy`.
- Changes to the active policy trigger `ResourceUpdated` for the canonical URI and the UI refreshes accordingly.

## Notes and Caveats
- See `tana/export/lib` for the low-level parser modules (some use lazy imports to avoid cycles).
- Tests marked `real_github` or `live_openai_api` talk to network/services; run explicitly

## References and Further Reading
- Bootstrap type safety: `src/adgn/agent/docs/bootstrap_type_safety.md`
- Approval policy implementation: `src/adgn/agent/approvals.py`
- Agent presets: see README.md "Agent Presets" (if available)

@instructions/fastmcp_pydantic.md
@instructions/fastmcp_exceptions.md

---

# Agent Guidelines and Implicit DoD

Scope
- This file applies to the entire `adgn/` subtree and all files beneath it.

Implicit Definition of Done (DoD)
- These rules apply to all tasks unless the user explicitly overrides them. They include all DoD items provided by the user during collaboration, plus the project defaults.

General
@../../STYLE.md

- Full test suite passing; ruff + mypy clean.
 - Run `trivial-patterns --scope tests tests` alongside `ruff` and `mypy`; add scope entries for every directory you touched (`--scope tests --scope src/adgn`) or omit the flag to cover the whole project. Update `[tool.adgn.trivial-patterns]` in `pyproject.toml` if you need additional skip globs. Review both trivial alias and renamed import warnings before sending patches.

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
**Important:** Run all docker build commands from the workspace root (`ducktape/`), not from `adgn/`.
- Runtime/policy container image (required for `container` mode):
  - `docker build -t adgn-runtime:latest -f docker/runtime/Dockerfile .`
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
