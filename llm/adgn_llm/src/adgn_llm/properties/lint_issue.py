from __future__ import annotations

import json
import shutil
import tarfile
import tempfile
import time
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from openai import AsyncOpenAI
from openai.types.responses import ResponseFunctionToolCall

from adgn_llm.properties.prop_utils import properties_root, find_property_files
from adgn_llm.properties.specimen_utils import load_single_issue
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
    DisplayEventsMixin,
)
from .specimen_utils import (
    ensure_archive_for_specimen_slug,
    Occurrence,
    LineRange,
    Issue,
    IssueCore,
    Specimen,
)
from .prompt_utils import render_prompt_template, build_input_schemas_json
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field
from .docker_env import properties_docker_spec, PropertiesDockerWiring

# ---------------------------------------------------------------------------
# Lint submit MCP server + shared state (accessible to controller and server)
# ---------------------------------------------------------------------------


class ChecklistItem(BaseModel):
    """Hierarchical checklist for the agent's performed checks.

    May be per-property or general. Answer should be "YES"/"NO" when binary; free strings allowed when necessary.
    """

    item: str = Field(..., description="Checklist question or assertion")
    subitems: list["ChecklistItem"] = Field(default_factory=list, description="Nested checks under this item")
    log: str = Field(default="", description="Short log of evidence or steps taken")
    answer: bool | str = Field(
        ...,
        description="Answer; use boolean for binary (true/false); free text allowed when needed",
    )


class LintSubmitPayload(BaseModel):
    """Final linter result payload."""

    model_config = ConfigDict(extra="forbid")

    fail: bool = Field(
        ...,
        description="Set true if any property is violated; false if all checks pass.",
    )
    message_md: str = Field(..., description="Concise Markdown report; do not restate pass/fail.")
    corrected_anchors: dict[str, list[LineRange] | None] | None = Field(
        default=None,
        description=(
            "null or full replacement of Occurrence.files-style anchors: "
            "{path: [{start_line: int, end_line: int|null}] | null}"
        ),
    )
    checklist: list[ChecklistItem] | None = Field(
        default=None,
        description="Root checklist items (tree) summarizing checks performed (per-property or general)",
    )


def format_checklist(items: list["ChecklistItem"]) -> str:
    """Format a checklist tree for human-readable console output.

    - Boolean answers are printed as True/False; strings are shown verbatim
    - Multi-line logs are indented under a "log:" label
    - Subitems are indented two spaces deeper
    """

    def render_item(it: "ChecklistItem") -> str:
        lines = [f"- {it.item} -> {it.answer}"]
        if it.log:
            lines.append("  log:")
            lines.append(textwrap.indent(str(it.log).rstrip("\n"), "    "))
        for child in it.subitems:
            lines.append(textwrap.indent(render_item(child), "  "))
        return "\n".join(lines)

    return "\n".join(render_item(root) for root in items)


def format_corrected_anchors(ca: dict[str, list[LineRange] | None] | None) -> str:
    """Pretty-format corrected_anchors for console output.

    Example:
    Corrected anchors:
    - path/to/file.py:
      - [10]
      - [25, 30]
    - other/file.py: null
    """
    if ca is None:
        return ""
    lines: list[str] = ["Corrected anchors:"]
    for path, ranges in ca.items():
        if ranges is None:
            lines.append(f"- {path}: null")
            continue
        lines.append(f"- {path}:")
        for r in ranges:
            if r.end_line is None:
                lines.append(f"  - [{r.start_line}]")
            else:
                lines.append(f"  - [{r.start_line}, {r.end_line}]")
    return "\n".join(lines)


class LintSubmitState:
    result: LintSubmitPayload | None = None


def make_lint_submit_server(state: LintSubmitState, *, name: str = "lint_submit", occ: Occurrence) -> FastMCP:
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


def make_nl_tool_call(server_name: str, container_path: str, call_id: str) -> ResponseFunctionToolCall:
    """Create a docker exec tool call to render a file with line numbers.

    Reads the entire file (no size cap) using `nl -ba -w1 -s ' ' <path>`.
    """
    return ResponseFunctionToolCall(
        type="function_call",
        name=build_mcp_function(server_name, DOCKER_EXEC_TOOL_NAME),
        call_id=call_id,
        arguments=json.dumps({"cmd": ["nl", "-ba", "-w1", "-s", " ", container_path]}),
    )


def _build_prompt(
    issue: Issue,
    _property_md_files: list[Path],
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
    schemas_json = build_input_schemas_json((IssueCore, Occurrence, LineRange))

    return render_prompt_template(
        "lint_issue.j2.md",
        issue_json=issue_json,
        docker_tool_name=docker_tool_name,
        submit_tool_name=submit_tool_name,
        wiring=wiring,
        schemas_json=schemas_json,
    )


BIG_THRESHOLD = 20480


class LinterController(DisplayEventsMixin):
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
        super().__init__(renderer=renderer, show_text=False)
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
                    name=build_mcp_function(self._wiring.server_name, DOCKER_EXEC_TOOL_NAME),
                    call_id="bootstrap:ls",
                    arguments=json.dumps(
                        {"cmd": ["ls", "-la"] + [str(self._wiring.working_dir / d) for d in self._dirs]}
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
                        self._wiring.server_name, str(self._wiring.working_dir / q), f"bootstrap:show:{len(out) + 1}"
                    )
                )
            return out

        self._step3 = _content_calls()
        # Property definition reads (full files, no cap)
        self._prop_calls: list[ResponseFunctionToolCall] = []
        if docker_wiring and prop_host_paths:
            defs_dir = (properties_root() / "definitions").resolve()
            for i, host_p in enumerate(prop_host_paths):
                rel = Path(host_p).resolve().relative_to(defs_dir).as_posix()
                cont_path = docker_wiring.container_path_for_prop_rel(rel)
                self._prop_calls.append(
                    make_nl_tool_call(self._wiring.server_name, cont_path, f"bootstrap:prop:{i + 1}")
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

    # Resolve specimen manifest for archive hydration
    sp = Specimen.load(specimen)

    # Always mount from under $HOME to avoid Docker volume restrictions on /var/folders
    ts = int(time.time())
    name = f"lint_{ts}"
    mount_root = Path.home() / ".cache" / "adgn-llm" / "workspaces" / f"{specimen}_{name}"
    mount_root.mkdir(parents=True, exist_ok=True)

    submit_state = LintSubmitState()

    try:
        # Prepare mount directory under $HOME from cached archive; hard-fail if cache missing
        if mount_root.exists():
            shutil.rmtree(mount_root, ignore_errors=True)
        archive = ensure_archive_for_specimen_slug(sp.manifest, sp.manifest_path, gc_path)
        # Extract to mount_root
        with tarfile.open(archive, "r:gz") as tf:
            tf.extractall(mount_root)

        # Determine content root: expect exactly one top-level directory after extraction
        entries = [p for p in mount_root.iterdir() if p.is_dir()]
        if len(entries) != 1:
            raise SystemExit(
                f"Unexpected archive layout under {mount_root}; expected a single top-level directory",
            )
        content_root = entries[0]

        # Build in-process FastMCP servers
        submit_server = make_lint_submit_server(submit_state, name="lint_submit", occ=occurrence)
        submit_spec = make_inproc_slot_spec(submit_server)

        wiring = properties_docker_spec(content_root, mount_properties=True)
        specs: dict[str, ServerSlotSpec] = {wiring.server_name: wiring.server_spec, "lint_submit": submit_spec}

        props = find_property_files([str(p) for p in issue_core.properties])
        prompt = _build_prompt(
            issue_core,  # accepts IssueCore; template receives instance via 'instances=[occurrence]'
            props,
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
            renderer=ConsoleEventRenderer(show_text=False),
        )

        async with McpManager(specs) as mcp:
            agent = await MiniCodex.create(
                model=model,
                mcp=mcp,
                system="You are a code agent. Be concise.",
                client=cast(ResponsesClient, client),
            )
            await agent.run(prompt, controller=ctrl)

        assert submit_state.result is not None, "submit_result not called; should never happen."
        return submit_state.result  # type: ignore[return-value]

    finally:
        # Cleanup copied workspace
        if mount_root.exists():
            shutil.rmtree(mount_root, ignore_errors=True)


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
    _sp, _root, issue = load_single_issue(specimen, issue_id, gitconfig)
    issue = cast(Issue, issue)

    # Require a single occurrence; do not run on the full issue or mutate the Issue
    if occurrence_index < 0 or occurrence_index >= len(issue.instances):
        raise SystemExit(
            f"occurrence_index out of range: {occurrence_index} (instances={len(issue.instances)})",
        )
    occ = issue.instances[occurrence_index]

    # Build submit tool name for dry-run prompt
    submit_tool_name = build_mcp_function("lint_submit", "submit_result")

    if dry_run:
        props = find_property_files([str(p) for p in issue.properties])
        # Build a wiring for prompt rendering (no container launched in dry-run)
        dummy_root = properties_root()  # any existing directory works for template context
        wiring = properties_docker_spec(dummy_root, mount_properties=True)
        prompt = _build_prompt(
            IssueCore.from_issue(issue),  # render via IssueCore + single occurrence
            props,
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
    )

    # Print the exact occurrence representation as fed to the model
    issue_dict = IssueCore.from_issue(issue).model_dump(exclude_none=True)
    issue_dict.pop("id", None)
    occ_dict: dict[str, Any] = occ.model_dump(exclude_none=True)
    issue_dict["instances"] = [occ_dict]
    issue_json = json.dumps(issue_dict, ensure_ascii=False)
    print("Issue (JSON):")
    print(issue_json)
    print()

    if res.checklist:
        print("Checklist:")
        print(format_checklist(res.checklist))
        print()
    if res.corrected_anchors is not None:
        print(format_corrected_anchors(res.corrected_anchors))
        print()
    if res.message_md:
        print(res.message_md)
        print()

    return 0 if (res.fail is False) else 2
