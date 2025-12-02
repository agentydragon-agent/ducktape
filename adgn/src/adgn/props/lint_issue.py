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
from adgn.agent.bootstrap import BootstrapHandler, TypedBootstrapBuilder, docker_exec_call, read_resource_call
from adgn.agent.event_renderer import DisplayEventsHandler
from adgn.agent.loop_control import Auto, Continue, NoLoopDecision, RequireAny
from adgn.agent.reducer import BaseHandler, GateUntil
from adgn.agent.transcript_handler import TranscriptHandler
from adgn.llm.rendering.rich_renderers import render_to_rich
from adgn.mcp._shared.constants import LINT_SUBMIT_SERVER_NAME, RUNTIME_CONTAINER_INFO_URI
from adgn.mcp._shared.naming import build_mcp_function
from adgn.mcp._shared.types import SimpleOk
from adgn.mcp.compositor.server import Compositor
from adgn.mcp.notifying_fastmcp import NotifyingFastMCP
from adgn.openai_utils.model import FunctionCallItem, OpenAIModelProto
from adgn.props.ids import BaseIssueID
from adgn.props.models.issue import IssueCore, LineRange, Occurrence
from adgn.props.models.lint import IssueLintFindingRecord, LintSubmitPayload, extract_corrections
from adgn.props.prompts.schemas import build_input_schemas_json
from adgn.props.prompts.util import render_prompt_template
from adgn.props.prop_utils import props_definitions_root
from adgn.props.runs_context import format_timestamp_session
from adgn.props.specimens.registry import SpecimenRegistry

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

    corrections = extract_corrections(obj.findings)

    if corrections:
        for pth, ranges in corrections.items():
            anchors_tbl.add_row(str(pth), ", ".join(r.format() for r in ranges))
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
    issue_id: BaseIssueID
    model: str = "gpt-5"
    dry_run: bool = False


BIG_THRESHOLD = 20480


def make_linter_bootstrap_calls(
    wiring: PropertiesDockerWiring, occ: Occurrence, content_root: Path, prop_host_paths: list[Path] | None = None
) -> list[FunctionCallItem]:
    """Build bootstrap function calls for linter agent.

    Returns initial function calls providing context about the container,
    workspace structure, and source files to review.

    Args:
        wiring: Docker container wiring configuration
        occ: Issue occurrence with files to inspect
        content_root: Host path to specimen content
        prop_host_paths: Optional property definition files to read

    Returns:
        List of FunctionCallItem objects for bootstrap injection
    """
    builder = TypedBootstrapBuilder(call_id_prefix="bootstrap")
    calls: list[FunctionCallItem] = []

    # Step 1: Container info
    calls.append(read_resource_call(builder, server=wiring.server_name, uri=RUNTIME_CONTAINER_INFO_URI))

    # Step 2: Directory listing
    files = list((occ.files or {}).keys())
    dirs = sorted({str(Path(p).parent) for p in files})
    if dirs:
        targets = [str(wiring.working_dir / d) for d in dirs]
        calls.append(docker_exec_call(builder, server=wiring.server_name, cmd=["ls", "-la", *targets]))

    # Step 3: File content (for small files only)
    sizes: dict[str, int] = {}
    for p in files:
        hp = (content_root / p).resolve()
        if not hp.is_file():
            raise SystemExit(f"Expected a regular file for occurrence path: {hp}")
        sizes[str(p)] = int(hp.stat().st_size)

    big_detected = any(size >= BIG_THRESHOLD for size in sizes.values())
    if files and not big_detected:
        for q in files:
            if sizes[str(q)] > BIG_THRESHOLD:
                continue
            container_path = wiring.working_dir / q
            calls.append(
                docker_exec_call(
                    builder,
                    server=wiring.server_name,
                    cmd=["nl", "-ba", "-w1", "-s", " ", str(container_path)],
                    timeout_ms=10_000,
                )
            )

    # Step 4: Property definition reads (if provided)
    if wiring and prop_host_paths:
        defs_dir = props_definitions_root().resolve()
        for host_p in prop_host_paths:
            rel = Path(host_p).resolve().relative_to(defs_dir).as_posix()
            cont_path = wiring.container_path_for_prop_rel(rel)
            calls.append(
                docker_exec_call(
                    builder,
                    server=wiring.server_name,
                    cmd=["nl", "-ba", "-w1", "-s", " ", str(cont_path)],
                    timeout_ms=10_000,
                )
            )

    return calls


class BootstrapInspectHandler(BaseHandler):
    """Shared bootstrap handler: emits container.info + ls workspace without sampling."""

    def __init__(self, wiring: PropertiesDockerWiring) -> None:
        self._wiring = wiring
        self._done: bool = False
        self._emitted: bool = False

    def on_before_sample(self):
        if self._done:
            return NoLoopDecision()
        # First cycle: emit synthetic calls, but do NOT mark done yet
        if not self._emitted:
            self._emitted = True
            builder = TypedBootstrapBuilder(call_id_prefix="bootstrap")
            calls = [
                read_resource_call(builder, server=self._wiring.server_name, uri=RUNTIME_CONTAINER_INFO_URI),
                docker_exec_call(
                    builder, server=self._wiring.server_name, cmd=["ls", "-la", str(self._wiring.working_dir)]
                ),
            ]
            return Continue(RequireAny(), inserts_input=tuple(calls), skip_sampling=True)
        # Second cycle: mark done and defer; subsequent cycles will continue normally
        self._done = True
        return NoLoopDecision()


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


# ---------------------------------------------------------------------------
# Shared core runner (used by tests and CLI)
# ---------------------------------------------------------------------------


async def lint_issue_run(
    specimen: str | None,
    issue_core: IssueCore,
    occurrence: Occurrence,
    *,
    client: OpenAIModelProto,
    handlers: list[BaseHandler] | None = None,
    content_root: Path | None = None,
    registry: SpecimenRegistry,
) -> LintSubmitPayload:
    """Run the lint-issue agent and return the exact structured payload.

    If content_root provided: uses it directly (caller manages hydration).
    If content_root not provided: hydrates specimen under $HOME/.cache.
    Launches in-proc submit server and docker_exec MCP with bootstrap injection
    and gating handlers as the CLI path.
    """
    submit_state = LintSubmitState()

    # If content_root provided, use it directly; otherwise hydrate
    if content_root is not None:
        # Caller manages hydration
        return await _lint_issue_run_with_hydrated_root(
            content_root, issue_core, occurrence, client, submit_state, handlers
        )

    # Hydrate and run
    if specimen is None:
        raise ValueError("Either specimen or content_root must be provided")

    async with registry.load_and_hydrate(Path(specimen).name) as hydrated:
        return await _lint_issue_run_with_hydrated_root(
            hydrated.content_root, issue_core, occurrence, client, submit_state, handlers
        )


async def _lint_issue_run_with_hydrated_root(
    content_root: Path,
    issue_core: IssueCore,
    occurrence: Occurrence,
    client: OpenAIModelProto,
    submit_state: LintSubmitState,
    handlers: list[BaseHandler] | None,
) -> LintSubmitPayload:
    """Core lint logic with pre-hydrated specimen root."""
    wiring = properties_docker_spec(content_root, mount_properties=True)

    props: list[Path] = []
    prompt = _build_prompt(
        issue_core,
        submit_tool_name=build_mcp_function("lint_submit", "submit_result"),
        occurrence=occurrence,
        wiring=wiring,
    )

    # Build bootstrap calls and handlers
    bootstrap_calls = make_linter_bootstrap_calls(
        wiring=wiring, occ=occurrence, content_root=content_root, prop_host_paths=props
    )

    # Bootstrap handler with _done flag for deferral coordination (matches BootstrapInspectHandler pattern)
    class BootstrapWithDone(BootstrapHandler):
        def __init__(self, calls):
            super().__init__(calls)
            self._done = False

        def on_before_sample(self):
            if self._done:
                return NoLoopDecision()
            if not self._injected:
                self._injected = True
                return Continue(tool_policy=Auto(), inserts_input=tuple(self._calls), skip_sampling=True)
            # Second cycle: mark done
            self._done = True
            return NoLoopDecision()

    bootstrap_handler = BootstrapWithDone(bootstrap_calls)
    # GateUntil defers while bootstrap hasn't completed (matches critic.py pattern)
    gate_handler = GateUntil(
        is_done=lambda: submit_state.result is not None, defer_when=lambda: not bootstrap_handler._done
    )

    # Build compositor and client
    comp = Compositor("compositor")
    await wiring.attach(comp)

    # Create lint submit server and mount in-proc
    submit_srv = NotifyingFastMCP(LINT_SUBMIT_SERVER_NAME, instructions="Lint submit")

    @submit_srv.flat_model()
    async def submit_result(result: LintSubmitPayload) -> SimpleOk:
        submit_state.result = result
        return SimpleOk(ok=True)

    await comp.mount_inproc(LINT_SUBMIT_SERVER_NAME, submit_srv)
    async with Client(comp) as mcp_client:
        agent = await MiniCodex.create(
            mcp_client=mcp_client,
            system="You are a code agent. Be concise.",
            client=client,
            handlers=[bootstrap_handler, gate_handler, *(handlers if handlers is not None else [])],
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
    issue_id: BaseIssueID,
    *,
    model: str = "gpt-5",
    dry_run: bool = False,
    occurrence_index: int,
    client: OpenAIModelProto,
) -> int:
    # Load and hydrate once (avoids rehydration in lint_issue_run)
    registry = SpecimenRegistry.from_package_resources()
    async with registry.load_and_hydrate(specimen) as hydrated:
        irec = hydrated.issues[issue_id]

        # Require a single occurrence; do not run on the full issue or mutate the Issue
        if not (0 <= occurrence_index < len(irec.instances)):
            raise SystemExit(f"occurrence_index out of range: {occurrence_index} (instances={len(irec.instances)})")
        occ = irec.instances[occurrence_index]

        # Build submit tool name for dry-run prompt
        submit_tool_name = build_mcp_function("lint_submit", "submit_result")

        if dry_run:
            # Build a wiring for prompt rendering (no container launched in dry-run)
            # Use hydrated content_root for accurate wiring
            wiring = properties_docker_spec(hydrated.content_root, mount_properties=True)
            prompt = _build_prompt(
                irec.core,  # render via IssueCore + single occurrence
                submit_tool_name=submit_tool_name,
                occurrence=occ,
                wiring=wiring,
            )
            tmpdir = Path(tempfile.gettempdir()) / "adgn_codex_prompts"
            tmpdir.mkdir(parents=True, exist_ok=True)
            ts = format_timestamp_session()
            outfile = tmpdir / f"lint_issue_{issue_id}_{ts}.md"
            outfile.write_text(prompt, encoding="utf-8")
            print(f"[dry-run] Saved prompt: {outfile}")
            return 0

        # Shared core: run and capture structured payload (reuses hydrated content_root)
        # Add per-run transcript logger handler (logs/ for ad-hoc debugging)
        run_dir = Path.cwd() / "logs" / "mini_codex" / "lint_issue"
        run_dir = run_dir / f"run_{format_timestamp_session()}_{os.getpid()}"
        run_dir.mkdir(parents=True, exist_ok=True)

        res = await lint_issue_run(
            specimen=None,  # Not needed when content_root provided
            issue_core=irec.core,
            occurrence=occ,
            client=client,
            handlers=[DisplayEventsHandler(), TranscriptHandler(events_path=run_dir / "events.jsonl")],
            content_root=hydrated.content_root,  # Reuse hydrated root (avoids rehydration)
            registry=registry,
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
