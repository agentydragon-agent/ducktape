from __future__ import annotations

import json
import shutil
import tarfile
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from mcp.server.fastmcp import FastMCP
from adgn_llm.properties.prompts.util import (
    render_prompt_template,
    build_input_schemas_json,
)
from .docker_env import properties_docker_spec, PropertiesDockerWiring
from adgn_llm.mini_codex.event_renderer import DisplayEventsHandler
from adgn_llm.properties.specimen_registry import SpecimenRegistry

from rich.console import Console, Group, ConsoleRenderable
from rich.table import Table
from rich.panel import Panel
from rich.markdown import Markdown
from adgn_llm.rendering.rich_renderers import render_to_rich

from openai import AsyncOpenAI
from openai.types.responses import ResponseFunctionToolCall

from adgn_llm.properties.prop_utils import properties_root, find_property_files
from adgn_llm.mcp.docker_exec.server import (
    SERVER_NAME as DOCKER_SERVER_NAME,
    TOOL_EXEC_NAME as DOCKER_EXEC_TOOL_NAME,
)
from adgn_llm.mcp.inproc_transport import make_inproc_slot_spec
from adgn_llm.mini_codex.agent import MiniCodex, ResponsesClient
from adgn_llm.mini_codex.mcp_manager import McpManager, build_mcp_function
from adgn_llm.mcp.types import ServerSlotSpec
from adgn_llm.mini_codex.loop_control import (
    Continue,
    Abort,
    RequireAny,
    SyntheticAction,
)
from adgn_llm.mini_codex.event_renderer import (
    ConsoleEventRenderer,
)
from adgn_llm.mini_codex.aggregating_handler import BaseHandler
from adgn_llm.properties.models.issue import Occurrence, LineRange, Issue, IssueCore
from adgn_llm.properties.models.lint import (
    IssueLintFindingRecord,
    LintSubmitPayload,
)
from .specimen_registry import ensure_archive_for_specimen_slug


# ---- Issue lint finding models are defined in models/lint.py and imported above ----

# ---------------------------------------------------------------------------
# Lint submit MCP server + shared state (accessible to controller and server)
# ---------------------------------------------------------------------------


class LintSubmitState:
    result: LintSubmitPayload | None = None


# Register Rich renderer for LintSubmitPayload here to avoid import cycles
@render_to_rich.register
def _render_lint_submit_payload(obj: LintSubmitPayload):  # type: ignore[misc]
    # Anchors table - derive corrections from findings (AnchorIncorrect) when present
    anchors_tbl = Table(title=None, show_lines=False, expand=True)
    anchors_tbl.add_column("Path", style="cyan")
    anchors_tbl.add_column("Ranges", style="magenta")

    corrections: dict[str, list[LineRange]] = {}
    if obj.findings:
        for fr in obj.findings:
            f: Any = fr.finding
            if getattr(f, "kind", None) == "ANCHOR_INCORRECT":
                corr = getattr(f, "correction", None)
                if corr:
                    corrections.setdefault(corr.file, []).append(corr.range)

    if corrections:
        for pth, ranges in corrections.items():
            spans = ", ".join(
                (
                    f"[{r.start_line}, {r.end_line}]"
                    if r.end_line is not None
                    else f"[{r.start_line}]"
                )
                for r in ranges
            )
            anchors_tbl.add_row(pth, spans)
    else:
        anchors_tbl.add_row("(no corrections)", "")

    bits: list[ConsoleRenderable] = [anchors_tbl]
    if obj.suggested_rationale:
        bits.append(Markdown("### Suggested rationale\n" + obj.suggested_rationale))

    # Render findings
    # Findings table (always present)
    findings_tbl = Table(title="Findings", show_lines=False, expand=True)
    findings_tbl.add_column("Kind", style="cyan")
    findings_tbl.add_column("Details", style="magenta")
    findings_tbl.add_column("Rationale", style="green")
    if obj.findings:
        for fr in obj.findings:
            find: Any = fr.finding
            kind = getattr(find, "kind", type(find).__name__)
            # Render details via our Rich renderer (assume implementation present)
            detail_render = render_to_rich(find)
            rationale_text = fr.rationale or ""
            findings_tbl.add_row(kind, detail_render, rationale_text)
    else:
        findings_tbl.add_row("(no findings)", "", "")
    bits.append(findings_tbl)

    if obj.message_md:
        bits.append(Markdown(obj.message_md))

    body: ConsoleRenderable = (
        bits[0] if len(bits) == 1 else cast(ConsoleRenderable, Group(*tuple(bits)))
    )
    return Panel(body, title="Lint result")


def make_lint_submit_server(
    state: LintSubmitState, *, name: str = "lint_submit"
) -> FastMCP:
    """Tiny FastMCP server exposing a single tool: submit_result.

    The linter agent must call this exactly once to signal completion. This flips
    shared state so the loop controller will stop the run on the next sampling step.
    """
    mcp = FastMCP(name, instructions="Final result submission for linting run")

    @mcp.tool()
    async def submit_result(result: LintSubmitPayload) -> dict[str, Any]:
        """Submit final linter result."""
        state.result = result
        return {"ok": True}

    return mcp


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------


@dataclass
class LintConfig:
    specimen: str
    issue_id: str
    model: str = "gpt-5"
    dry_run: bool = False


def make_nl_tool_call(
    server_name: str, container_path: Path, call_id: str
) -> ResponseFunctionToolCall:
    """Create a docker exec tool call to render a file with line numbers.

    Reads the entire file (no size cap) using `nl -ba -w1 -s ' ' <path>`.
    """
    return ResponseFunctionToolCall(
        type="function_call",
        name=build_mcp_function(server_name, DOCKER_EXEC_TOOL_NAME),
        call_id=call_id,
        arguments=json.dumps(
            {"cmd": ["nl", "-ba", "-w1", "-s", " ", str(container_path)]}
        ),
    )


# TODO(mpokorny): Bridge: accept (IssueCore, Occurrence) now; migrate to IssueDoc
# (header + occurrences) and select a single occurrence here. Keep emitted JSON
# header-only (no id) by design for model context hygiene; remove legacy Issue.


def _build_prompt(
    issue: Issue | IssueCore,
    *,
    submit_tool_name: str,
    occurrence: Occurrence,
    wiring: PropertiesDockerWiring,
) -> str:
    # Do not include specimen slug or issue id. Include only issue fields.
    # The agent will read code from /workspace and property definitions from /props via MCP.
    issue_dict = issue.model_dump(exclude_none=True)
    issue_dict.pop("id", None)
    issue_dict["instances"] = [occurrence.model_dump(exclude_none=True)]
    issue_json = json.dumps(issue_dict, ensure_ascii=False)

    docker_tool_name = build_mcp_function(DOCKER_SERVER_NAME, DOCKER_EXEC_TOOL_NAME)

    # Input schemas for the agent (always included)
    schemas_json = build_input_schemas_json(
        (IssueCore, Occurrence, LineRange, LintSubmitPayload, IssueLintFindingRecord)
    )

    return render_prompt_template(
        "lint_issue.j2.md",
        issue_json=issue_json,
        docker_tool_name=docker_tool_name,
        submit_tool_name=submit_tool_name,
        wiring=wiring,
        schemas_json=schemas_json,
    )


BIG_THRESHOLD = 20480


class LinterController(BaseHandler):
    """LinterController (purpose-specific) with integrated display + tool policy"""

    def __init__(
        self,
        *,
        state: LintSubmitState,
        occ: Occurrence,
        content_root: Path,
        docker_wiring: PropertiesDockerWiring,
        prop_host_paths: list[Path] | None = None,
        renderer: ConsoleEventRenderer | None = None,
    ) -> None:
        # Initialize handler-style renderer (observer-only). Do not call super() with mixin args.
        self._renderer = renderer or ConsoleEventRenderer(show_text=False)
        self._state = state
        self._step = 0
        self._wiring = docker_wiring
        # Snapshot specimen inputs
        self._files = list((occ.files or {}).keys())
        self._dirs = sorted({str(Path(p).parent) for p in self._files})
        # Determine sizes and big-file detection
        sizes: dict[str, int] = {}
        for p in self._files:
            hp = (content_root / p).resolve()
            st = hp.stat()
            if not hp.is_file():
                raise SystemExit(f"Expected a regular file for occurrence path: {hp}")
            sizes[p] = int(st.st_size)
        self._big_detected = any(size >= BIG_THRESHOLD for size in sizes.values())
        # Pre-build synthetic steps
        self._step1 = [
            ResponseFunctionToolCall(
                type="function_call",
                name="mcp__resources__read",
                call_id="bootstrap:res",
                arguments=json.dumps(
                    {
                        "server": self._wiring.server_name,
                        "uri": "resource://container.info",
                        "start_offset": 0,
                        "max_bytes": 65536,
                    }
                ),
            )
        ]
        if self._dirs:
            self._step2 = [
                ResponseFunctionToolCall(
                    type="function_call",
                    name=build_mcp_function(
                        self._wiring.server_name, DOCKER_EXEC_TOOL_NAME
                    ),
                    call_id="bootstrap:ls",
                    arguments=json.dumps(
                        {
                            "cmd": ["ls", "-la"]
                            + [str(self._wiring.working_dir / d) for d in self._dirs]
                        }
                    ),
                )
            ]
        else:
            self._step2 = []

        def _content_calls() -> list[ResponseFunctionToolCall]:
            out: list[ResponseFunctionToolCall] = []
            for q in self._files:
                if sizes[q] > BIG_THRESHOLD:
                    continue
                out.append(
                    make_nl_tool_call(
                        self._wiring.server_name,
                        self._wiring.working_dir / q,
                        f"bootstrap:show:{len(out) + 1}",
                    )
                )
            return out

        self._step3 = _content_calls()
        # Property definition reads (full files, no cap)
        self._prop_calls: list[ResponseFunctionToolCall] = []
        if docker_wiring and prop_host_paths:
            defs_dir = (properties_root() / "props").resolve()
            for i, host_p in enumerate(prop_host_paths):
                rel = Path(host_p).resolve().relative_to(defs_dir).as_posix()
                cont_path = docker_wiring.container_path_for_prop_rel(rel)
                self._prop_calls.append(
                    make_nl_tool_call(
                        self._wiring.server_name, cont_path, f"bootstrap:prop:{i + 1}"
                    )
                )

    def on_before_sample(self):  # type: ignore[override]
        # Stop immediately once submit_result was called
        if self._state.result is not None:
            return Abort()
        # Bootstrap synthetic steps
        self._step += 1
        if self._step == 1:
            return SyntheticAction(outputs=self._step1)
        if self._step == 2 and self._step2:
            return SyntheticAction(outputs=self._step2)
        if self._step == 3 and self._files and not self._big_detected:
            return SyntheticAction(outputs=self._step3)
        if self._step == 4 and self._prop_calls:
            return SyntheticAction(outputs=self._prop_calls)
        # After bootstrap, always require a tool call until submit_result flips the switch
        return Continue(RequireAny())


# ---------------------------------------------------------------------------
# Shared core runner (used by tests and CLI)
# ---------------------------------------------------------------------------


async def lint_issue_run(
    specimen: str,
    issue_core: IssueCore,
    occurrence: Occurrence,
    *,
    model: str = "gpt-5",
    gitconfig: str | None = None,
    client: AsyncOpenAI,
    renderer: ConsoleEventRenderer | None = None,
) -> LintSubmitPayload:
    """Run the lint-issue agent and return the exact structured payload.

    - Hydrates the specimen workspace under $HOME/.cache to avoid Docker volume restrictions
    - Launches in-proc submit server and docker_exec MCP per properties_docker_spec
    - Uses the same LinterController bootstrap/tool policy as the CLI path
    """
    # Determine default gitconfig fallback (kept in sync with load_single_issue)
    if gitconfig is None:
        cfg = properties_root() / "gitconfig.local"
        if cfg.exists():
            gitconfig = str(cfg)
    gc_path = Path(gitconfig).expanduser().resolve() if gitconfig else None

    # Resolve specimen manifest for archive hydration (fail fast on errors)

    rec = SpecimenRegistry.load_strict(Path(specimen).name)

    submit_state = LintSubmitState()

    # Hydrate specimen via registry context manager (centralized cleanup)
    async with rec.hydrated_copy(gc_path) as content_root:
        # Build in-process FastMCP servers
        submit_server = make_lint_submit_server(submit_state, name="lint_submit")
        submit_spec = make_inproc_slot_spec(submit_server)

        wiring = properties_docker_spec(content_root, mount_properties=True)
        specs: dict[str, ServerSlotSpec] = {
            wiring.server_name: wiring.server_spec,
            "lint_submit": submit_spec,
        }

        props = find_property_files([str(p) for p in issue_core.properties])
        prompt = _build_prompt(
            issue_core,  # accepts IssueCore; template receives instance via 'instances=[occurrence]'
            submit_tool_name=build_mcp_function("lint_submit", "submit_result"),
            occurrence=occurrence,
            wiring=wiring,
        )

        # Controller: LinterController with identical bootstrap/tool policy
        ctrl = LinterController(
            state=submit_state,
            occ=occurrence,
            content_root=content_root,
            docker_wiring=wiring,
            prop_host_paths=props,
            renderer=renderer,
        )

        async with McpManager(specs) as mcp:
            # Register LinterController instance (ctrl) first so it provides loop decisions,
            # then register the display handler for rendering events.
            agent = await MiniCodex.create(
                model=model,
                mcp=mcp,
                system="You are a code agent. Be concise.",
                client=cast(ResponsesClient, client),
                handlers=[ctrl, DisplayEventsHandler()],
                parallel_tool_calls=True,
            )
            # Run without passing controller; loop control is provided by handlers.
            await agent.run(prompt)

    assert submit_state.result, "submit_result somehow not called?"
    return submit_state.result  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# CLI entry
# ---------------------------------------------------------------------------


async def run_specimen_lint_issue_async(
    specimen: str,
    issue_id: str,
    *,
    model: str = "gpt-5",
    dry_run: bool = False,
    gitconfig: str | None = None,
    occurrence_index: int,
    client: AsyncOpenAI,
) -> int:
    # Resolve specimen/issue via registry (strict load; crash on invalid specimen/issues)
    rec = SpecimenRegistry.load_strict(specimen)
    try:
        issue: Issue = rec.issues[issue_id]
    except KeyError:
        raise SystemExit(f"Issue id not found in specimen issues: {issue_id}")

    # Require a single occurrence; do not run on the full issue or mutate the Issue
    if not (0 <= occurrence_index < len(issue.instances)):
        raise SystemExit(
            f"occurrence_index out of range: {occurrence_index} (instances={len(issue.instances)})",
        )
    occ = issue.instances[occurrence_index]

    # Build submit tool name for dry-run prompt
    submit_tool_name = build_mcp_function("lint_submit", "submit_result")

    if dry_run:
        _ = find_property_files([str(p) for p in issue.properties])
        # Build a wiring for prompt rendering (no container launched in dry-run)
        # any existing directory works for template context
        dummy_root = properties_root()
        wiring = properties_docker_spec(dummy_root, mount_properties=True)
        prompt = _build_prompt(
            IssueCore.from_issue(issue),  # render via IssueCore + single occurrence
            submit_tool_name=submit_tool_name,
            occurrence=occ,
            wiring=wiring,
        )
        tmpdir = Path(tempfile.gettempdir()) / "adgn_codex_prompts"
        tmpdir.mkdir(parents=True, exist_ok=True)
        ts = int(time.time())
        outfile = tmpdir / f"lint_issue_{issue_id}_{ts}.md"
        outfile.write_text(prompt, encoding="utf-8")
        print(f"[dry-run] Saved prompt: {outfile}")
        return 0

    # Shared core: run and capture structured payload
    res = await lint_issue_run(
        specimen,
        IssueCore.from_issue(issue),
        occ,
        model=model,
        gitconfig=gitconfig,
        client=client,
        renderer=None,
    )

    # Print the exact occurrence representation as fed to the model
    issue_dict = IssueCore.from_issue(issue).model_dump(exclude_none=True)
    issue_dict.pop("id", None)
    occ_dict: dict[str, Any] = occ.model_dump(exclude_none=True)
    issue_dict["instances"] = [occ_dict]
    issue_json = json.dumps(issue_dict, ensure_ascii=False)
    print("Issue (JSON):")
    print(issue_json)

    # Pretty-print final agent output via Rich renderer
    Console().print(render_to_rich(res))
    return 0
