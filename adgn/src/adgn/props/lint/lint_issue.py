from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
import json
import os
from pathlib import Path
import tempfile
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from adgn.mcp._shared.mounted import Mounted

import aiodocker
from compact_json import Formatter  # type: ignore[import-untyped]
from fastmcp.client import Client
from fastmcp.tools import FunctionTool
from jinja2 import Environment, PackageLoader
from pydantic import BaseModel
from rich.console import Console, ConsoleRenderable, Group
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from adgn.agent.agent import Agent
from adgn.agent.bootstrap import TypedBootstrapBuilder, docker_exec_call
from adgn.agent.display import DisplayEventsHandler
from adgn.agent.handler import AbortIf, BaseHandler, SequenceHandler
from adgn.agent.loop_control import InjectItems, RequireAnyTool
from adgn.agent.transcript_handler import TranscriptHandler
from adgn.llm.rendering.rich_renderers import render_to_rich
from adgn.mcp._shared.types import SimpleOk
from adgn.mcp.enhanced import EnhancedFastMCP
from adgn.mcp.exec.docker.server import ContainerExecServer
from adgn.mcp.resources.server import ResourcesServer
from adgn.openai_utils.json_schema import openai_json_schema
from adgn.openai_utils.model import FunctionCallItem, OpenAIModelProto, UserMessage
from adgn.props.db import get_session
from adgn.props.db.models import Snapshot
from adgn.props.docker_env import PropertiesDockerCompositor
from adgn.props.hydration import SnapshotHydrator
from adgn.props.ids import BaseIssueID, SnapshotSlug
from adgn.props.models.lint import IssueLintFindingRecord, LintSubmitPayload, extract_corrections
from adgn.props.models.true_positive import IssueCore, LineRange, Occurrence
from adgn.props.rationale import Rationale
from adgn.props.runs_context import format_timestamp_session


def _compact_json_filter(value: Any, max_width: int = 100) -> str:
    """Jinja2 filter for compact JSON formatting."""
    formatter = Formatter(max_inline_length=max_width)
    return formatter.serialize(value)  # type: ignore[no-any-return]


def _get_templates_env() -> Environment:
    """Load prompt templates from the installed package."""
    env = Environment(loader=PackageLoader("adgn", "props"), autoescape=False, trim_blocks=True, lstrip_blocks=True)
    env.filters["compactjson"] = _compact_json_filter
    return env


def _render_lint_prompt(*, issue_json: str, compositor: object, schemas_json: dict[str, dict[str, Any]]) -> str:
    """Render the lint issue prompt template."""
    env = _get_templates_env()
    tmpl = env.get_template("lint/prompt.j2.md")
    return str(tmpl.render(issue_json=issue_json, compositor=compositor, schemas_json=schemas_json)).strip()


def _build_input_schemas_json(models: Iterable[type[BaseModel]]) -> dict[str, dict[str, Any]]:
    """Return {ModelName: schema} for all given Pydantic models."""
    return {m.__name__: openai_json_schema(m) for m in models}


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


class LintSubmitServer(EnhancedFastMCP):
    """Lint submit MCP server with typed tool access.

    Provides submit_result tool for linting workflow.
    """

    # Tool reference (assigned in __init__)
    submit_result_tool: FunctionTool

    def __init__(self, state: LintSubmitState):
        """Create lint submit server with state container.

        Args:
            state: Lint submit state container
        """
        super().__init__("Lint Submit MCP Server", instructions="Final result submission for linting run")

        # Register tool - name derived from function name
        async def submit_result(input: LintSubmitPayload) -> SimpleOk:
            """Submit final linter result."""
            state.result = input
            return SimpleOk(ok=True)

        self.submit_result_tool = self.flat_model()(submit_result)


# ---------------------------------------------------------------------------
# Lint Issue Compositor (Phase 2 pattern)
# ---------------------------------------------------------------------------


class LintIssueCompositor(PropertiesDockerCompositor):
    """Compositor with lint issue servers pre-mounted.

    Inherits from PropertiesDockerCompositor, which provides:
    - runtime: Docker exec server (mounted by parent class)

    Adds:
    - lint_submit: Lint submission server
    """

    # Mounted server attributes (runtime inherited, lint_submit added here)
    lint_submit: Mounted[LintSubmitServer]

    def __init__(self, workspace_root: Path, docker_client: aiodocker.Docker, submit_state: LintSubmitState):
        """Create compositor with lint issue dependencies.

        Configuration is fixed for lint issue use case:
        - Network isolated (network_mode="none")
        - Read-only workspace (workspace_mode="ro")
        - No database connection
        - No extra binds

        Args:
            workspace_root: Path to workspace directory to mount in container.
            docker_client: Async Docker client (managed by caller).
            submit_state: Lint submit state container (shared with caller).
        """
        super().__init__(
            workspace_root,
            docker_client,
            hydrator=SnapshotHydrator.from_env(),
            db_conn=None,
            workspace_mode="ro",
            network_mode="none",
            extra_env=None,
            labels={"adgn.project": "props", "adgn.role": "lint"},
        )
        self._submit_state = submit_state

    async def __aenter__(self):
        """Start compositor and mount servers."""
        # Start parent compositor (mounts resources, compositor_meta, runtime)
        await super().__aenter__()

        # Mount lint submit server
        self.lint_submit = await self.mount_inproc("lint_submit", LintSubmitServer(self._submit_state), pinned=True)

        return self


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------


@dataclass
class LintConfig:
    snapshot: str
    tp_id: BaseIssueID
    model: str = "gpt-5"
    dry_run: bool = False


BIG_THRESHOLD = 20480


def make_linter_bootstrap_calls(
    compositor: PropertiesDockerCompositor, occ: Occurrence, content_root: Path
) -> list[FunctionCallItem]:
    """Build bootstrap function calls for linter agent.

    Returns initial function calls providing context about the container,
    workspace structure, and source files to review.

    Args:
        compositor: Properties compositor with Docker configuration
        occ: TruePositive occurrence with files to inspect
        content_root: Host path to specimen content

    Returns:
        List of FunctionCallItem objects for bootstrap injection
    """
    builder = TypedBootstrapBuilder(call_id_prefix="bootstrap")
    calls: list[FunctionCallItem] = []

    # Step 1: Container info
    calls.append(
        builder.read_resource(
            compositor.resources,
            server=compositor.runtime.prefix,
            uri=compositor.runtime.server.container_info_resource.uri,
        )
    )

    # Step 2: Directory listing
    files = [fo.path for fo in occ.files]
    dirs = sorted({str(Path(p).parent) for p in files})
    if dirs:
        calls.append(
            docker_exec_call(
                builder, compositor.runtime, cmd=["ls", "-la", *[compositor.working_dir / d for d in dirs]]
            )
        )

    # Step 3: Collect file content paths (for small files only)
    sizes: dict[str, int] = {}
    for p in files:
        hp = (content_root / p).resolve()
        if not hp.is_file():
            raise SystemExit(f"Expected a regular file for occurrence path: {hp}")
        sizes[str(p)] = int(hp.stat().st_size)

    paths_to_number: list[Path] = []
    big_detected = any(size >= BIG_THRESHOLD for size in sizes.values())
    if files and not big_detected:
        for q in files:
            if sizes[str(q)] > BIG_THRESHOLD:
                continue
            paths_to_number.append(compositor.working_dir / q)

    # Create numbered line calls for all collected paths
    calls.extend(
        docker_exec_call(builder, compositor.runtime, cmd=["nl", "-ba", "-w1", "-s", " ", path])
        for path in paths_to_number
    )

    return calls


def make_bootstrap_calls_for_inspection(
    compositor: PropertiesDockerCompositor, builder: TypedBootstrapBuilder
) -> list[FunctionCallItem]:
    """Build bootstrap calls for basic property inspection: container.info + ls workspace.

    Args:
        compositor: Properties Docker compositor (provides container config)
        builder: Bootstrap builder for generating typed tool calls
    """
    return [
        builder.read_resource(
            compositor.resources,
            server=compositor.runtime.prefix,
            uri=compositor.runtime.server.container_info_resource.uri,
        ),
        docker_exec_call(builder, compositor.runtime, cmd=["ls", "-la", compositor.working_dir]),
    ]


# TODO(mpokorny): Bridge: accept (IssueCore, Occurrence) now; migrate to IssueDoc
# (header + occurrences) and select a single occurrence here. Keep emitted JSON
# header-only (no id) by design for model context hygiene; remove legacy Issue.


def _build_prompt(issue: IssueCore, *, occurrence: Occurrence, compositor: LintIssueCompositor) -> str:
    # Do not include specimen slug or issue id. Include only issue fields.
    # The agent will read code from /workspace via MCP.
    issue_dict = issue.model_dump(exclude_none=True)
    issue_dict.pop("id", None)
    issue_dict["instances"] = [occurrence.model_dump(exclude_none=True)]
    issue_json = json.dumps(issue_dict, ensure_ascii=False)

    # Input schemas for the agent (always included)
    schemas_json = _build_input_schemas_json(
        (IssueCore, Occurrence, LineRange, LintSubmitPayload, IssueLintFindingRecord)
    )

    prompt_md: str = _render_lint_prompt(issue_json=issue_json, compositor=compositor, schemas_json=schemas_json)
    return prompt_md


def make_linter_handlers(
    *,
    state: LintSubmitState,
    resources: Mounted[ResourcesServer],
    runtime: Mounted[ContainerExecServer],
    occ: Occurrence,
    content_root: Path,
    compositor: PropertiesDockerCompositor,
) -> list:
    """Build handlers for linter agent: bootstrap + abort.

    Args:
        state: Linter submission state
        resources: Mounted resources server (comp.resources)
        runtime: Mounted runtime server (comp.runtime)
        occ: TruePositive occurrence with files to inspect
        content_root: Host path to specimen content
        compositor: Properties Docker compositor configuration

    Returns:
        [SequenceHandler, AbortIf] - bootstrap injects calls, abort when done
    """
    # Build all bootstrap calls upfront (continuous sequence)
    bootstrap_calls = make_linter_bootstrap_calls(compositor=compositor, occ=occ, content_root=content_root)

    # Return two handlers: bootstrap for injection, abort condition
    return [
        SequenceHandler([InjectItems(items=bootstrap_calls)]),
        AbortIf(should_abort=lambda: state.result is not None),
    ]


# ---------------------------------------------------------------------------
# Shared core runner (used by tests and CLI)
# ---------------------------------------------------------------------------


async def lint_issue_run(
    snapshot_slug: SnapshotSlug | None,
    issue_core: IssueCore,
    occurrence: Occurrence,
    *,
    client: OpenAIModelProto,
    docker_client: aiodocker.Docker,
    handlers: Sequence[BaseHandler] = (),
    content_root: Path | None = None,
    hydrator: SnapshotHydrator | None = None,
) -> LintSubmitPayload:
    """Run the lint-issue agent and return the exact structured payload.

    If content_root provided: uses it directly (caller manages hydration).
    If content_root not provided: hydrates snapshot source code using hydrator.
    Launches in-proc submit server and docker_exec MCP with bootstrap injection
    and gating handlers as the CLI path.
    """
    submit_state = LintSubmitState()

    # If content_root provided, use it directly; otherwise hydrate
    if content_root is not None:
        # Caller manages hydration
        return await _lint_issue_run_with_hydrated_root(
            content_root, issue_core, occurrence, client, docker_client, submit_state, handlers
        )

    # Hydrate source code and run
    if snapshot_slug is None:
        raise ValueError("Either snapshot_slug or content_root must be provided")
    if hydrator is None:
        raise ValueError("hydrator required when content_root not provided")

    async with hydrator.hydrate(snapshot_slug) as hydrated:
        return await _lint_issue_run_with_hydrated_root(
            hydrated.content_root, issue_core, occurrence, client, docker_client, submit_state, handlers
        )


async def _lint_issue_run_with_hydrated_root(
    content_root: Path,
    issue_core: IssueCore,
    occurrence: Occurrence,
    client: OpenAIModelProto,
    docker_client: aiodocker.Docker,
    submit_state: LintSubmitState,
    handlers: Sequence[BaseHandler],
) -> LintSubmitPayload:
    """Core lint logic with pre-hydrated snapshot root."""
    # Use LintIssueCompositor to bundle server mounting
    async with LintIssueCompositor(
        workspace_root=content_root, docker_client=docker_client, submit_state=submit_state
    ) as comp:
        prompt = _build_prompt(issue_core, occurrence=occurrence, compositor=comp)

        # Build bootstrap calls using Mounted[T] wrappers
        bootstrap_calls = make_linter_bootstrap_calls(compositor=comp, occ=occurrence, content_root=content_root)

        # Build handlers: bootstrap injection + abort condition
        # Sequential evaluation ensures bootstrap completes before abort check runs
        handlers_list = [
            SequenceHandler([InjectItems(items=bootstrap_calls)]),
            AbortIf(should_abort=lambda: submit_state.result is not None),
        ]

        # Add any extra handlers provided by caller
        handlers_list.extend(handlers)

        async with Client(comp) as mcp_client:
            agent = await Agent.create(
                mcp_client=mcp_client,
                client=client,
                handlers=handlers_list,
                dynamic_instructions=comp.render_agent_dynamic_instructions,
                parallel_tool_calls=True,
                tool_policy=RequireAnyTool(),
            )
            agent.insert_message(UserMessage.text(prompt))
            await agent.run()
    # Compositor.__aexit__ unmounts all non-pinned servers and cleans up containers here

    assert submit_state.result, "submit_result somehow not called?"
    result: LintSubmitPayload = submit_state.result
    return result


# ---------------------------------------------------------------------------
# CLI entry
# ---------------------------------------------------------------------------


async def run_specimen_lint_issue_async(
    snapshot_slug: SnapshotSlug,
    tp_id: BaseIssueID,
    *,
    model: str = "gpt-5",
    dry_run: bool = False,
    occurrence_index: int,
    client: OpenAIModelProto,
    docker_client: aiodocker.Docker,
    hydrator: SnapshotHydrator,
) -> int:
    # Load issues from database

    with get_session() as session:
        db_snapshot = session.query(Snapshot).filter_by(slug=snapshot_slug).one()
        # Find TP by id directly from ORM
        tp_orm = next((tp for tp in db_snapshot.true_positives if tp.tp_id == str(tp_id)), None)
        if tp_orm is None:
            raise SystemExit(f"True positive '{tp_id}' not found in snapshot '{snapshot_slug}'")

        # Require a single occurrence; do not run on the full issue or mutate the Issue
        if not (0 <= occurrence_index < len(tp_orm.occurrences)):
            raise SystemExit(
                f"occurrence_index out of range: {occurrence_index} (occurrences={len(tp_orm.occurrences)})"
            )
        tp_occ = tp_orm.occurrences[occurrence_index]
        # Convert TruePositiveOccurrence to Occurrence (drop expect_caught_from field)
        occ = Occurrence.from_files_dict(files=tp_occ.files, note=tp_occ.note)

        # Build IssueCore for lint prompt (id + rationale only)
        issue_core = IssueCore(id=BaseIssueID(tp_orm.tp_id), rationale=Rationale(tp_orm.rationale))

    # Hydrate source code for both dry-run and real execution
    async with hydrator.hydrate(snapshot_slug) as hydrated:
        if dry_run:
            # Build compositor and enter it to get mounted servers with proper tool names
            submit_state = LintSubmitState()
            async with LintIssueCompositor(
                workspace_root=hydrated.content_root, docker_client=docker_client, submit_state=submit_state
            ) as comp:
                prompt = _build_prompt(
                    issue_core,  # render via IssueCore + single occurrence
                    occurrence=occ,
                    compositor=comp,
                )
            tmpdir = Path(tempfile.gettempdir()) / "adgn_codex_prompts"
            tmpdir.mkdir(parents=True, exist_ok=True)
            ts = format_timestamp_session()
            outfile = tmpdir / f"lint_issue_{tp_id}_{ts}.md"
            outfile.write_text(prompt, encoding="utf-8")
            print(f"[dry-run] Saved prompt: {outfile}")
            return 0

        # Shared core: run and capture structured payload (reuses hydrated content_root)
        # Add per-run transcript logger handler (logs/ for ad-hoc debugging)
        run_dir = Path.cwd() / "logs" / "agent" / "lint_issue"
        run_dir = run_dir / f"run_{format_timestamp_session()}_{os.getpid()}"
        run_dir.mkdir(parents=True, exist_ok=True)

        res = await lint_issue_run(
            snapshot_slug=None,  # Not needed when content_root provided
            issue_core=issue_core,
            occurrence=occ,
            client=client,
            docker_client=docker_client,
            handlers=[DisplayEventsHandler(), TranscriptHandler(events_path=run_dir / "events.jsonl")],
            content_root=hydrated.content_root,  # Reuse hydrated root (avoids rehydration)
        )

        # Print the exact occurrence representation as fed to the model
        issue_dict = issue_core.model_dump(exclude_none=True)
        issue_dict.pop("id", None)
        occ_dict: dict[str, Any] = occ.model_dump(exclude_none=True)
        issue_dict["instances"] = [occ_dict]
        issue_json = json.dumps(issue_dict, ensure_ascii=False)
        print("Issue (JSON):")
        print(issue_json)

        # Pretty-print final agent output via Rich renderer
        Console().print(render_to_rich(res))
        return 0
