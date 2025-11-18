from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import tempfile
from typing import Any, cast

from fastmcp.client import Client
from rich.console import Console, ConsoleRenderable, Group
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from adgn.agent.agent import MiniCodex
from adgn.agent.event_renderer import DisplayEventsHandler
from adgn.agent.loop_control import Abort, Auto, Continue, RequireAny
from adgn.agent.reducer import BaseHandler
from adgn.agent.transcript_handler import TranscriptHandler
from adgn.llm.rendering.rich_renderers import render_to_rich
from adgn.mcp._shared.constants import LINT_SUBMIT_SERVER_NAME
from adgn.mcp._shared.naming import build_mcp_function
from adgn.mcp._shared.types import SimpleOk
from adgn.mcp.compositor.server import Compositor
from adgn.mcp.exec.models import ExecInput
from adgn.mcp.notifying_fastmcp import NotifyingFastMCP
from adgn.openai_utils.builders import make_item_tool_call
from adgn.openai_utils.model import FunctionCallItem, OpenAIModelProto
from adgn.props.models.issue import IssueCore, IssueId, LineRange, Occurrence
from adgn.props.models.lint import AnchorIncorrect, IssueLintFindingRecord, LintSubmitPayload
from adgn.props.prompts.util import build_input_schemas_json, render_prompt_template
from adgn.props.prop_utils import pkg_dir, props_definitions_root
from adgn.props.specimens.registry import SpecimenRegistry

from .cli_shared import now_ts
from .docker_env import PropertiesDockerWiring, properties_docker_spec

# ---------------------------------------------------------------------------
# Lint submit MCP server + shared state (accessible to controller and server)
# ---------------------------------------------------------------------------


class LintSubmitState:
    result: LintSubmitPayload | None = None


# Register Rich renderer for LintSubmitPayload here to avoid import cycles
@render_to_rich.register
def _render_lint_submit_payload(obj: LintSubmitPayload):
    # Anchors table - derive corrections from findings (AnchorIncorrect) when present
    anchors_tbl = Table(title=None, show_lines=False, expand=True)
    anchors_tbl.add_column("Path", style="cyan")
    anchors_tbl.add_column("Ranges", style="magenta")

    corrections: dict[str, list[LineRange]] = {}
    if obj.findings:
        for fr in obj.findings:
            f = fr.finding
            if isinstance(f, AnchorIncorrect):
                corr = f.correction
                corrections.setdefault(corr.file, []).append(corr.range)

    if corrections:
        for pth, ranges in corrections.items():
            spans = ", ".join(
                (f"[{r.start_line}, {r.end_line}]" if r.end_line is not None else f"[{r.start_line}]") for r in ranges
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
            find = fr.finding
            kind = find.kind
            # Render details via our Rich renderer (assume implementation present)
            detail_render = render_to_rich(find)
            rationale_text = fr.rationale or ""
            findings_tbl.add_row(kind, detail_render, rationale_text)
    else:
        findings_tbl.add_row("(no findings)", "", "")
    bits.append(findings_tbl)

    if obj.message_md:
        bits.append(Markdown(obj.message_md))

    body: ConsoleRenderable = bits[0] if len(bits) == 1 else cast(ConsoleRenderable, Group(*tuple(bits)))
    return Panel(body, title="Lint result")


def make_lint_submit_server(state: LintSubmitState, *, name: str = "lint_submit") -> NotifyingFastMCP:
    """Tiny FastMCP server exposing a single tool: submit_result.

    The linter agent must call this exactly once to signal completion. This flips
    shared state so the loop controller will stop the run on the next sampling step.
    """
    mcp = NotifyingFastMCP(name, instructions="Final result submission for linting run")

    @mcp.flat_model(structured_output=True)
    async def submit_result(input: LintSubmitPayload) -> SimpleOk:
        """Submit final linter result."""
        state.result = input
        return SimpleOk(ok=True)

    return mcp


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------


@dataclass
class LintConfig:
    specimen: str
    issue_id: IssueId
    model: str = "gpt-5"
    dry_run: bool = False


def make_nl_tool_call(server_name: str, container_path: Path, call_id: str) -> FunctionCallItem:
    """Create a docker exec tool call to render a file with line numbers.

    Reads the entire file (no size cap) using `nl -ba -w1 -s ' ' <path>`.
    """
    return make_item_tool_call(
        call_id=call_id,
        name=build_mcp_function(server_name, DOCKER_EXEC_TOOL_NAME),
        arguments=ExecInput(cmd=["nl", "-ba", "-w1", "-s", " ", str(container_path)], timeout_ms=10_000).model_dump(),
    )


def make_container_info_call(wiring: PropertiesDockerWiring) -> FunctionCallItem:
    """resources.read for resource://container.info on the docker server."""
    return make_item_tool_call(
        call_id="bootstrap:res",
        name=build_mcp_function("resources", "read"),
        arguments={
            "server": wiring.server_name,
            "uri": "resource://container.info",
            "start_offset": 0,
            "max_bytes": 65536,
        },
    )


def make_ls_workspace_call(wiring: PropertiesDockerWiring, subpaths: list[str] | None = None) -> FunctionCallItem:
    """docker_exec ls -la for /workspace or provided subpaths."""
    targets = [str(wiring.working_dir)] if not subpaths else [str(wiring.working_dir / p) for p in subpaths]
    return make_item_tool_call(
        call_id="bootstrap:ls",
        name=build_mcp_function(wiring.server_name, DOCKER_EXEC_TOOL_NAME),
        arguments=ExecInput(cmd=["ls", "-la", *targets], timeout_ms=10_000).model_dump(),
    )


# TODO(mpokorny): Bridge: accept (IssueCore, Occurrence) now; migrate to IssueDoc
# (header + occurrences) and select a single occurrence here. Keep emitted JSON
# header-only (no id) by design for model context hygiene; remove legacy Issue.


def _build_prompt(
    issue: IssueCore, *, submit_tool_name: str, occurrence: Occurrence, wiring: PropertiesDockerWiring
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

    prompt_md: str = render_prompt_template(
        "lint_issue.j2.md",
        issue_json=issue_json,
        docker_tool_name=docker_tool_name,
        submit_tool_name=submit_tool_name,
        wiring=wiring,
        schemas_json=schemas_json,
    )
    return prompt_md


BIG_THRESHOLD = 20480


class LinterController(BaseHandler):
    """LinterController (purpose-specific) with integrated display + tool policy

    TODO(mpokorny): Split bootstrap from gating and rely on GateUntil for the
    steady-state loop; keep this class focused on composing SyntheticAction
    bootstrap sequences only.
    """

    def __init__(
        self,
        *,
        state: LintSubmitState,
        occ: Occurrence,
        content_root: Path,
        docker_wiring: PropertiesDockerWiring,
        prop_host_paths: list[Path] | None = None,
    ) -> None:
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
            make_item_tool_call(
                call_id="bootstrap:res",
                name=build_mcp_function("resources", "read"),
                arguments={
                    "server": self._wiring.server_name,
                    "uri": "resource://container.info",
                    "start_offset": 0,
                    "max_bytes": 65536,
                },
            )
        ]
        if self._dirs:
            self._step2 = [
                make_item_tool_call(
                    call_id="bootstrap:ls",
                    name=build_mcp_function(self._wiring.server_name, DOCKER_EXEC_TOOL_NAME),
                    arguments={"cmd": ["ls", "-la"] + [str(self._wiring.working_dir / d) for d in self._dirs]},
                )
            ]
        else:
            self._step2 = []

        def _content_calls() -> list[FunctionCallItem]:
            out: list[FunctionCallItem] = []
            for q in self._files:
                if sizes[q] > BIG_THRESHOLD:
                    continue
                out.append(
                    make_nl_tool_call(
                        self._wiring.server_name, self._wiring.working_dir / q, f"bootstrap:show:{len(out) + 1}"
                    )
                )
            return out

        self._step3 = _content_calls()
        # Property definition reads (full files, no cap)
        self._prop_calls: list[FunctionCallItem] = []
        if docker_wiring and prop_host_paths:
            defs_dir = props_definitions_root().resolve()
            for i, host_p in enumerate(prop_host_paths):
                rel = Path(host_p).resolve().relative_to(defs_dir).as_posix()
                cont_path = docker_wiring.container_path_for_prop_rel(rel)
                self._prop_calls.append(
                    make_nl_tool_call(self._wiring.server_name, cont_path, f"bootstrap:prop:{i + 1}")
                )

    def on_before_sample(self):
        # Stop immediately once submit_result was called
        if self._state.result is not None:
            return Abort()
        # Bootstrap synthetic steps
        self._step += 1
        if self._step == 1:
            return Continue(Auto(), inserts_input=tuple(self._step1), skip_sampling=True)
        if self._step == 2 and self._step2:
            return Continue(Auto(), inserts_input=tuple(self._step2), skip_sampling=True)
        if self._step == 3 and self._files and not self._big_detected:
            return Continue(Auto(), inserts_input=tuple(self._step3), skip_sampling=True)
        if self._step == 4 and self._prop_calls:
            return Continue(Auto(), inserts_input=tuple(self._prop_calls), skip_sampling=True)
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
    client: OpenAIModelProto,
    gitconfig: str | None = None,
    handlers: list[BaseHandler] | None = None,
) -> LintSubmitPayload:
    """Run the lint-issue agent and return the exact structured payload.

    - Hydrates specimen under $HOME/.cache
    - Launches in-proc submit server and docker_exec MCP
    - Uses same LinterController bootstrap/tool policy as the CLI path
    """
    # Determine default gitconfig fallback (kept in sync with load_single_issue)
    if gitconfig is None:
        cfg = pkg_dir() / "gitconfig.local"
        if cfg.exists():
            gitconfig = str(cfg)
    gc_path = Path(gitconfig).expanduser().resolve() if gitconfig else None

    # Resolve specimen manifest for archive hydration (fail fast on errors)

    rec = SpecimenRegistry.load_strict(Path(specimen).name)

    submit_state = LintSubmitState()

    # Hydrate specimen via registry context manager (centralized cleanup)
    async with rec.hydrated_copy(gc_path) as content_root:
        # Build in-process FastMCP servers
        # Lint submit as tools-builder secured attach
        def _build_lint_submit_tools(s: NotifyingFastMCP) -> None:
            @s.flat_model()
            async def submit_result(result: LintSubmitPayload) -> SimpleOk:
                submit_state.result = result
                return SimpleOk(ok=True)

        wiring = properties_docker_spec(content_root, mount_properties=True)

        props: list[Path] = []
        prompt = _build_prompt(
            issue_core,
            submit_tool_name=build_mcp_function("lint_submit", "submit_result"),
            occurrence=occurrence,
            wiring=wiring,
        )

        # Controller: LinterController with identical bootstrap/tool policy
        ctrl = LinterController(
            state=submit_state, occ=occurrence, content_root=content_root, docker_wiring=wiring, prop_host_paths=props
        )

        # Build compositor and client
        comp = Compositor("compositor")
        await wiring.attach(comp)
        # Create a small server and mount in-proc (no auth)
        submit_srv = NotifyingFastMCP(LINT_SUBMIT_SERVER_NAME, instructions="Lint submit")
        _build_lint_submit_tools(submit_srv)
        await comp.mount_inproc(LINT_SUBMIT_SERVER_NAME, submit_srv)
        async with Client(comp) as mcp_client:
            agent = await MiniCodex.create(
                model=model,
                mcp_client=mcp_client,
                system="You are a code agent. Be concise.",
                client=client,
                handlers=[ctrl, *(handlers if handlers is not None else [])],
                parallel_tool_calls=True,
            )
            await agent.run(prompt)

    assert submit_state.result, "submit_result somehow not called?"
    result: LintSubmitPayload = submit_state.result
    return result


# ---------------------------------------------------------------------------
# CLI entry
# ---------------------------------------------------------------------------


async def run_specimen_lint_issue_async(
    specimen: str,
    issue_id: IssueId,
    *,
    model: str = "gpt-5",
    dry_run: bool = False,
    gitconfig: str | None = None,
    occurrence_index: int,
    client: OpenAIModelProto,
) -> int:
    # Resolve specimen/issue via registry (strict load; crash on invalid specimen/issues)
    rec = SpecimenRegistry.load_strict(specimen)
    try:
        irec = rec.issues[issue_id]
    except KeyError:
        raise SystemExit(f"Issue id not found in specimen issues: {issue_id}") from None

    # Require a single occurrence; do not run on the full issue or mutate the Issue
    if not (0 <= occurrence_index < len(irec.instances)):
        raise SystemExit(f"occurrence_index out of range: {occurrence_index} (instances={len(irec.instances)})")
    occ = irec.instances[occurrence_index]

    # Build submit tool name for dry-run prompt
    submit_tool_name = build_mcp_function("lint_submit", "submit_result")

    if dry_run:
        # Build a wiring for prompt rendering (no container launched in dry-run)
        # any existing directory works for template context
        dummy_root = pkg_dir()
        wiring = properties_docker_spec(dummy_root, mount_properties=True)
        prompt = _build_prompt(
            irec.core,  # render via IssueCore + single occurrence
            submit_tool_name=submit_tool_name,
            occurrence=occ,
            wiring=wiring,
        )
        tmpdir = Path(tempfile.gettempdir()) / "adgn_codex_prompts"
        tmpdir.mkdir(parents=True, exist_ok=True)
        ts = now_ts()
        outfile = tmpdir / f"lint_issue_{issue_id}_{ts}.md"
        outfile.write_text(prompt, encoding="utf-8")
        print(f"[dry-run] Saved prompt: {outfile}")
        return 0

    # Shared core: run and capture structured payload
    # Add per-run transcript logger handler
    run_dir = Path.cwd() / "logs" / "mini_codex" / "lint_issue"
    run_dir = run_dir / f"run_{now_ts()}_{os.getpid()}"
    run_dir.mkdir(parents=True, exist_ok=True)

    res = await lint_issue_run(
        specimen,
        irec.core,
        occ,
        model=model,
        gitconfig=gitconfig,
        client=client,
        handlers=[DisplayEventsHandler(), TranscriptHandler(dest_dir=run_dir)],
    )

    # Print the exact occurrence representation as fed to the model
    issue_dict = irec.core.model_dump(exclude_none=True)
    issue_dict.pop("id", None)
    occ_dict: dict[str, Any] = occ.model_dump(exclude_none=True)
    issue_dict["instances"] = [occ_dict]
    issue_json = json.dumps(issue_dict, ensure_ascii=False)
    print("Issue (JSON):")
    print(issue_json)

    # Pretty-print final agent output via Rich renderer
    Console().print(render_to_rich(res))
    return 0


# Generic docker exec tool identifiers
DOCKER_SERVER_NAME = "docker"
DOCKER_EXEC_TOOL_NAME = "exec"
